import asyncio
import functools
import threading
import time
from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import select

from .config import settings
from .db import Case, Material, Page, Run, Session, Source, event, now
from .preferences import load_config
from .providers import mcp_request, selected_model
from .sources import store_source

TERMINAL = {"completed", "needs_review", "failed", "cancelled", "interrupted"}


class Cancelled(Exception):
    pass


def check_cancel(run_id):
    with Session() as db:
        run = db.get(Run, run_id)
        if run.cancel_requested or run.status == "cancelled":
            raise Cancelled()


@contextmanager
def heartbeat(table, identity):
    stop = threading.Event()

    def beat():
        while not stop.wait(15):
            with Session.begin() as db:
                row = db.get(table, identity)
                row.heartbeat = now()

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)


def build_context(run_id, config):
    coverage = {"mcp": "disabled", "note": "仅分析本次上传材料及导入来源；没有运行全网检索。"}
    with Session() as db:
        run = db.get(Run, run_id)
        case = db.get(Case, run.case_id)
        case_id, question = case.id, run.question
        source_ids = list(run.source_ids)
    if config["mcp"]["enabled"]:
        try:
            result = asyncio.run(mcp_request(config["mcp"], question))
            items = result if isinstance(result, list) else result.get("sources", result.get("results", []))
            if not isinstance(items, list):
                items = []
            imported = []
            with Session.begin() as db:
                for item in items[:10]:
                    if (
                        isinstance(item, dict)
                        and isinstance(item.get("content"), str)
                        and item["content"].strip()
                    ):
                        row = store_source(
                            db, case_id, {**item, "provider": "mcp", "completeness": "unverified"}
                        )
                        imported.append(row.id)
            source_ids = list(dict.fromkeys(source_ids + imported))
            coverage["mcp"] = "success" if imported else "no_citable_text"
            coverage["note"] = (
                "已调用配置的检索服务；返回正文仍需核验完整性、版本与适用性。"
                if imported
                else "检索服务已响应，但未返回标准 sources/results[].content 正文；没有计为已核验依据。"
            )
        except Exception:
            coverage["mcp"] = "unavailable"
            coverage["note"] = "检索服务不可用；本次继续分析上传材料和已导入来源，不代表没有相关法规或案例。"
    check_cancel(run_id)
    evidence = {}
    unreadable = []
    with Session() as db:
        run = db.get(Run, run_id)
        case = db.get(Case, case_id)
        materials = db.scalars(
            select(Material).where(Material.case_id == case_id, Material.id.in_(run.material_ids))
        ).all()
        for material in materials:
            for page in db.scalars(select(Page).where(Page.material_id == material.id).order_by(Page.number)):
                if page.text.strip():
                    evidence["P:" + page.id] = {
                        "kind": "material",
                        "material_id": material.id,
                        "name": material.name,
                        "page": page.number,
                        "text": page.text,
                        "method": page.method,
                        "warning": page.warning,
                        "sha256": material.sha256,
                    }
                if page.method == "pending_vision" or not page.text.strip():
                    unreadable.append(f"{material.name} 第 {page.number} 页未完成识别")
        for source in db.scalars(select(Source).where(Source.case_id == case_id, Source.id.in_(source_ids))):
            evidence["S:" + source.id] = {
                "kind": "source",
                "name": source.title,
                "text": source.content,
                "url": source.url,
                "version": source.version,
                "validity": source.validity,
                "completeness": source.completeness,
                "sha256": source.sha256,
            }
        if not evidence:
            raise ValueError("没有可读取材料；请先完成文件解析或导入来源")
        if sum(len(e["text"]) for e in evidence.values()) > settings.max_context_chars:
            raise ValueError("材料超过单次 90000 字符上限，请选择更少的素材或按争点拆分案件")
        coverage["unreadable_pages"] = unreadable
        return {
            "case": {"title": case.title, "category": case.category, "description": case.description},
            "question": question,
            "mode": run.mode,
            "evidence": evidence,
            "coverage": coverage,
        }


