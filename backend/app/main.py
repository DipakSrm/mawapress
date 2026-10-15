from fastapi import FastAPI

from app.core.errors import register_error_handlers
from app.modules.auth.router import router as auth_router


def create_app() -> FastAPI:
    app = FastAPI(title="MAWAPRESS API", version="0.1.0")
    register_error_handlers(app)
    app.include_router(auth_router)

    @app.get("/api/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
