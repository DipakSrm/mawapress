from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def test_validation_error_uses_envelope(client):
    r = await client.post("/api/auth/login", json={"email": "not-an-email"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["message"] == "Request validation failed"
    assert isinstance(err["details"]["errors"], list) and err["details"]["errors"]


async def test_unknown_route_uses_envelope(client):
    r = await client.get("/api/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
    assert r.json()["error"]["details"] == {}


async def test_method_not_allowed_uses_envelope(client):
    r = await client.post("/api/healthz")
    assert r.status_code == 405
    assert r.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert "allow" in {k.lower() for k in r.headers}


async def test_unhandled_exception_uses_envelope():
    app = create_app()

    @app.get("/crash")
    async def crash():
        raise RuntimeError("secret internals")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/crash")
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "INTERNAL_ERROR", "message": "Internal server error", "details": {}}}
