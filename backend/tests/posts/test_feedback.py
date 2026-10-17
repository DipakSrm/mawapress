from tests.factories import auth_header, auth_if_match, create_post_via_api, make_category, make_user, publish_via_api
from app.modules.users.models import Role


async def _in_review(client, reporter, cat):
    draft = await create_post_via_api(client, reporter, cat)
    r = await client.post(f"/api/posts/{draft['id']}/submit", headers=auth_header(reporter))
    assert r.status_code == 200
    return r.json()


async def _send_back(client, editor, post, note="Add a second source"):
    r = await client.post(
        f"/api/posts/{post['id']}/send-back", json={"note": note}, headers=auth_if_match(editor, post["updated_at"])
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_send_back_stores_feedback_and_exposes_it(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor, name="Sita Editor")
    cat = await make_category(session)
    back = await _send_back(client, editor, await _in_review(client, reporter, cat), "  Add a second source ")
    assert back["status"] == "draft"
    assert back["feedback_note"] == "Add a second source"
    assert back["feedback_by"] == str(editor.id)
    assert back["feedback_by_name"] == "Sita Editor"
    assert back["feedback_at"]
    assert back["created_at"]

    got = (await client.get(f"/api/posts/{back['id']}", headers=auth_header(reporter))).json()
    assert got["feedback_note"] == "Add a second source"

    row = (await client.get("/api/posts", headers=auth_header(reporter))).json()["items"][0]
    assert row["feedback_note"] == "Add a second source"
    assert row["feedback_by_name"] == "Sita Editor"
    assert row["feedback_at"]
    assert row["created_at"]


async def test_send_back_without_note_clears_older_feedback(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    back = await _send_back(client, editor, await _in_review(client, reporter, cat), "first")
    again = (await client.post(f"/api/posts/{back['id']}/submit", headers=auth_header(reporter))).json()
    second = await _send_back(client, editor, again, "")
    assert second["feedback_note"] is None
    assert second["feedback_by"] == str(editor.id)


async def test_successful_submit_clears_feedback_but_publish_and_unschedule_keep_it(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    back = await _send_back(client, editor, await _in_review(client, reporter, cat))

    # Unschedule back to draft keeps the note.
    from datetime import datetime, timedelta, timezone

    when = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    sched = await client.post(
        f"/api/posts/{back['id']}/schedule", json={"scheduled_at": when}, headers=auth_if_match(editor, back["updated_at"])
    )
    assert sched.status_code == 200
    assert sched.json()["feedback_note"] == "Add a second source"
    unsched = await client.post(
        f"/api/posts/{back['id']}/unschedule", headers=auth_if_match(editor, sched.json()["updated_at"])
    )
    assert unsched.json()["status"] == "draft"
    assert unsched.json()["feedback_note"] == "Add a second source"

    # Editing the draft keeps it too.
    edit = await client.patch(
        f"/api/posts/{back['id']}", json={"locale": "ne", "title": "नयाँ"},
        headers=auth_if_match(reporter, unsched.json()["updated_at"]),
    )
    assert edit.json()["feedback_note"] == "Add a second source"

    # Publishing keeps it.
    live = await publish_via_api(client, editor, edit.json())
    assert live["feedback_note"] == "Add a second source"

    # A successful submit clears it (second post, reporter resubmits).
    other = await _send_back(client, editor, await _in_review(client, reporter, cat), "fix the dateline")
    resubmitted = await client.post(f"/api/posts/{other['id']}/submit", headers=auth_header(reporter))
    assert resubmitted.status_code == 200
    body = resubmitted.json()
    assert body["feedback_note"] is None
    assert body["feedback_by"] is None
    assert body["feedback_by_name"] is None
    assert body["feedback_at"] is None


async def test_failed_submit_keeps_feedback(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    back = await _send_back(client, editor, await _in_review(client, reporter, cat))
    stranger = await make_user(session)
    assert (await client.post(f"/api/posts/{back['id']}/submit", headers=auth_header(stranger))).status_code == 403
    got = (await client.get(f"/api/posts/{back['id']}", headers=auth_header(reporter))).json()
    assert got["feedback_note"] == "Add a second source"
