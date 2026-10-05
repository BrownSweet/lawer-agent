import io
import json
from datetime import timedelta

import pymupdf
import pytest
from crewai import BaseLLM
from PIL import Image

from law_backend.agents import execute_role
from law_backend.contracts import Draft, Finding, Review, verify_draft
from law_backend.db import Config, Material, Run, Session, now
from law_backend.fees import lawsuit_fee
from law_backend.materials import process_material
from law_backend.preferences import load_config
from law_backend.worker import Cancelled, claim_job, process_run, recover_stale


def add_material(client, case, name="证据.txt", data=None):
    data = data or "合成测试：甲方支付乙方人民币 10000 元，乙方确认收款。".encode()
    response = client.post(f"/api/cases/{case['id']}/materials", files={"file": (name, data)})
    assert response.status_code == 201, response.text
    return response.json()


def add_source(client, case, content="测试条文原文", version="2026"):
    return client.post(
        f"/api/cases/{case['id']}/sources",
        json={
            "title": "合成来源",
            "content": content,
            "version": version,
            "url": "https://example.gov.cn/law",
        },
    ).json()


def start_run(client, case, **kwargs):
    return client.post(f"/api/cases/{case['id']}/runs", json={"question": "整理事实与材料缺口", **kwargs})


def test_auth_csrf_and_malformed_length(client):
    assert client.get("/api/health").json()["database"] == "mysql"
    assert (
        client.post("/api/cases", headers={"X-Workspace-Request": ""}, json={"title": "blocked"}).status_code
        == 403
    )
    assert (
        client.post("/api/cases", headers={"content-length": "oops"}, json={"title": "blocked"}).status_code
        == 400
    )
    client.post("/api/logout")
    assert client.get("/api/cases").status_code == 401


def test_secret_encryption_and_patch_semantics(client):
    saved = client.patch(
        "/api/settings", json={"providers": {"deepseek": {"api_key": "fixture-private-key"}}}
    )
    assert saved.status_code == 200
    assert "fixture-private-key" not in saved.text
    assert saved.json()["providers"]["deepseek"]["has_key"] is True
    with Session() as db:
        assert "fixture-private-key" not in db.get(Config, 1).encrypted
    client.patch("/api/settings", json={"providers": {"deepseek": {"model": "test-model"}}})
    assert load_config()["providers"]["deepseek"]["api_key"] == "fixture-private-key"
    client.patch("/api/settings", json={"providers": {"deepseek": {"api_key": ""}}})
    assert client.get("/api/settings").json()["providers"]["deepseek"]["has_key"] is False


def test_immutable_source_versions(client, case):
    a = add_source(client, case)
    same = add_source(client, case)
    b = add_source(client, case, content="不同正文")
    c = add_source(client, case, version="2020")
    assert a["id"] == same["id"]
    assert len({a["id"], b["id"], c["id"]}) == 3
    assert all(s["validity"] == "未核验" for s in (a, b, c))
    assert client.get("/api/sources/" + a["id"]).json()["content"] == "测试条文原文"


def test_text_material_roundtrip(client, case):
    material = add_material(client, case)
    assert claim_job(Material, "processing") == material["id"]
    assert claim_job(Material, "processing") is None
    process_material(material["id"])
    pages = client.get(f"/api/materials/{material['id']}/pages").json()
    assert len(pages) == 1 and "10000" in pages[0]["text"]
    assert pages[0]["method"] == "text"
    assert "10000" in client.get(f"/api/materials/{material['id']}/file").text


def test_pdf_text_layer_and_pixels(client, case):
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), "SYNTHETIC EVIDENCE: payment of 10000 yuan confirmed on 2026-01-01.")
        raw = doc.tobytes()
    material = add_material(client, case, "sample.pdf", raw)
    process_material(material["id"])
    page = client.get(f"/api/materials/{material['id']}/pages").json()[0]
    assert page["method"] == "text" and "10000" in page["text"]
    assert client.get(f"/api/materials/{material['id']}/file?page=1").content.startswith(b"\x89PNG")


