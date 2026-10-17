from fastapi import FastAPI

from app.core.errors import register_error_handlers
from app.modules.auth.router import router as auth_router
from app.modules.posts.router import router as posts_router
from app.modules.public.router import router as public_router
from app.modules.taxonomy.router import router as taxonomy_router
from app.modules.users.router import router as users_router


def create_app() -> FastAPI:
    app = FastAPI(title="MAWAPRESS API", version="0.1.0")
    register_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(posts_router)
    app.include_router(taxonomy_router)
    app.include_router(public_router)

    @app.get("/api/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
