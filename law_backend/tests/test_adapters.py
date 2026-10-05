import asyncio
import copy
import io
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest

from law_backend import providers, storage
from law_backend.agents import execute_role
from law_backend.config import DEFAULT_CONFIG
from law_backend.contracts import Finding


@pytest.mark.parametrize("provider,json_mode", [("deepseek", True), ("tokenhub", False)])
def test_real_agent_compatible_http_contract(monkeypatch, provider, json_mode):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["provider"] = provider
    config["providers"][provider].update(api_key="test-secret", model="fixture-model", json_mode=json_mode)
    seen = []

    def respond(request):
        body = json.loads(request.content)
        seen.append(body)
        assert request.url == config["providers"][provider]["base_url"] + "/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-secret"
        assert body.get("response_format") == ({"type": "json_object"} if json_mode else None)
        assert "JSON Schema" in body["messages"][-1]["content"]
        assert "legal-scenario-router" in json.dumps(body["messages"], ensure_ascii=False)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"title": "HTTP test", "summary": "Synthetic", "claims": []}
                            )
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    original = httpx.Client
    monkeypatch.setattr(
        providers.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(respond), **kw)
    )
    result, usage = execute_role("intake", {"evidence": {}}, Finding, config)
    assert result["title"] == "HTTP test"
    assert usage["total_tokens"] == 15 and len(seen) == 1


def test_cos_preserves_original_bucket_and_closes_stream(monkeypatch):
    seen = []
    raw = io.BytesIO(b"private-material")

    class FakeCOS:
        def put_object(self, **kwargs):
            seen.append(kwargs)

        def get_object(self, **kwargs):
            seen.append(kwargs)
            return {"Body": SimpleNamespace(get_raw_stream=lambda: raw)}

    def factory(config):
        assert config["bucket"] == "original-bucket"
        return FakeCOS()

    monkeypatch.setattr(storage, "client", factory)
    config = {"mode": "cos", "bucket": "original-bucket", "region": "ap-guangzhou", "secret_key": "private"}
    storage.put("case/file", b"private-material", config)
    assert (
        storage.get("case/file", storage.location(config), {**config, "bucket": "new-bucket"})
        == b"private-material"
    )
    assert raw.closed and seen[0]["Body"] == b"private-material"
    assert "secret_key" not in storage.location(config)


@pytest.mark.parametrize("transport", ["sse", "streamable-http"])
def test_mcp_discovery_and_structured_read_only_search(monkeypatch, transport):
    seen = []

    @asynccontextmanager
    async def connection(url, **kwargs):
        seen.append((url, kwargs))
        yield ("read", "write", None)

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def initialize(self):
            pass

        async def list_tools(self):
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name="search",
                        description="read only",
                        inputSchema={"type": "object"},
                        annotations=SimpleNamespace(destructiveHint=False, readOnlyHint=True),
                    )
                ]
            )

        async def call_tool(self, name, args):
            assert name == "search" and args == {"text": "合同争议", "limit": 3}
            return SimpleNamespace(
                isError=False, structuredContent={"sources": [{"title": "source", "content": "text"}]}
            )

    monkeypatch.setattr(providers, "sse_client", connection)
    monkeypatch.setattr(providers, "streamablehttp_client", connection)
    monkeypatch.setattr(providers, "ClientSession", FakeSession)
    config = {
        "transport": transport,
        "url": "https://example.com/mcp",
        "token": "fixture-token",
        "tool": "search",
        "query_field": "text",
        "arguments": {"limit": 3},
    }
    assert asyncio.run(providers.mcp_request(config))["tools"][0]["name"] == "search"
    assert asyncio.run(providers.mcp_request(config, "合同争议"))["sources"][0]["content"] == "text"
    assert seen[0][1]["headers"]["Authorization"] == "Bearer fixture-token"
