import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    database_url: str
    app_secret: str
    app_username: str = Field(default="admin", min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    app_password: str
    cookie_secure: bool = False
    data_dir: Path = ROOT / ".local" / "files"
    max_upload_mb: int = 20
    max_pages: int = 80
    max_context_chars: int = 90000


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
