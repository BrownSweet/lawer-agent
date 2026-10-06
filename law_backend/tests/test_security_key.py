import base64
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import Fernet

from law_backend.config import DEFAULT_CONFIG, settings
from law_backend.db import Config, Session
from law_backend.preferences import load_config, save_config
from law_backend.security import configuration_cipher, initialize_security


def test_key_generated_once_and_reused():
    with ThreadPoolExecutor(max_workers=4) as pool:
        ciphers = list(pool.map(lambda _: configuration_cipher(), range(4)))
    ciphertext = ciphers[0].encrypt(b'synthetic-key-check')
    assert all(cipher.decrypt(ciphertext) == b'synthetic-key-check' for cipher in ciphers)
    assert settings.security_key_path.stat().st_mode & 0o777 == 0o600
    saved = settings.security_key_path.read_bytes()
    save_config({"providers": {"deepseek": {"api_key": "synthetic-private-key"}}})
    initialize_security()
    assert settings.security_key_path.read_bytes() == saved
    assert load_config()['providers']['deepseek']['api_key'] == 'synthetic-private-key'


def seed_legacy():
    secret = 'synthetic-legacy-encryption-secret'
    cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))
    with Session.begin() as db:
        db.add(Config(id=1, encrypted=cipher.encrypt(json.dumps(DEFAULT_CONFIG).encode()).decode()))
    return secret


def test_legacy_ciphertext_migration(monkeypatch):
    monkeypatch.setattr(settings, 'legacy_app_secret', seed_legacy())
    initialize_security()
    monkeypatch.setattr(settings, 'legacy_app_secret', '')
    initialize_security()
    assert load_config() == DEFAULT_CONFIG


@pytest.mark.parametrize('secret', ['', 'incorrect-legacy-key'])
def test_missing_wrong_legacy_key_preserves_data(monkeypatch, secret):
    seed_legacy()
    monkeypatch.setattr(settings, 'legacy_app_secret', secret)
    with Session() as db:
        original = db.get(Config, 1).encrypted
    with pytest.raises(RuntimeError):
        initialize_security()
    assert not settings.security_key_path.exists()
    with Session() as db:
        assert db.get(Config, 1).encrypted == original


def test_lost_key_never_silently_replaced():
    save_config({"providers": {"deepseek": {"api_key": "synthetic-secret"}}})
    settings.security_key_path.unlink()
    with pytest.raises(RuntimeError):
        load_config()
    assert not settings.security_key_path.exists()
