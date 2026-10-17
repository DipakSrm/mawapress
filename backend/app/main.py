from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.limits import BodyLimitMiddleware
from app.core.errors import register_error_handlers
from app.modules.auth.router import router as auth_router
from app.modules.importer.router import router as import_router
from app.modules.jobs.router import router as jobs_router
from app.modules.media.router import router as media_router
from app.modules.posts.router import router as posts_router
from app.modules.public.router import router as public_router
from app.modules.taxonomy.router import router as taxonomy_router
from app.modules.users.router import router as users_router


def create_app() -> FastAPI:
    app = FastAPI(title="MAWAPRESS API", version="0.1.0")
    register_error_handlers(app)
    app.add_middleware(BodyLimitMiddleware)
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(posts_router)
    app.include_router(taxonomy_router)
    app.include_router(public_router)
    app.include_router(media_router)
    app.include_router(jobs_router)
    app.include_router(import_router)

    settings = get_settings()
    if settings.storage == "local":
        # Dev/test only: S3 deployments serve media from the bucket's own origin (MAWA_MEDIA_BASE_URL).
        app.mount("/media", StaticFiles(directory=f"{settings.media_local_dir}/media", check_dir=False), name="media")

    @app.get("/api/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
