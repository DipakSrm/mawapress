import uuid

from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_redis
from app.db.session import get_session
from app.main import create_app
from app.modules.auth.security import create_access_token, hash_password
from app.modules.taxonomy.models import Category, Tag
from app.modules.users.models import Role, User


async def make_user(
    session: AsyncSession,
    *,
    role: Role = Role.reporter,
    email: str | None = None,
    password: str = "secret-pass-1",
    name: str = "Test User",
    is_active: bool = True,
) -> User:
    user = User(
        email=(email or f"{uuid.uuid4().hex[:10]}@mawapress.com").lower(),
        password_hash=hash_password(password),
        name=name,
        role=role,
        is_active=is_active,
    )
    session.add(user)
    await session.flush()
    return user


async def make_category(
    session: AsyncSession,
    slug: str = "morang",
    name_ne: str = "मोरङ",
    name_en: str = "Morang",
    *,
    parent_id: int | None = None,
    sort: int = 0,
) -> Category:
    cat = Category(slug=slug, name_ne=name_ne, name_en=name_en, parent_id=parent_id, sort=sort)
    session.add(cat)
    await session.flush()
    return cat


async def make_tag(session: AsyncSession, slug: str = "flood", name_ne: str = "बाढी", name_en: str = "Flood") -> Tag:
    tag = Tag(slug=slug, name_ne=name_ne, name_en=name_en)
    session.add(tag)
    await session.flush()
    return tag


def auth_header(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role.value, user.token_version)}"}


def auth_if_match(user: User, updated_at: str) -> dict[str, str]:
    return {**auth_header(user), "If-Match": updated_at}


def doc(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


async def create_post_via_api(
    client: AsyncClient,
    user: User,
    category: Category,
    *,
    title: str = "बाढी समाचार",
    locale: str = "ne",
    body: str = "पानी परिरहेको छ",
    **extra,
) -> dict:
    r = await client.post(
        "/api/posts",
        json={"locale": locale, "title": title, "content_json": doc(body), "category_id": category.id, **extra},
        headers=auth_header(user),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def publish_via_api(client: AsyncClient, editor: User, post: dict) -> dict:
    r = await client.post(f"/api/posts/{post['id']}/publish", headers=auth_if_match(editor, post["updated_at"]))
    assert r.status_code == 200, r.text
    return r.json()


class DownRedis:
    """Every Redis call fails the way a dropped connection does."""

    async def get(self, *args, **kwargs):
        raise RedisConnectionError("redis down")

    set = delete = incr = get


async def down_client(session: AsyncSession) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_redis] = lambda: DownRedis()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
