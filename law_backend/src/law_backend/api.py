import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from .config import ROOT, settings
from .db import (
    Account,
    Case,
    Event,
    LoginSession,
    Material,
    Page,
    Run,
    Session,
    Source,
    event,
    now,
    serialize,
    uid,
)
from .fees import lawsuit_fee
from .materials import detect_file, file_hash
from .preferences import load_config, public_config, save_config
from .providers import mcp_request, selected_model, test_model
from .security import create_session, hash_password, initialize_security, token_hash, verify_password
from .sources import fetch_official, store_source
from .storage import get, location, put, test_cos

attempts = {}


def authenticate(request: Request):
    digest = token_hash(request.cookies.get("law_session", ""))
    with Session() as db:
        account = db.scalar(
            select(Account).join(LoginSession, LoginSession.account_id == Account.id)
            .where(LoginSession.token_hash == digest, LoginSession.expires_at > now())
        )
        if account is None:
            raise HTTPException(401, "请先登录工作台")
        request.state.account_name = account.username


def check_attempts(request):
    host = request.client.host if request.client else "unknown"
    recent = [t for t in attempts.get(host, []) if time.time() - t < 600]
    if len(recent) >= 10:
        raise HTTPException(429, "尝试过于频繁，请 10 分钟后重试")
    return host, recent


@asynccontextmanager
async def lifespan(app):
    initialize_security()
    with Session() as db:
        db.execute(text("SELECT 1"))
    yield


app = FastAPI(title="律序 · 法律工作台", lifespan=lifespan)


