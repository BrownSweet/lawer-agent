import base64
import copy
import hashlib
import json
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import BaseModel, Field, HttpUrl

from .config import DEFAULT_CONFIG, settings
from .db import Config, Session

fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.app_secret.encode()).digest()))


class ProviderConfig(BaseModel):
    base_url: HttpUrl
    model: str = Field(max_length=200)
    api_key: str = Field(default="", max_length=4096)
    vision: bool = False
    json_mode: bool = False


class StorageConfig(BaseModel):
    mode: Literal["local", "cos"] = "local"
    region: str = Field(default="", max_length=100, pattern=r"^[a-z0-9-]*$")
    bucket: str = Field(default="", max_length=100, pattern=r"^[a-z0-9-]*$")
    secret_id: str = Field(default="", max_length=4096)
    secret_key: str = Field(default="", max_length=4096)


class MCPConfig(BaseModel):
    enabled: bool = False
    url: str = Field(default="", max_length=2000)
    token: str = Field(default="", max_length=4096)
    transport: Literal["streamable-http", "sse"] = "streamable-http"
    tool: str = Field(default="", max_length=200)
    query_field: str = Field(default="text", max_length=100)
    arguments: dict = Field(default_factory=dict)


class Preferences(BaseModel):
    provider: Literal["deepseek", "tokenhub"]
    providers: dict[str, ProviderConfig]
    storage: StorageConfig
    mcp: MCPConfig


def load_config():
    with Session() as db:
        row = db.get(Config, 1)
        return json.loads(fernet.decrypt(row.encrypted.encode())) if row else copy.deepcopy(DEFAULT_CONFIG)


def public_config(config):
    data = copy.deepcopy(config)
    for provider in data["providers"].values():
        provider["has_key"] = bool(provider.pop("api_key", ""))
    for key in ("secret_id", "secret_key"):
        data["storage"]["has_" + key] = bool(data["storage"].pop(key, ""))
    data["mcp"]["has_token"] = bool(data["mcp"].pop("token", ""))
    return data


def save_config(incoming):
    """PATCH semantics: omitted credentials are preserved; explicit empty strings clear them."""
    data = load_config()
    for key in ("provider",):
        if key in incoming:
            data[key] = incoming[key]
    for group in ("storage", "mcp"):
        if group in incoming:
            data[group].update(incoming[group])
    for key, value in incoming.get("providers", {}).items():
        if key not in data["providers"]:
            raise ValueError("未知模型供应商")
        data["providers"][key].update(value)
    data = Preferences.model_validate(data).model_dump(mode="json")
    with Session.begin() as db:
        row = db.get(Config, 1)
        encrypted = fernet.encrypt(json.dumps(data, ensure_ascii=False).encode()).decode()
        if row:
            row.encrypted = encrypted
        else:
            db.add(Config(id=1, encrypted=encrypted))
    return public_config(data)
