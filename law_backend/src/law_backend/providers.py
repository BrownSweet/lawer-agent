import asyncio
import json
from datetime import timedelta
from urllib.parse import urlparse

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client


def selected_model(config):
    model = config["providers"][config["provider"]]
    if not model["api_key"] or not model["model"]:
        raise ValueError("请先在设置中配置模型名称和 API Key")
    validate_endpoint(model["base_url"])
    return model


def validate_endpoint(url):
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.fragment or p.query:
        raise ValueError("服务地址须为不包含账号或查询参数的 HTTPS URL")


def complete(model, messages, max_tokens=4000, json_mode=False):
    validate_endpoint(model["base_url"])
    body = {"model": model["model"], "messages": messages, "max_tokens": max_tokens}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    with httpx.Client(timeout=httpx.Timeout(120, connect=15), follow_redirects=False) as client:
        response = client.post(
            model["base_url"].rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer " + model["api_key"]},
            json=body,
        )
        response.raise_for_status()
        payload = response.json()
        if payload["choices"][0].get("finish_reason") == "length":
            raise ValueError("模型输出达到长度上限，请缩小本次分析范围")
        content = payload["choices"][0]["message"].get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("模型未返回正文")
        return content, payload.get("usage", {})


def chat(config, messages, max_tokens=4000):
    return complete(selected_model(config), messages, max_tokens)[0]


def test_model(config, vision=False):
    messages = [{"role": "user", "content": "仅回复 OK"}]
    if vision:
        import base64
        import io

        from PIL import Image

        image = Image.new("RGB", (32, 32), "red")
        out = io.BytesIO()
        image.save(out, format="PNG")
        messages[0]["content"] = [
            {"type": "text", "text": "简短描述这张图片的颜色"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()},
            },
        ]
    reply = chat(config, messages, max_tokens=256)
    return {"ok": True, "message": reply[:500], "capability": "image" if vision else "text"}


async def mcp_request(config, query=None):
    validate_endpoint(config["url"])
    headers = {"Authorization": "Bearer " + config["token"]} if config.get("token") else {}
    if config["transport"] == "sse":
        transport = sse_client(config["url"], headers=headers, timeout=15, sse_read_timeout=30)
    else:
        transport = streamablehttp_client(config["url"], headers=headers, timeout=15, sse_read_timeout=30)
    async with asyncio.timeout(45):
        async with transport as streams:
            async with ClientSession(
                streams[0], streams[1], read_timeout_seconds=timedelta(seconds=30)
            ) as session:
                await session.initialize()
                available = await session.list_tools()
                if query is None:
                    return {
                        "ok": True,
                        "tools": [
                            {"name": t.name, "description": t.description, "schema": t.inputSchema}
                            for t in available.tools
                        ],
                    }
                tool = next((t for t in available.tools if t.name == config["tool"]), None)
                if not tool:
                    raise ValueError("已配置的检索工具未在服务中找到")
                if tool.annotations and (
                    tool.annotations.destructiveHint is True or tool.annotations.readOnlyHint is False
                ):
                    raise ValueError("仅支持只读检索工具，请选择不修改外部数据的工具")
                arguments = {**config.get("arguments", {}), config["query_field"]: query}
                result = await session.call_tool(tool.name, arguments)
                if result.isError:
                    raise ValueError("检索服务返回错误")
                if result.structuredContent:
                    if len(json.dumps(result.structuredContent, ensure_ascii=False)) > 300000:
                        raise ValueError("检索返回超过本次处理上限")
                    return result.structuredContent
                text = "\n".join(c.text for c in result.content if c.type == "text")
                if len(text) > 300000:
                    raise ValueError("检索返回超过本次处理上限")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"unstructured": text}
