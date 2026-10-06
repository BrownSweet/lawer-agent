import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import select

from law_backend.api import app
from law_backend.config import settings
from law_backend.db import Account, LoginSession, Session, now
from law_backend.security import initialize_security, token_hash, verify_password

CREDS = {"username": "test-admin", "password": "local-test-password"}
HEADERS = {"X-Workspace-Request": "1"}


def test_first_setup_once_and_password_hashed():
    with TestClient(app, headers=HEADERS) as client:
        assert client.get('/api/auth/status').json() == {"initialized": False}
        assert client.get('/api/cases').status_code == 401
        assert client.post('/api/auth/setup', json={**CREDS, "password": "short"}).status_code == 422
        response = client.post('/api/auth/setup', json=CREDS)
        assert response.status_code == 201
        assert 'HttpOnly' in response.headers['set-cookie']
        assert client.get('/api/auth/status').json() == {"initialized": True}
        assert client.get('/api/session').json()['username'] == 'test-admin'
        assert client.post('/api/auth/setup', json=CREDS).status_code == 409
        with Session() as db:
            account = db.get(Account, 1)
            assert CREDS['password'] not in account.password_hash
            assert verify_password(CREDS['password'], account.password_hash)
            assert db.scalar(select(LoginSession)).token_hash != client.cookies.get('law_session')


def test_concurrent_setup():
    with TestClient(app, headers=HEADERS) as client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: client.post('/api/auth/setup', json=CREDS).status_code, range(2)))
        assert sorted(results) == [201, 409]
        with Session() as db:
            assert len(db.scalars(select(Account)).all()) == 1


def test_login_requires_both_account_and_password(client):
    client.post('/api/logout')
    assert client.post('/api/login', json={"password": CREDS['password']}).status_code == 422
    for username, password in [('wrong-admin', CREDS['password']), ('test-admin', 'wrong-password')]:
        assert client.post('/api/login', json={"username": username, "password": password}).status_code == 401
        assert client.get('/api/cases').status_code == 401
    assert client.post('/api/login', json=CREDS).status_code == 200
    assert client.get('/api/session').json() == {"authenticated": True, "username": "test-admin"}


def test_logout_revokes_replayed_cookie(client):
    token = client.cookies.get('law_session')
    client.post('/api/logout')
    client.cookies.set('law_session', token)
    assert client.get('/api/session').status_code == 401


def test_expired_session(client):
    with Session.begin() as db:
        db.get(LoginSession, token_hash(client.cookies.get('law_session'))).expires_at = now() - timedelta(seconds=1)
    assert client.get('/api/session').status_code == 401


def test_account_change_revokes_all_sessions(client):
    first = client.cookies.get('law_session')
    client.post('/api/login', json=CREDS)
    second = client.cookies.get('law_session')
    payload = {"username": "new-admin", "password": "updated-test-password", "current_password": "wrong"}
    assert client.put('/api/account', json=payload).status_code == 400
    assert client.get('/api/session').status_code == 200
    payload['current_password'] = CREDS['password']
    assert client.put('/api/account', json=payload).status_code == 200
    for token in (first, second):
        client.cookies.clear()
        client.cookies.set('law_session', token)
        assert client.get('/api/session').status_code == 401
    assert client.post('/api/login', json=CREDS).status_code == 401
    assert client.post('/api/login', json={"username": "new-admin", "password": payload['password']}).status_code == 200


def test_old_signed_session_rejected(client):
    client.cookies.clear()
    legacy = URLSafeTimedSerializer('synthetic-legacy-secret', salt='law-workspace').dumps(
        hashlib.sha256(b'local-test-password').hexdigest()
    )
    client.cookies.set('law_session', legacy)
    assert client.get('/api/session').status_code == 401


def test_account_persists_and_ignores_later_env(client, monkeypatch):
    monkeypatch.setattr(settings, 'legacy_app_username', 'env-user')
    monkeypatch.setattr(settings, 'legacy_app_password', 'env-password-not-used')
    initialize_security()
    with TestClient(app, headers=HEADERS) as restarted:
        assert restarted.get('/api/auth/status').json()['initialized'] is True
        assert restarted.post('/api/login', json=CREDS).status_code == 200
        assert restarted.post('/api/login', json={"username": "env-user", "password": "env-password-not-used"}).status_code == 401


def test_legacy_account_import(monkeypatch):
    monkeypatch.setattr(settings, 'legacy_app_username', 'old-admin')
    monkeypatch.setattr(settings, 'legacy_app_password', 'old-test-password')
    initialize_security()
    monkeypatch.setattr(settings, 'legacy_app_password', '')
    with TestClient(app, headers=HEADERS) as client:
        assert client.get('/api/auth/status').json()['initialized'] is True
        assert client.post('/api/login', json={"username": "old-admin", "password": "old-test-password"}).status_code == 200


def test_login_rate_limit(client):
    client.post('/api/logout')
    for _ in range(10):
        assert client.post('/api/login', json={**CREDS, "password": "incorrect"}).status_code == 401
    assert client.post('/api/login', json=CREDS).status_code == 429


def test_open_sse_stops_after_session_revocation(client, case):
    import asyncio
    from types import SimpleNamespace

    from law_backend.api import events
    from law_backend.db import Run

    with Session.begin() as db:
        run = Run(case_id=case['id'], question='Synthetic SSE session check', status='queued')
        db.add(run)
        db.flush()
        run_id = run.id
    token = client.cookies.get('law_session')

    async def disconnected():
        return False

    async def check():
        request = SimpleNamespace(cookies={'law_session': token}, headers={},
                                  state=SimpleNamespace(), is_disconnected=disconnected)
        response = await events(run_id, request)
        assert 'heartbeat' in await anext(response.body_iterator)
        with Session.begin() as db:
            db.delete(db.get(LoginSession, token_hash(token)))
        assert 'session-expired' in await anext(response.body_iterator)
        await response.body_iterator.aclose()

    asyncio.run(check())
