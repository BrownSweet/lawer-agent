import os
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", hide_input_in_errors=True)
    database_url: str = Field(default="", repr=False)
    mysql_ip: str | None = None
    mysql_port: int = Field(default=3306, ge=1, le=65535)
    mysql_root: str | None = None
    mysql_password: str | None = Field(default=None, repr=False)
    mysql_database: str | None = None
    # 仅用于旧部署的一次性迁移；新部署无需传入，迁移后不再作为认证来源。
    legacy_app_secret: str = Field(default="", validation_alias="APP_SECRET", repr=False)
    legacy_app_username: str = Field(default="admin", validation_alias="APP_USERNAME")
    legacy_app_password: str = Field(default="", validation_alias="APP_PASSWORD", repr=False)
    security_key_path: Path = ROOT / ".local" / "security.key"
    cookie_secure: bool = False
    data_dir: Path = ROOT / ".local" / "files"
    max_upload_mb: int = 20
    max_pages: int = 80
    max_context_chars: int = 90000

    @field_validator("mysql_ip", "mysql_root", "mysql_database")
    @classmethod
    def normalize_mysql_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def resolve_database_url(self):
        # 保留本地开发和已有部署的 DATABASE_URL；容器也可使用 Jiami 的分项参数。
        if self.database_url.strip():
            return self
        missing = [
            name for name in ("mysql_ip", "mysql_root", "mysql_password", "mysql_database")
            if not getattr(self, name)
        ]
        if missing:
            raise ValueError(f"缺少 MySQL 配置：{', '.join(missing)}")
        self.database_url = URL.create(
            "mysql+pymysql",
            username=self.mysql_root,
            password=self.mysql_password,
            host=self.mysql_ip,
            port=self.mysql_port,
            database=self.mysql_database,
            query={"charset": "utf8mb4"},
        ).render_as_string(hide_password=False)
        return self


settings = Settings()
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TELEMETRY_ENABLED", "false")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")

DEFAULT_CONFIG = {
    "provider": "deepseek",
    "providers": {
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-flash",
            "api_key": "",
            "vision": True,
            "json_mode": True,
        },
        "tokenhub": {
            "base_url": "https://tokenhub.tencentmaas.com/v1",
            "model": "",
            "api_key": "",
            "vision": False,
            "json_mode": False,
        },
    },
    "storage": {"mode": "local", "region": "", "bucket": "", "secret_id": "", "secret_key": ""},
    "mcp": {
        "enabled": False,
        "url": "",
        "token": "",
        "transport": "streamable-http",
        "tool": "",
        "query_field": "text",
        "arguments": {},
    },
}
