import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.posts.models import Post, PostStatus, PostTranslation
from app.modules.taxonomy.models import Category
from app.modules.users.models import Role, User

DOC = {"type": "doc", "content": []}


async def _author_and_category(session):
    user = User(email="a@mawapress.com", password_hash="x", name="A", role=Role.reporter)
    cat = Category(slug="morang", name_ne="मोरङ", name_en="Morang")
    session.add_all([user, cat])
    await session.flush()
    return user, cat


def _post(user, cat, locale, slug):
    post = Post(author_id=user.id, category_id=cat.id)
    post.translations.append(
        PostTranslation(locale=locale, title="t", slug=slug, content_json=DOC, content_html="")
    )
    return post


async def test_post_with_translation_roundtrip(session):
    user, cat = await _author_and_category(session)
    post = _post(user, cat, "ne", "shirshak")
    session.add(post)
    await session.flush()
    session.expunge_all()

    loaded = await session.get(Post, post.id)
    assert loaded.status == PostStatus.draft
    assert loaded.updated_at.tzinfo is not None
    assert [t.slug for t in loaded.translations] == ["shirshak"]


async def test_slug_unique_per_locale(session):
    user, cat = await _author_and_category(session)
    session.add_all([_post(user, cat, "ne", "same"), _post(user, cat, "ne", "same")])
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_same_slug_allowed_in_other_locale(session):
    user, cat = await _author_and_category(session)
    session.add_all([_post(user, cat, "ne", "same"), _post(user, cat, "en", "same")])
    await session.flush()
