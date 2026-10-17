from datetime import timedelta

from app.db.base import utcnow
from app.db.outbox import OutboxEvent
from app.modules.users.models import Role
from tests.factories import auth_header, make_user


async def _event(session, **cols) -> OutboxEvent:
    ev = OutboxEvent(topic="post.published", payload={}, **cols)
    session.add(ev)
    await session.flush()
    return ev


async def test_list_dead_and_pending(client, session):
    admin = await make_user(session, role=Role.admin)
    dead = await _event(session, attempts=5, last_error="boom", dead_at=utcnow())
    pending = await _event(session, attempts=1)
    done = await _event(session, processed_at=utcnow())
    dead_rows = (await client.get("/api/admin/jobs?state=dead", headers=auth_header(admin))).json()
    pending_rows = (await client.get("/api/admin/jobs?state=pending", headers=auth_header(admin))).json()
    dead_ids = {r["id"] for r in dead_rows}
    pending_ids = {r["id"] for r in pending_rows}
    assert dead.id in dead_ids and pending.id not in dead_ids and done.id not in dead_ids
    assert pending.id in pending_ids and dead.id not in pending_ids and done.id not in pending_ids
    row = next(r for r in dead_rows if r["id"] == dead.id)
    assert set(row) == {"id", "topic", "attempts", "last_error", "created_at", "dead_at"}
    assert row["attempts"] == 5 and row["last_error"] == "boom"


async def test_list_rejects_bad_state(client, session):
    admin = await make_user(session, role=Role.admin)
    assert (await client.get("/api/admin/jobs?state=nope", headers=auth_header(admin))).status_code == 422


async def test_retry_resets_dead_job(client, session):
    admin = await make_user(session, role=Role.admin)
    ev = await _event(
        session, attempts=5, last_error="boom", dead_at=utcnow(), next_attempt_at=utcnow() + timedelta(hours=1)
    )
    r = await client.post(f"/api/admin/jobs/{ev.id}/retry", headers=auth_header(admin))
    assert r.status_code == 200
    await session.refresh(ev)
    assert ev.dead_at is None and ev.next_attempt_at is None and ev.attempts == 0


async def test_retry_unknown_is_404_and_processed_is_409(client, session):
    admin = await make_user(session, role=Role.admin)
    assert (await client.post("/api/admin/jobs/999999999/retry", headers=auth_header(admin))).status_code == 404
    done = await _event(session, processed_at=utcnow())
    assert (await client.post(f"/api/admin/jobs/{done.id}/retry", headers=auth_header(admin))).status_code == 409


async def test_non_admin_forbidden_and_anonymous_unauthorized(client, session):
    editor = await make_user(session, role=Role.editor)
    ev = await _event(session, dead_at=utcnow())
    assert (await client.get("/api/admin/jobs?state=dead", headers=auth_header(editor))).status_code == 403
    assert (await client.post(f"/api/admin/jobs/{ev.id}/retry", headers=auth_header(editor))).status_code == 403
    assert (await client.get("/api/admin/jobs?state=dead")).status_code == 401
