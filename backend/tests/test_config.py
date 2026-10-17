import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_rejects_default_secret():
    with pytest.raises(ValidationError):
        Settings(env="production")


def test_production_rejects_short_secret():
    with pytest.raises(ValidationError):
        Settings(env="production", jwt_secret="x" * 31)


def test_production_accepts_long_secret():
    assert Settings(env="production", jwt_secret="x" * 40).env == "production"


def test_dev_allows_default_secret():
    assert Settings().env == "dev"


def test_session_settings_defaults(monkeypatch):
    for name in ("MAWA_COOKIE_SECURE", "MAWA_TRUST_PROXY", "MAWA_REFRESH_DAYS"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert (s.refresh_days, s.cookie_secure, s.trust_proxy) == (14, True, False)
