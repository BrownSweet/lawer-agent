import os

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from law_backend.config import Settings


@pytest.fixture
def mysql_environment(monkeypatch):
    for key in list(os.environ):
        if key.lower() == "database_url" or key.lower().startswith("mysql_"):
            monkeypatch.delenv(key)
    values = {
        "mysql_ip": "mysql-server",
        "mysql_port": "3307",
        "mysql_root": "law_user",
        "mysql_password": "synthetic:@/#%? password",
        "mysql_database": "law_workspace_test",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


def test_jiami_environment_names_and_password_roundtrip(mysql_environment):
    config = Settings(_env_file=None)
    url = make_url(config.database_url)
    assert url.drivername == "mysql+pymysql"
    assert (url.host, url.port, url.username, url.database) == (
        "mysql-server", 3307, "law_user", "law_workspace_test",
    )
    assert url.password == mysql_environment["mysql_password"]
    assert url.query == {"charset": "utf8mb4"}


def test_mysql_default_port_and_normalized_text(mysql_environment, monkeypatch):
    monkeypatch.delenv("mysql_port")
    monkeypatch.setenv("mysql_ip", " mysql-server ")
    assert make_url(Settings(_env_file=None).database_url).port == 3306
    assert make_url(Settings(_env_file=None).database_url).host == "mysql-server"


@pytest.mark.parametrize("key", ["mysql_ip", "mysql_root", "mysql_password", "mysql_database"])
def test_missing_mysql_field_fails_without_echoing_password(mysql_environment, monkeypatch, key):
    monkeypatch.delenv(key)
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)
    assert key in str(error.value)
    assert mysql_environment["mysql_password"] not in str(error.value)


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_invalid_mysql_port_fails(mysql_environment, monkeypatch, port):
    monkeypatch.setenv("mysql_port", port)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_existing_database_url_has_priority(mysql_environment, monkeypatch):
    legacy = "mysql+pymysql://old:synthetic@legacy:3318/legacy_test?charset=utf8mb4"
    monkeypatch.setenv("DATABASE_URL", legacy)
    assert Settings(_env_file=None).database_url == legacy
