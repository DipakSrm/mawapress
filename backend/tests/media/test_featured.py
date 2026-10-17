from app.modules.media.variants import make_variants
from app.modules.public.service import FEED_GEN_KEY, post_cache_key
from app.modules.users.models import Role
from tests.factories import auth_header, auth_if_match, create_post_via_api, make_category, make_user, publish_via_api
from tests.media.conftest import files, image_bytes
from tests.media.test_variants import make_ctx


async def upload(mclient, user, size=(2000, 1000)):
    r = await mclient.post("/api/media", files=files(image_bytes("PNG", size)), headers=auth_header(user))
    assert r.status_code == 201, r.text
    return r.json()


async def patch_post(mclient, editor, post_id, updated_at, body):
    return await mclient.patch(f"/api/posts/{post_id}", json={"locale": "ne", **body}, headers=auth_if_match(editor, updated_at))


async def test_featured_media_in_post_out_and_validated(mclient, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    media = await upload(mclient, editor)
    post = await create_post_via_api(mclient, editor, cat, featured_media_id=media["id"])
    assert post["featured_media_id"] == media["id"]
    assert post["featured_media"]["url"] == media["url"]
    bad = await mclient.post(
        "/api/posts",
        json={"locale": "ne", "title": "x", "content_json": {"type": "doc", "content": []}, "category_id": cat.id,
              "featured_media_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_header(editor),
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "MEDIA_NOT_FOUND"
    plain = await create_post_via_api(mclient, editor, cat, title="plain")
    assert plain["featured_media"] is None


async def test_featured_media_set_clear_and_unchanged_on_update(mclient, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    media = await upload(mclient, editor)
    post = await create_post_via_api(mclient, editor, cat)
    r = await patch_post(mclient, editor, post["id"], post["updated_at"], {"featured_media_id": media["id"]})
    assert r.status_code == 200 and r.json()["featured_media_id"] == media["id"]
    r = await patch_post(mclient, editor, post["id"], r.json()["updated_at"], {"title": "नयाँ शीर्षक"})
    assert r.json()["featured_media_id"] == media["id"]
    r = await patch_post(mclient, editor, post["id"], r.json()["updated_at"], {"featured_media_id": None})
    assert r.json()["featured_media_id"] is None and r.json()["featured_media"] is None
    r = await patch_post(
        mclient, editor, post["id"], r.json()["updated_at"],
        {"featured_media_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "MEDIA_NOT_FOUND"


async def test_featured_image_on_public_post_cards_and_seo(mclient, session, storage):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    media = await upload(mclient, editor)
    await mclient.patch(f"/api/media/{media['id']}", json={"alt_ne": "बाढीको फोटो"}, headers=auth_header(editor))
    post = await create_post_via_api(mclient, editor, cat, featured_media_id=media["id"])
    await make_variants(make_ctx(session, storage), media["id"])
    await publish_via_api(mclient, editor, post)

    page = (await mclient.get("/api/public/posts/ne/badhi-samachar")).json()
    img = page["image"]
    assert img["url"] == media["url"] and (img["width"], img["height"]) == (2000, 1000)
    assert img["alt"] == "बाढीको फोटो"
    assert set(img["variants"]) == {"w320", "w640", "w1024", "w1600", "og"}
    assert page["seo"]["og_image"] == "https://mawapress.com" + img["variants"]["og"]

    home = (await mclient.get("/api/public/home", params={"locale": "ne"})).json()
    cards = [c for b in home["categories"] for c in b["posts"]]
    assert cards[0]["image"] == img
    search = (await mclient.get("/api/public/search", params={"q": "बाढी", "locale": "ne"})).json()
    assert search["items"][0]["image"]["url"] == media["url"]


async def test_image_alt_falls_back_to_caption_then_title(mclient, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    media = await upload(mclient, editor, size=(300, 200))
    post = await create_post_via_api(mclient, editor, cat, featured_media_id=media["id"])
    await publish_via_api(mclient, editor, post)
    assert (await mclient.get("/api/public/posts/ne/badhi-samachar")).json()["image"]["alt"] == "बाढी समाचार"
    await mclient.patch(f"/api/media/{media['id']}", json={"caption": "A caption"}, headers=auth_header(editor))
    # Re-saving the featured image on the live post invalidates the cached page.
    post = (await mclient.get(f"/api/posts/{post['id']}", headers=auth_header(editor))).json()
    r = await patch_post(mclient, editor, post["id"], post["updated_at"], {"featured_media_id": None})
    r = await patch_post(mclient, editor, post["id"], r.json()["updated_at"], {"featured_media_id": media["id"]})
    assert r.status_code == 200
    assert (await mclient.get("/api/public/posts/ne/badhi-samachar")).json()["image"]["alt"] == "A caption"


async def test_seo_og_image_uses_original_without_variants(mclient, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    media = await upload(mclient, editor, size=(300, 200))
    post = await create_post_via_api(mclient, editor, cat, featured_media_id=media["id"])
    await publish_via_api(mclient, editor, post)
    page = (await mclient.get("/api/public/posts/ne/badhi-samachar")).json()
    assert page["seo"]["og_image"] == "https://mawapress.com" + media["url"]


async def test_post_without_image_has_null_image(mclient, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    await publish_via_api(mclient, editor, await create_post_via_api(mclient, editor, cat))
    assert (await mclient.get("/api/public/posts/ne/badhi-samachar")).json()["image"] is None


async def test_changing_featured_image_on_live_post_invalidates_caches(mclient, session, fake_redis):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    media = await upload(mclient, editor, size=(300, 200))
    post = await publish_via_api(mclient, editor, await create_post_via_api(mclient, editor, cat))
    await mclient.get("/api/public/posts/ne/badhi-samachar")
    assert await fake_redis.get(post_cache_key("ne", "badhi-samachar"))
    gen = await fake_redis.get(FEED_GEN_KEY)
    r = await patch_post(mclient, editor, post["id"], post["updated_at"], {"featured_media_id": media["id"]})
    assert r.status_code == 200
    assert await fake_redis.get(post_cache_key("ne", "badhi-samachar")) is None
    assert await fake_redis.get(FEED_GEN_KEY) != gen
    assert (await mclient.get("/api/public/posts/ne/badhi-samachar")).json()["image"]["url"] == media["url"]


async def test_changing_featured_image_on_draft_is_not_public(mclient, session, fake_redis):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    media = await upload(mclient, editor, size=(300, 200))
    post = await create_post_via_api(mclient, editor, cat)
    gen = await fake_redis.get(FEED_GEN_KEY)
    r = await patch_post(mclient, editor, post["id"], post["updated_at"], {"featured_media_id": media["id"]})
    assert r.status_code == 200
    assert await fake_redis.get(FEED_GEN_KEY) == gen
