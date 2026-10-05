from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import settings


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def uid():
    return str(uuid4())


engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=1800)
Session = sessionmaker(engine, expire_on_commit=False)
LongText = Text().with_variant(LONGTEXT(), "mysql")


class Base(DeclarativeBase):
    pass


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40), default="civil")
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Material(Base):
    __tablename__ = "materials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage: Mapped[dict] = mapped_column(JSON)
    object_key: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    force_vision: Mapped[bool] = mapped_column(Boolean, default=False)
    heartbeat: Mapped[datetime] = mapped_column(DateTime, default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Page(Base):
    __tablename__ = "material_pages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    material_id: Mapped[str] = mapped_column(ForeignKey("materials.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(LongText, default="")
    method: Mapped[str] = mapped_column(String(40), default="text")
    warning: Mapped[str] = mapped_column(Text, default="")
    image_key: Mapped[str] = mapped_column(String(500), default="")


class Source(Base):
    __tablename__ = "source_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    document_key: Mapped[str] = mapped_column(String(64), index=True)
    version_key: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(500))
    provider: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[str] = mapped_column(String(100), default="未标明")
    effective_date: Mapped[str] = mapped_column(String(50), default="")
    validity: Mapped[str] = mapped_column(String(50), default="未核验")
    completeness: Mapped[str] = mapped_column(String(30), default="unverified")
    content: Mapped[str] = mapped_column(LongText)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Run(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(30), default="analysis")
    material_ids: Mapped[list] = mapped_column(JSON, default=list)
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    model_info: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(30), default="queued")
    outputs: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    heartbeat: Mapped[datetime] = mapped_column(DateTime, default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Event(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Config(Base):
    __tablename__ = "workspace_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    encrypted: Mapped[str] = mapped_column(LongText)


def event(db, run, stage, message):
    run.stage = stage
    run.heartbeat = now()
    db.add(Event(run_id=run.id, stage=stage, message=message))


def serialize(row):
    return {
        c.name: (
            getattr(row, c.name).isoformat() + "Z"
            if isinstance(getattr(row, c.name), datetime)
            else getattr(row, c.name)
        )
        for c in row.__table__.columns
    }
