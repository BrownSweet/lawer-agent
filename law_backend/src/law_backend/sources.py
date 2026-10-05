import hashlib
import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from .db import Source


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def store_source(db, case_id, data):
    content = data["content"].strip()
    if not content or len(content) > 200000:
        raise ValueError("来源正文应在 1 至 200000 字符之间")
    title = str(data.get("title", "未命名来源"))[:500]
    provider = str(data.get("provider", "user"))[:100]
    url = str(data.get("url", ""))[:2000]
    version = str(data.get("version", "未标明"))[:100]
    effective = str(data.get("effective_date", ""))[:50]
    document_key = digest(provider + "\0" + title + "\0" + url)
    sha = digest(content)
    version_key = digest(document_key + "\0" + version + "\0" + effective + "\0" + sha)
    existing = db.scalar(select(Source).where(Source.case_id == case_id, Source.version_key == version_key))
    if existing:
        return existing
    row = Source(
        case_id=case_id,
        document_key=document_key,
        version_key=version_key,
        title=title,
        provider=provider,
        url=url,
        version=version,
        effective_date=effective,
        validity="未核验",
        completeness=str(data.get("completeness", "unverified"))[:30],
        content=content,
        sha256=sha,
    )
    db.add(row)
    db.flush()
    return row


def validate_public_official_url(url):
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if p.scheme != "https" or p.port not in (None, 443) or p.username or p.password:
        raise ValueError("仅支持官方 HTTPS 网页")
    if not (host.endswith(".gov.cn") or host.endswith(".npc.gov.cn")):
        raise ValueError("请提供 gov.cn 或 npc.gov.cn 官方网页；其他来源可粘贴正文导入")
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("网页地址不能指向本地或内网")


def fetch_official(url):
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
        for _ in range(4):
            validate_public_official_url(url)
            with client.stream("GET", url, headers={"User-Agent": "LawWorkspace/0.1"}) as response:
                if response.is_redirect:
                    from urllib.parse import urljoin

                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                if "html" not in response.headers.get("content-type", ""):
                    raise ValueError("该链接不是 HTML 页面，PDF 请使用文件上传")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2_000_000:
                        raise ValueError("网页超过 2MB，请改用文件上传")
                soup = BeautifulSoup(bytes(raw), "html.parser")
                title = soup.title.get_text(strip=True) if soup.title else url
                for node in soup(["script", "style", "nav", "footer", "header"]):
                    node.decompose()
                body = soup.select_one("article") or soup.select_one("main") or soup.body or soup
                text = body.get_text("\n", strip=True)
                if not text.strip():
                    raise ValueError("网页未返回可读取正文")
                return {
                    "title": title,
                    "url": url,
                    "content": text,
                    "provider": "official-web",
                    "completeness": "unverified",
                }
    raise ValueError("网页重定向次数过多")
