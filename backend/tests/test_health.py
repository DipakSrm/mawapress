from httpx import ASGITransport, AsyncClient

from app.core.errors import AppError
from app.main import create_app


async def test_healthz(client):
    r = await client.get("/api/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_app_error_uses_envelope():
    app = create_app()

    @app.get("/boom")
    async def boom():
        raise AppError(418, "TEAPOT", "short and stout", {"x": 1})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/boom")
    assert r.status_code == 418
    assert r.json() == {"error": {"code": "TEAPOT", "message": "short and stout", "details": {"x": 1}}}
