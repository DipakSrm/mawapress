"""arq entry point: `python -m uv run arq app.worker.settings.WorkerSettings`.

Later tasks register their functions / cron jobs in the two lists below.
"""

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.storage import get_storage
from app.db.session import SessionLocal, engine
from app.modules.media.variants import make_variants
from app.worker.maintenance import purge_refresh_tokens
from app.worker.scheduler import SCHEDULER_TIMEOUT_SECONDS, publish_due_posts
from app.worker.outbox import CRON_TIMEOUT_SECONDS, new_http_client, process_outbox


async def startup(ctx: dict) -> None:
    ctx["session_factory"] = SessionLocal
    ctx["settings"] = get_settings()
    ctx["http"] = new_http_client()
    ctx["storage"] = get_storage()


async def shutdown(ctx: dict) -> None:
    await ctx["http"].aclose()
    await engine.dispose()


class WorkerSettings:
    functions: list = [make_variants]
    cron_jobs = [
        # Ticks may overlap (unique only dedupes the same tick); the outbox lease makes that safe.
        cron(process_outbox, second=set(range(0, 60, 10)), run_at_startup=True, timeout=CRON_TIMEOUT_SECONDS),
        cron(publish_due_posts, second={0, 30}, timeout=SCHEDULER_TIMEOUT_SECONDS),
        cron(purge_refresh_tokens, hour=3, minute=17, unique=True),
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    on_startup = startup
    on_shutdown = shutdown