@app.middleware("http")
async def security_headers(request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if request.headers.get("X-Workspace-Request") != "1":
            return Response("Missing request header", status_code=403)
        try:
            content_length = int(request.headers.get("content-length", 0) or 0)
        except ValueError:
            return Response("Invalid content length", status_code=400)
        if content_length > (settings.max_upload_mb + 2) * 1024 * 1024:
            return Response("File too large", status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(max_length=256)


class SetupAccount(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=12, max_length=256)


class ChangeAccount(SetupAccount):
    current_password: str = Field(min_length=1, max_length=256)


@app.get("/api/auth/status")
def auth_status():
    with Session() as db:
        return {"initialized": db.get(Account, 1) is not None}


@app.post("/api/auth/setup", status_code=201)
def setup_account(body: SetupAccount, response: Response):
    try:
        with Session.begin() as db:
            if db.get(Account, 1) is not None:
                raise HTTPException(409, "管理员已创建，请登录")
            db.add(Account(id=1, username=body.username, password_hash=hash_password(body.password)))
            db.flush()
            create_session(db, response)
    except IntegrityError:
        raise HTTPException(409, "管理员已创建，请登录") from None
    return {"ok": True, "username": body.username}


@app.post("/api/login")
def login(body: Login, request: Request, response: Response):
    host, recent = check_attempts(request)
    with Session.begin() as db:
        account = db.scalar(select(Account).where(Account.id == 1).with_for_update())
        valid = account is not None and verify_password(body.password, account.password_hash)
        if not valid or account.username != body.username.strip():
            attempts[host] = recent + [time.time()]
            raise HTTPException(401, "账号或密码不正确")
        attempts.pop(host, None)
        create_session(db, response)
        username = account.username
    return {"ok": True, "username": username}


router = APIRouter(prefix="/api", dependencies=[Depends(authenticate)])


@router.get("/session")
def session(request: Request):
    return {"authenticated": True, "username": request.state.account_name}


@router.put("/account")
def change_account(body: ChangeAccount, request: Request, response: Response):
    host, recent = check_attempts(request)
    with Session.begin() as db:
        account = db.scalar(select(Account).where(Account.id == 1).with_for_update())
        if db.get(LoginSession, token_hash(request.cookies.get("law_session", ""))) is None:
            raise HTTPException(401, "会话已失效，请重新登录")
        if not verify_password(body.current_password, account.password_hash):
            attempts[host] = recent + [time.time()]
            raise HTTPException(400, "当前密码不正确")
        account.username = body.username
        account.password_hash = hash_password(body.password)
        db.execute(delete(LoginSession).where(LoginSession.account_id == account.id))
        attempts.pop(host, None)
    response.delete_cookie("law_session")
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response):
    with Session.begin() as db:
        db.execute(delete(LoginSession).where(
            LoginSession.token_hash == token_hash(request.cookies.get("law_session", ""))
        ))
    response.delete_cookie("law_session")
    return {"ok": True}


def require(db, table, identity):
    row = db.get(table, identity)
    if row is None:
        raise HTTPException(404, "记录不存在")
    return row


def assert_idle(db, case_id):
    db.scalar(select(Case).where(Case.id == case_id).with_for_update())
    busy = db.scalar(select(Run.id).where(Run.case_id == case_id, Run.status.in_(["queued", "running"])))
    if busy:
        raise HTTPException(409, "案件已有分析任务，请等待完成或取消后重试")


class CaseInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    category: Literal["civil", "labor"] = "civil"
    description: str = Field(default="", max_length=12000)


@router.get("/cases")
def list_cases():
    with Session() as db:
        cases = db.scalars(select(Case).order_by(Case.updated_at.desc())).all()
        return [
            {
                **serialize(case),
                "material_count": db.scalar(
                    select(func.count(Material.id)).where(Material.case_id == case.id)
                ),
            }
            for case in cases
        ]


@router.post("/cases", status_code=201)
def create_case(body: CaseInput):
    with Session.begin() as db:
        row = Case(**body.model_dump())
        db.add(row)
        db.flush()
        return serialize(row)


@router.get("/cases/{case_id}")
def case_detail(case_id: str):
    with Session() as db:
        case = require(db, Case, case_id)
        materials = db.scalars(
            select(Material).where(Material.case_id == case_id).order_by(Material.created_at)
        ).all()
        sources = db.scalars(
            select(Source).where(Source.case_id == case_id).order_by(Source.created_at.desc())
        ).all()
        runs = db.scalars(select(Run).where(Run.case_id == case_id).order_by(Run.created_at.desc())).all()
        return {
            **serialize(case),
            "materials": [serialize(m) for m in materials],
            "sources": [{k: v for k, v in serialize(s).items() if k != "content"} for s in sources],
            "runs": [{k: v for k, v in serialize(r).items() if k not in ("outputs", "result")} for r in runs],
        }


@router.put("/cases/{case_id}")
def update_case(case_id: str, body: CaseInput):
    with Session.begin() as db:
        row = require(db, Case, case_id)
        assert_idle(db, case_id)
        for key, value in body.model_dump().items():
            setattr(row, key, value)
        return serialize(row)


@router.post("/cases/{case_id}/materials", status_code=201)
async def upload(case_id: str, file: UploadFile):
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    await file.close()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "单个文件不能超过 20MB")
    name = (file.filename or "material").replace("\\", "/").split("/")[-1][:255]
    try:
        mime = await asyncio.to_thread(detect_file, name, data)
    except Exception:
        raise HTTPException(
            400, "文件无效、加密或超出限制。支持 80 页以内 PDF、图片和 UTF-8 文本。"
        ) from None
    config = load_config()["storage"]
    with Session.begin() as db:
        require(db, Case, case_id)
        assert_idle(db, case_id)
        identity = uid()
        key = f"{case_id}/{identity}/original{Path(name).suffix.lower()}"
        try:
            await asyncio.to_thread(put, key, data, config, mime)
        except Exception:
            raise HTTPException(502, "文件存储失败，请检查存储配置") from None
        row = Material(
            id=identity,
            case_id=case_id,
            name=name,
            mime=mime,
            size=len(data),
            sha256=file_hash(data),
            storage=location(config),
            object_key=key,
        )
        db.add(row)
        db.flush()
        return serialize(row)


@router.get("/materials/{material_id}/pages")
def pages(material_id: str):
    with Session() as db:
        require(db, Material, material_id)
        return [
            serialize(p)
            for p in db.scalars(select(Page).where(Page.material_id == material_id).order_by(Page.number))
        ]


