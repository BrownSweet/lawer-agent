"""Integration tests use an explicitly isolated MySQL database, never workspace data."""

import os
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[2]
env = dotenv_values(root / ".env")
url = make_url(os.environ.get("LAW_TEST_DATABASE_URL") or env["DATABASE_URL"])
if not os.environ.get("LAW_TEST_DATABASE_URL"):
    url = url.set(database="law_workspace_test")
if not url.database.endswith("_test") or url.get_backend_name() != "mysql":
    raise RuntimeError("Tests require a dedicated MySQL database ending in _test")
os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
os.environ["CREWAI_TRACING_ENABLED"] = "false"

from law_backend.config import settings  # noqa: E402 -- environment isolation must precede imports
from law_backend.db import Base, engine  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database(tmp_path, monkeypatch):
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())
    monkeypatch.setattr(settings, "data_dir", tmp_path / "files")
    monkeypatch.setattr(settings, "security_key_path", tmp_path / "security.key")
    monkeypatch.setattr(settings, "legacy_app_secret", "")
    monkeypatch.setattr(settings, "legacy_app_username", "admin")
    monkeypatch.setattr(settings, "legacy_app_password", "")
    from law_backend.api import attempts

    attempts.clear()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from law_backend.api import app

    with TestClient(app, headers={"X-Workspace-Request": "1"}) as test_client:
        assert (
            test_client.post(
                "/api/auth/setup", json={"username": "test-admin", "password": "local-test-password"}
            ).status_code
            == 201
        )
        yield test_client


@pytest.fixture
def case(client):
    response = client.post("/api/cases", json={"title": "测试案件（合成数据）"})
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def model_config(client):
    assert (
        client.patch(
            "/api/settings", json={"providers": {"deepseek": {"api_key": "test-key-no-network"}}}
        ).status_code
        == 200
    )
