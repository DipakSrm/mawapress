"""arq entry point: `python -m uv run arq app.worker.settings.WorkerSettings`.

Later tasks register their functions / cron jobs in the two lists below.
"""

from arq import cron
from arq.connections import RedisSettings

from app.core.cache import get_redis
from app.core.config import get_settings
from app.core.storage import get_storage
from app.db.session import SessionLocal, engine
from app.modules.media.variants import make_variants
from app.worker.maintenance import purge_refresh_tokens
from app.worker.views import FLUSH_TIMEOUT_SECONDS, flush_views
from app.worker.scheduler import SCHEDULER_TIMEOUT_SECONDS, publish_due_posts
from app.worker.outbox import CRON_TIMEOUT_SECONDS, new_http_client, process_outbox


async def startup(ctx: dict) -> None:
    ctx["session_factory"] = SessionLocal
    ctx["settings"] = get_settings()
    ctx["http"] = new_http_client()
    ctx["storage"] = get_storage()
    ctx["cache_redis"] = get_redis()  # decoded client for cache and stat keys (arq's own ctx["redis"] is not)


async def shutdown(ctx: dict) -> None:
    await ctx["http"].aclose()
    await ctx["cache_redis"].aclose()
    await engine.dispose()


class WorkerSettings:
    functions: list = [make_variants]
    cron_jobs = [
        # Ticks may overlap (unique only dedupes the same tick); the outbox lease makes that safe.
        cron(process_outbox, second=set(range(0, 60, 10)), run_at_startup=True, timeout=CRON_TIMEOUT_SECONDS),
        cron(publish_due_posts, second={0, 30}, timeout=SCHEDULER_TIMEOUT_SECONDS),
        cron(flush_views, second=0, timeout=FLUSH_TIMEOUT_SECONDS),  # drain is atomic, so overlap is harmless
        cron(purge_refresh_tokens, hour=3, minute=17, unique=True),
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    on_startup = startup
    on_shutdown = shutdown