@router.get("/materials/{material_id}/file")
def material_file(material_id: str, page: int | None = None):
    with Session() as db:
        material = require(db, Material, material_id)
        key, mime = material.object_key, material.mime
        if page is not None:
            row = db.scalar(select(Page).where(Page.material_id == material_id, Page.number == page))
            if not row or not row.image_key:
                raise HTTPException(404, "页面图像不存在")
            key, mime = row.image_key, "image/png"
        try:
            data = get(key, material.storage, load_config()["storage"])
        except Exception:
            raise HTTPException(502, "无法读取文件，请检查原存储桶访问权限") from None
        return Response(data, media_type=mime, headers={"Content-Disposition": "inline"})


@router.post("/materials/{material_id}/reparse")
def reparse(material_id: str, vision: bool = False):
    with Session.begin() as db:
        row = require(db, Material, material_id)
        assert_idle(db, row.case_id)
        if row.status in ("queued", "processing"):
            raise HTTPException(409, "素材正在排队或解析")
        if vision:
            try:
                if not selected_model(load_config())["vision"]:
                    raise ValueError()
            except ValueError:
                raise HTTPException(400, "请先配置支持图片的模型并启用图片能力") from None
        row.status, row.error, row.force_vision = "queued", "", vision
        return {"ok": True}


class SourceInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=200000)
    url: str = Field(default="", max_length=2000)
    version: str = Field(default="未标明", max_length=100)
    effective_date: str = Field(default="", max_length=50)


@router.post("/cases/{case_id}/sources", status_code=201)
def add_source(case_id: str, body: SourceInput):
    with Session.begin() as db:
        require(db, Case, case_id)
        return serialize(store_source(db, case_id, body.model_dump()))


class URLInput(BaseModel):
    url: str = Field(max_length=2000)


@router.post("/cases/{case_id}/sources/fetch", status_code=201)
def import_url(case_id: str, body: URLInput):
    with Session() as db:
        require(db, Case, case_id)
    try:
        data = fetch_official(body.url)
    except Exception:
        raise HTTPException(400, "无法读取该官方 HTML 网页，请检查链接或粘贴正文导入") from None
    with Session.begin() as db:
        return serialize(store_source(db, case_id, data))


@router.get("/sources/{source_id}")
def source_detail(source_id: str):
    with Session() as db:
        return serialize(require(db, Source, source_id))


class RunInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    question: str = Field(min_length=2, max_length=12000)
    mode: Literal["analysis", "complaint", "defense"] = "analysis"
    material_ids: list[str] = Field(default_factory=list, max_length=100)
    source_ids: list[str] = Field(default_factory=list, max_length=100)


@router.post("/cases/{case_id}/runs", status_code=202)
def start_run(case_id: str, body: RunInput):
    config = load_config()
    try:
        model = selected_model(config)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    if not body.material_ids and not body.source_ids:
        raise HTTPException(400, "至少选择一份材料或来源")
    with Session.begin() as db:
        require(db, Case, case_id)
        assert_idle(db, case_id)
        material_ids = list(dict.fromkeys(body.material_ids))
        source_ids = list(dict.fromkeys(body.source_ids))
        for identity in material_ids:
            row = require(db, Material, identity)
            if row.case_id != case_id:
                raise HTTPException(400, "不能使用其他案件的材料")
            if row.status not in ("ready", "needs_vision"):
                raise HTTPException(409, "请先完成所有所选材料的解析")
        for identity in source_ids:
            if require(db, Source, identity).case_id != case_id:
                raise HTTPException(400, "不能使用其他案件的来源")
        row = Run(
            case_id=case_id,
            question=body.question,
            mode=body.mode,
            material_ids=material_ids,
            source_ids=source_ids,
            model_info={
                "provider": config["provider"],
                "model": model["model"],
                "base_url": model["base_url"],
            },
        )
        db.add(row)
        db.flush()
        event(db, row, "queued", "任务已排队，等待后台工作进程。")
        return serialize(row)


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    with Session() as db:
        return serialize(require(db, Run, run_id))


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    with Session.begin() as db:
        run = require(db, Run, run_id)
        if run.status in ("queued", "running"):
            run.cancel_requested = True
            if run.status == "queued":
                run.status = "cancelled"
                from .db import now

                run.finished_at = now()
            event(db, run, run.stage, "已请求取消；当前模型调用完成后停止后续步骤。")
        return {"ok": True}


