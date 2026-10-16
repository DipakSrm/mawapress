import os
import subprocess
import sys
from pathlib import Path

from testcontainers.community.postgres import PostgresContainer

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _alembic(env, *args):
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120,
    )


def test_alembic_upgrade_head_on_empty_database():
    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as pg:
        env = {**os.environ, "MAWA_DATABASE_URL": pg.get_connection_url()}
        result = _alembic(env, "upgrade", "head")
    assert result.returncode == 0, result.stderr


def test_models_match_migrations():
    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as pg:
        env = {**os.environ, "MAWA_DATABASE_URL": pg.get_connection_url()}
        upgrade = _alembic(env, "upgrade", "head")
        check = _alembic(env, "check")
    assert upgrade.returncode == 0, upgrade.stderr
    assert check.returncode == 0, check.stdout + check.stderr


def test_alembic_downgrade_then_upgrade_round_trip():
    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as pg:
        env = {**os.environ, "MAWA_DATABASE_URL": pg.get_connection_url()}
        results = [
            _alembic(env, "upgrade", "head"),
            _alembic(env, "downgrade", "base"),
            _alembic(env, "upgrade", "head"),
        ]
    for result in results:
        assert result.returncode == 0, result.stderr
