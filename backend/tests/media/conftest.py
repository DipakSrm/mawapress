import io

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.core.cache import get_redis
from app.core.jobs import get_enqueuer
from app.core.storage import LocalStorage, get_storage
from app.db.session import get_session
from app.main import create_app


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "files", "")


@pytest.fixture
def jobs():
    return []


@pytest_asyncio.fixture
async def mclient(session, fake_redis, storage, jobs):
    app = create_app()

    async def enqueue(name, *args):
        jobs.append((name, args))

    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_enqueuer] = lambda: enqueue
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def image_bytes(fmt="PNG", size=(400, 300), color=(200, 30, 30), **save_kwargs) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt, **save_kwargs)
    return buf.getvalue()


def files(data: bytes, name="photo.png", content_type="image/png") -> dict:
    return {"file": (name, data, content_type)}