def test_image_pending_then_multimodal(client, case, monkeypatch):
    out = io.BytesIO()
    Image.new("RGB", (120, 80), "red").save(out, "PNG")
    material = add_material(client, case, "receipt.png", out.getvalue())
    process_material(material["id"])
    assert client.get(f"/api/cases/{case['id']}").json()["materials"][0]["status"] == "needs_vision"
    assert client.post(f"/api/materials/{material['id']}/reparse?vision=true").status_code == 400
    client.patch("/api/settings", json={"providers": {"deepseek": {"api_key": "local-stub"}}})
    calls = []

    def fake_chat(config, messages, **kwargs):
        calls.append(messages)
        return "模拟视觉响应：图片为红色，测试数据不构成真实证据。"

    monkeypatch.setattr("law_backend.materials.chat", fake_chat)
    assert client.post(f"/api/materials/{material['id']}/reparse?vision=true").status_code == 200
    process_material(material["id"])
    assert calls[0][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert client.get(f"/api/materials/{material['id']}/pages").json()[0]["method"] == "vision"


def test_bad_files_and_cross_case_boundaries(client, case, model_config):
    assert (
        client.post(
            f"/api/cases/{case['id']}/materials", files={"file": ("fake.pdf", b"not a PDF")}
        ).status_code
        == 400
    )
    other = client.post("/api/cases", json={"title": "另外案件"}).json()
    source = add_source(client, other)
    assert start_run(client, case, source_ids=[source["id"]]).status_code == 400


def test_queued_cancellation_releases_case(client, case, model_config):
    source = add_source(client, case)
    response = start_run(client, case, source_ids=[source["id"]])
    assert response.status_code == 202
    identity = response.json()["id"]
    assert start_run(client, case, source_ids=[source["id"]]).status_code == 409
    assert client.post(f"/api/runs/{identity}/cancel").status_code == 200
    row = client.get("/api/runs/" + identity).json()
    assert row["status"] == "cancelled" and row["finished_at"]
    assert claim_job(Run, "running") is None
    assert start_run(client, case, source_ids=[source["id"]]).status_code == 202


class StubLLM(BaseLLM):
    answer: str

    def call(self, messages, **kwargs):
        return self.answer

    def supports_function_calling(self):
        return False

    def supports_stop_words(self):
        return False


def role_executor(stage, context, schema):
    reference = next(iter(context["evidence"]))
    claim = {"text": "合成来源存在测试条文。", "citations": [reference], "kind": "fact"}
    finding = {
        "title": "本地测试",
        "summary": "使用合成响应验证框架链路",
        "claims": [claim],
        "timeline": [],
        "gaps": [],
    }
    value = finding
    if stage == "draft":
        value = {
            "title": "合成测试草稿",
            "summary": "此结果仅用于软件测试。",
            "sections": [finding],
            "next_steps": [],
            "limitations": ["模拟模型响应"],
        }
    if stage == "review":
        value = {
            "summary": "模拟复核",
            "items": [{"claim_index": 0, "verdict": "supported", "reason": "合成原文支持"}],
            "issues": [],
        }
    return execute_role(
        stage,
        context,
        schema,
        {},
        llm_override=StubLLM(model="local-offline-test", answer=json.dumps(value, ensure_ascii=False)),
    )


def test_real_crewai_flow_agents_mysql_and_sse_without_mcp(client, case, model_config, monkeypatch):
    async def forbidden_mcp(*args):
        raise AssertionError("Disabled MCP must not be called")

    monkeypatch.setattr("law_backend.worker.mcp_request", forbidden_mcp)
    source = add_source(client, case)
    identity = start_run(client, case, source_ids=[source["id"]]).json()["id"]
    assert claim_job(Run, "running") == identity
    process_run(identity, executor_override=role_executor)
    row = client.get("/api/runs/" + identity).json()
    assert row["status"] == "completed"
    assert set(row["outputs"]) == {"intake", "research", "draft", "review"}
    assert row["result"]["coverage"]["mcp"] == "disabled"
    assert row["result"]["claims"][0]["association"] == "linked"
    assert "S:" + source["id"] in row["result"]["evidence"]
    events = client.get("/api/runs/" + identity + "/events").text
    assert events.count("event: progress") == 10 and "event: finished" in events
    assert "合成测试草稿" in client.get("/api/runs/" + identity + "/export").text


def test_mcp_failure_degrades_and_cancellation_between_stages(client, case, model_config, monkeypatch):
    async def broken(*args):
        raise ConnectionError("offline")

    monkeypatch.setattr("law_backend.worker.mcp_request", broken)
    client.patch("/api/settings", json={"mcp": {"enabled": True, "url": "https://example.com/mcp"}})
    source = add_source(client, case)
    identity = start_run(client, case, source_ids=[source["id"]]).json()["id"]
    claim_job(Run, "running")
    seen = []

    def cancel_after_first(stage, context, schema):
        seen.append(stage)
        assert context["coverage"]["mcp"] == "unavailable"
        with Session.begin() as db:
            db.get(Run, identity).cancel_requested = True
        return Finding(title="cancel", summary="cancel").model_dump(), {}

    with pytest.raises(Cancelled):
        process_run(identity, executor_override=cancel_after_first)
    assert seen == ["intake"]


def test_recovery_of_stale_run(client, case, model_config):
    source = add_source(client, case)
    identity = start_run(client, case, source_ids=[source["id"]]).json()["id"]
    claim_job(Run, "running")
    with Session.begin() as db:
        db.get(Run, identity).heartbeat = now() - timedelta(minutes=6)
    recover_stale()
    assert client.get("/api/runs/" + identity).json()["status"] == "interrupted"


def test_association_does_not_mean_support_or_validity():
    draft = Draft(
        title="test",
        summary="test",
        sections=[
            Finding(
                title="claim",
                summary="",
                claims=[
                    {"text": "相反结论", "citations": ["S:1"], "kind": "fact"},
                    {"text": "法律效力断言", "citations": ["S:1"], "kind": "legal"},
                    {"text": "不存在的引用", "citations": ["S:missing"], "kind": "fact"},
                ],
            )
        ],
    )
    review = Review(
        summary="",
        items=[
            {"claim_index": i, "verdict": v, "reason": "test"}
            for i, v in enumerate(["contradicted", "supported", "supported"])
        ],
    )
    result = verify_draft(draft, review, {"S:1": {"text": "原文"}})
    assert result["claims"][0]["association"] == "linked"
    assert result["claims"][0]["support"] == "contradicted"
    assert result["claims"][1]["validity"] == "needs_review"
    assert result["claims"][2]["support"] == "insufficient"
    assert result["needs_review"] is True


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "1e9999", "abc"])
def test_fee_rejects_invalid_numbers(value):
    with pytest.raises(ValueError):
        lawsuit_fee(value)


def test_fee_calculation():
    assert lawsuit_fee("100000")["fee"] == "2300.00"
