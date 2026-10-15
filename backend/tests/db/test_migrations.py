import os
import subprocess
import sys
from pathlib import Path

from testcontainers.community.postgres import PostgresContainer

BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_alembic_upgrade_head_on_empty_database():
    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as pg:
        env = {**os.environ, "MAWA_DATABASE_URL": pg.get_connection_url()}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
        )
    assert result.returncode == 0, result.stderr