def process_run(run_id, executor_override=None):
    from .agents import ROLES, execute_role
    from .main import LegalFlow

    config = load_config()
    if executor_override is None:
        model = selected_model(config)
        with Session() as db:
            expected = db.get(Run, run_id).model_info
            if expected.get("provider") != config["provider"] or any(
                expected.get(k) != model.get(k) for k in ("model", "base_url")
            ):
                raise ValueError("排队期间模型配置已改变，请重新发起分析")
    context = build_context(run_id, config)

    def checkpoint(stage, payload, usage):
        with Session.begin() as db:
            run = db.get(Run, run_id)
            if payload is not None:
                run.outputs = {**run.outputs, stage: {"data": payload, "usage": usage}}
            event(db, run, stage, ROLES[stage]["role"] + ("已完成" if payload is not None else "开始处理"))

    executor = executor_override or functools.partial(execute_role, config=config)
    flow = LegalFlow(
        executor=executor, checkpoint=checkpoint, check_cancel=lambda: check_cancel(run_id), context=context
    )
    flow.kickoff()
    result = flow.state.result
    if not result:
        raise ValueError("工作流未产生有效结果")
    with Session.begin() as db:
        run = db.get(Run, run_id)
        if run.cancel_requested:
            raise Cancelled()
        run.result = result
        # All first-version outputs remain drafts; no automatic court filing or legal certification.
        run.status = (
            "needs_review"
            if result["needs_review"] or context["coverage"]["unreadable_pages"]
            else "completed"
        )
        run.finished_at = now()
        event(db, run, "done", "分析草稿已生成；引用关联与结论复核分别展示。")


def recover_stale():
    cutoff = now() - timedelta(minutes=5)
    with Session.begin() as db:
        for run in db.scalars(select(Run).where(Run.status == "running", Run.heartbeat < cutoff)):
            run.status, run.error, run.finished_at = "interrupted", "后台任务中断，可重新发起分析。", now()
            event(db, run, "interrupted", run.error)
        for material in db.scalars(
            select(Material).where(Material.status == "processing", Material.heartbeat < cutoff)
        ):
            material.status, material.error = "failed", "解析任务中断，请重新解析。"


def claim_job(table, status):
    with Session.begin() as db:
        row = db.scalar(
            select(table)
            .where(table.status == "queued")
            .order_by(table.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not row:
            return None
        if table is Run and row.cancel_requested:
            row.status = "cancelled"
            return None
        row.status, row.heartbeat = status, now()
        return row.id


def work_once():
    from .materials import process_material

    material_id = claim_job(Material, "processing")
    if material_id:
        try:
            with heartbeat(Material, material_id):
                process_material(material_id)
        except Exception as exc:
            with Session.begin() as db:
                row = db.get(Material, material_id)
                row.status = "failed"
                row.error = (
                    str(exc)[:300]
                    if isinstance(exc, ValueError)
                    else "文件解析或存储失败，请检查文件和存储配置。"
                )
        return True
    run_id = claim_job(Run, "running")
    if not run_id:
        return False
    try:
        with heartbeat(Run, run_id):
            process_run(run_id)
    except Exception as exc:
        with Session.begin() as db:
            run = db.get(Run, run_id)
            run.status = "cancelled" if isinstance(exc, Cancelled) else "failed"
            run.error = (
                "任务已取消。"
                if isinstance(exc, Cancelled)
                else (
                    str(exc)[:300]
                    if isinstance(exc, ValueError)
                    else "分析失败，请检查模型服务、额度和网络后重新发起。"
                )
            )
            run.finished_at = now()
            event(db, run, run.status, run.error)
    return True


def main():
    print("Law workspace worker started. Polling MySQL jobs; no cloud credentials are printed.")
    recover_stale()
    last_recovery = time.monotonic()
    while True:
        try:
            if time.monotonic() - last_recovery >= 60:
                recover_stale()
                last_recovery = time.monotonic()
            if not work_once():
                time.sleep(1)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f"Worker retrying after {type(exc).__name__}")
            time.sleep(3)


if __name__ == "__main__":
    main()
