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