@router.get("/runs/{run_id}/events")
async def events(run_id: str, request: Request, after: int = 0):
    with Session() as db:
        require(db, Run, run_id)
    try:
        after = max(after, int(request.headers.get("last-event-id", "0")))
    except ValueError:
        pass

    async def stream():
        cursor = after
        while not await request.is_disconnected():
            try:
                authenticate(request)
            except HTTPException:
                yield 'event: session-expired\ndata: {}\n\n'
                break
            with Session() as db:
                rows = db.scalars(
                    select(Event).where(Event.run_id == run_id, Event.id > cursor).order_by(Event.id)
                ).all()
                status = db.get(Run, run_id).status
            for row in rows:
                cursor = row.id
                yield f"id: {row.id}\nevent: progress\ndata: {json.dumps(serialize(row), ensure_ascii=False)}\n\n"
            if status not in ("queued", "running"):
                yield f"event: finished\ndata: {json.dumps({'status': status})}\n\n"
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@router.get("/runs/{run_id}/export")
def export_run(run_id: str):
    with Session() as db:
        run = require(db, Run, run_id)
        if not run.result:
            raise HTTPException(409, "尚无可导出的分析结果")
        result = run.result
        draft = result["draft"]
        lines = [
            "# " + draft["title"],
            "",
            "> 分析草稿，含未核验事项。已关联不代表结论正确。",
            "",
            draft["summary"],
            "",
            "来源范围：" + result["coverage"]["note"],
        ]
        for section in draft["sections"]:
            lines.extend(["", "## " + section["title"], "", section["summary"]])
            for claim in section["claims"]:
                lines.append("\n- " + claim["text"] + " [" + ", ".join(claim["citations"]) + "]")
        lines.extend(["", "## 复核", result["review_summary"]])
        for claim in result["claims"]:
            lines.append(
                f"- {claim['index'] + 1}. {claim['support']} / {claim['validity']}：{claim['reason']}"
            )
        lines.extend(
            [
                "",
                "## 下一步",
                *["- " + x for x in draft["next_steps"]],
                "",
                "## 限制",
                *["- " + x for x in draft["limitations"]],
                "",
                "## 来源索引",
            ]
        )
        for ref, evidence in result["evidence"].items():
            lines.append(
                f"- {ref}：{evidence['name']}，页码 {evidence.get('page', '—')}，版本 {evidence.get('version', '—')}；{evidence.get('url', '')}"
            )
        return Response(
            "\n".join(lines),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="analysis-{run_id}.md"'},
        )


@router.get("/settings")
def get_settings():
    return public_config(load_config())


@router.patch("/settings")
def set_settings(body: dict):
    try:
        return save_config(body)
    except Exception:
        raise HTTPException(400, "配置格式不正确，请检查接口地址、模型、存储和 MCP 参数") from None


@router.post("/settings/test/{target}")
async def test_settings(target: Literal["model", "vision", "cos", "mcp"]):
    config = load_config()
    try:
        if target == "mcp":
            return await mcp_request(config["mcp"])
        if target == "cos":
            return await asyncio.to_thread(test_cos, config["storage"])
        return await asyncio.to_thread(test_model, config, target == "vision")
    except Exception:
        raise HTTPException(
            502, "连接测试失败，请核对已保存的地址、密钥、模型或服务权限；密钥不会在错误中显示"
        ) from None


@router.get("/fees")
def fees(amount: str):
    try:
        return lawsuit_fee(amount)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/health")
def health():
    with Session() as db:
        db.execute(text("SELECT 1"))
    return {"ok": True, "database": "mysql", "crewai": "1.15.22"}


app.include_router(router)
dist = ROOT / "frontend" / "dist"
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")


@app.get("/{path:path}")
def frontend(path: str):
    if path.startswith("api/") or not (dist / "index.html").exists():
        raise HTTPException(404, "页面不存在；开发时请启动 Vue 前端")
    return FileResponse(dist / "index.html")
