"""Local encryption key and database-backed administrator sessions."""
import base64
import fcntl
import hashlib
import hmac
import os
import secrets
import tempfile
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import Account, Config, LoginSession, Session, now

SESSION_SECONDS = 43200


def configuration_cipher():
    """Create once under a process lock; never replace a missing key for existing ciphertext."""
    path = settings.security_key_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            return Fernet(path.read_bytes().strip())
        with Session() as db:
            config = db.get(Config, 1)
            encrypted = config.encrypted if config else None
        if encrypted:
            if not settings.legacy_app_secret:
                raise RuntimeError("已有加密配置但缺少密钥文件；请恢复 security.key，或提供旧 APP_SECRET 完成一次迁移。")
            key = base64.urlsafe_b64encode(hashlib.sha256(settings.legacy_app_secret.encode()).digest())
            try:
                Fernet(key).decrypt(encrypted.encode())
            except InvalidToken:
                raise RuntimeError("旧 APP_SECRET 无法解密已有配置；未修改原数据。") from None
        else:
            key = Fernet.generate_key()
        # 同目录原子替换避免 API/Worker 并发启动或进程中断留下半个密钥。
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".security-")
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(key)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return Fernet(key)


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, maxmem=64 * 1024 * 1024)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password, encoded):
    try:
        algorithm, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=1, maxmem=64 * 1024 * 1024,
        )
        return hmac.compare_digest(digest.hex(), expected)
    except ValueError:
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db, response):
    token = secrets.token_urlsafe(32)
    db.execute(delete(LoginSession).where(LoginSession.expires_at <= now()))
    db.add(LoginSession(token_hash=token_hash(token), account_id=1,
                        expires_at=now() + timedelta(seconds=SESSION_SECONDS)))
    response.set_cookie("law_session", token, httponly=True, secure=settings.cookie_secure,
                        samesite="strict", max_age=SESSION_SECONDS)


def initialize_security():
    cipher = configuration_cipher()
    with Session() as db:
        config = db.get(Config, 1)
        if config:
            # 启动时发现错误密钥，不能把无法解密的配置误当作空配置。
            cipher.decrypt(config.encrypted.encode())
    if not settings.legacy_app_password:
        return
    try:
        with Session.begin() as db:
            if db.get(Account, 1) is None:
                db.add(Account(id=1, username=settings.legacy_app_username,
                               password_hash=hash_password(settings.legacy_app_password)))
    except IntegrityError:
        # 另一个 API 进程已完成同一管理员的迁移。
        pass
