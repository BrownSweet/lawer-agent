import hashlib

from itsdangerous import URLSafeTimedSerializer

from law_backend.config import settings


def test_login_requires_both_account_and_password(client):
    client.post("/api/logout")
    assert client.post("/api/login", json={"password": "local-test-password"}).status_code == 422
    for username, password in [("wrong-admin", "local-test-password"), ("test-admin", "wrong-password")]:
        response = client.post("/api/login", json={"username": username, "password": password})
        assert response.status_code == 401
        assert response.json()["detail"] == "账号或密码不正确"
        assert client.get("/api/cases").status_code == 401
    response = client.post("/api/login", json={"username": "test-admin", "password": "local-test-password"})
    assert response.status_code == 200
    assert client.get("/api/session").json() == {"authenticated": True, "username": "test-admin"}
    assert "HttpOnly" in response.headers["set-cookie"]
    client.post("/api/logout")
    assert client.get("/api/session").status_code == 401


def test_old_password_only_session_is_rejected(client):
    client.cookies.clear()
    legacy = URLSafeTimedSerializer(settings.app_secret, salt="law-workspace").dumps(
        hashlib.sha256(settings.app_password.encode()).hexdigest()
    )
    client.cookies.set("law_session", legacy)
    assert client.get("/api/session").status_code == 401


def test_account_changes_invalidate_existing_session(client, monkeypatch):
    from law_backend import api

    old_identity = api.session_identity
    monkeypatch.setattr(api, "session_identity", api.account_identity("renamed-admin", settings.app_password))
    assert client.get("/api/session").status_code == 401
    monkeypatch.setattr(
        api, "session_identity", api.account_identity(settings.app_username, "changed-password")
    )
    assert client.get("/api/session").status_code == 401
    monkeypatch.setattr(api, "session_identity", old_identity)
    assert client.get("/api/session").status_code == 200
