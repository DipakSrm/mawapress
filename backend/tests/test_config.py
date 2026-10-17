import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("MAWA_COOKIE_SECURE", raising=False)  # conftest sets it false for the http test client


def test_production_rejects_insecure_cookies():
    with pytest.raises(ValidationError):
        Settings(env="production", jwt_secret="x" * 40, cookie_secure=False)


def test_dev_allows_insecure_cookies():
    assert Settings(env="dev", cookie_secure=False).cookie_secure is False


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


def test_startup_warns_outside_dev_without_trust_proxy_or_with_local_storage():
    prod = Settings(_env_file=None, env="production", jwt_secret="x" * 40)
    text = " ".join(prod.startup_warnings())
    assert "MAWA_TRUST_PROXY" in text and "MAWA_STORAGE=local" in text


def test_startup_is_quiet_in_dev_and_when_configured():
    assert Settings(_env_file=None, env="dev").startup_warnings() == []
    ok = Settings(
        _env_file=None, env="production", jwt_secret="x" * 40, trust_proxy=True, storage="s3",
        s3_endpoint="https://r2.test", s3_bucket="b", s3_access_key="k", s3_secret_key="s", media_base_url="https://cdn.test",
    )
    assert ok.startup_warnings() == []


def test_get_settings_logs_the_warnings(monkeypatch, caplog):
    from app.core import config

    monkeypatch.setenv("MAWA_ENV", "production")
    monkeypatch.setenv("MAWA_JWT_SECRET", "y" * 40)
    config.get_settings.cache_clear()
    try:
        with caplog.at_level("WARNING", logger="mawa.config"):
            config.get_settings()
        assert "MAWA_TRUST_PROXY" in caplog.text and "MAWA_STORAGE=local" in caplog.text
    finally:
        monkeypatch.undo()
        config.get_settings.cache_clear()
