import asyncio
import io
import zipfile
from dataclasses import dataclass, field

import mammoth
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.jobs import Enqueuer, enqueue_quietly
from app.core.storage import MAX_UPLOAD_BYTES, Storage
from app.modules.importer.html_to_tiptap import convert
from app.modules.importer.schemas import ImportOut, ImportReport
from app.modules.media import service as media_service
from app.modules.posts import service as posts_service
from app.modules.posts.models import Post
from app.modules.posts.schemas import Locale, PostCreate, PostOut
from app.modules.taxonomy.models import Category
from app.modules.users.models import User

MAX_DOCX_BYTES = 15 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_MEMBERS = 2000
MAX_RATIO = 100
RATIO_FLOOR = 64 * 1024  # a tiny member can legitimately compress >100x; the total cap bounds those
MAX_IMAGES = 50
MAX_MESSAGES = 20
TIME_LIMIT = 30  # seconds, per conversion phase
MAX_TITLE = 300

STYLE_MAP = """
p[style-name='Quote'] => blockquote > p
p[style-name='Intense Quote'] => blockquote > p
u => u
"""


def check_docx(raw: bytes) -> None:
    """Reject non-docx input and zip bombs before any XML is parsed."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            infos = z.infolist()
            if len(infos) > MAX_MEMBERS:
                raise AppError(413, "DOCX_TOO_LARGE", "This document contains too many parts")
            total = 0
            for info in infos:
                total += info.file_size
                big = info.file_size >= RATIO_FLOOR
                if big and (info.compress_size == 0 or info.file_size / info.compress_size > MAX_RATIO):
                    raise AppError(413, "DOCX_TOO_LARGE", "This document expands too much when unpacked")
            if total > MAX_UNCOMPRESSED_BYTES:
                raise AppError(413, "DOCX_TOO_LARGE", "This document expands too much when unpacked")
            if "word/document.xml" not in z.namelist():
                raise AppError(415, "NOT_A_DOCX", "Only .docx documents can be imported")
    except zipfile.BadZipFile:
        raise AppError(415, "NOT_A_DOCX", "Only .docx documents can be imported") from None


@dataclass
class _Extracted:
    html: str
    images: list[bytes] = field(default_factory=list)  # in placeholder order: mawa-img:<index>
    warnings: list[str] = field(default_factory=list)


def _extract(raw: bytes) -> _Extracted:
    """Synchronous: zip checks + mammoth (its own minidom/expat parsing; external entities are not fetched)."""
    check_docx(raw)
    out = _Extracted(html="")

    def on_image(image) -> dict:
        n = len(out.images)
        if n >= MAX_IMAGES:
            out.warnings.append(f"more than {MAX_IMAGES} images; the rest were skipped")
            return {"src": "mawa-skipped"}
        with image.open() as f:
            data = f.read(MAX_UPLOAD_BYTES + 1)
        out.images.append(data)
        return {"src": f"mawa-img:{n}", "alt": image.alt_text or ""}

    try:
        result = mammoth.convert_to_html(
            io.BytesIO(raw), style_map=STYLE_MAP, convert_image=mammoth.images.img_element(on_image)
        )
    except AppError:
        raise
    except Exception:
        raise AppError(422, "DOCX_UNREADABLE", "This document could not be read") from None
    out.html = result.value
    out.warnings.extend(m.message for m in result.messages[:MAX_MESSAGES])
    return out


def _title_from(doc: dict, given: str | None, filename: str | None) -> str:
    if given and given.strip():
        return given.strip()[:MAX_TITLE]
    content = doc["content"]
    for i, node in enumerate(content):
        if node["type"] == "heading" and node["attrs"]["level"] == 1:
            title = "".join(c.get("text", "") for c in node["content"]).strip()
            if title:
                del content[i]
                if not content:
                    content.append({"type": "paragraph"})
                return title[:MAX_TITLE]
            break
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if name.lower().endswith(".docx"):
        name = name[:-5]
    return name.strip()[:MAX_TITLE] or "Untitled import"


async def import_docx(
    session: AsyncSession, storage: Storage, enqueue: Enqueuer, user: User, *,
    raw: bytes, filename: str | None, locale: Locale, category_id: int, title: str | None,
) -> tuple[Post, ImportReport]:
    if len(raw) > MAX_DOCX_BYTES:
        raise AppError(413, "FILE_TOO_LARGE", "Documents can be at most 15 MB")
    if await session.get(Category, category_id) is None:
        raise AppError(422, "CATEGORY_NOT_FOUND", "Category does not exist")
    try:
        extracted = await asyncio.wait_for(asyncio.to_thread(_extract, raw), TIME_LIMIT)
    except TimeoutError:
        raise AppError(422, "IMPORT_TIMEOUT", "This document took too long to convert") from None

    warnings = list(dict.fromkeys(extracted.warnings))
    urls: dict[str, str] = {}
    for n, data in enumerate(extracted.images):
        try:
            media = await media_service.upload(session, storage, user, data)
        except AppError as exc:  # a bad image costs that image, not the import
            warnings.append(f"image {n + 1} was skipped: {exc.message}")
            continue
        urls[f"mawa-img:{n}"] = storage.url(media.key)
        await enqueue_quietly(enqueue, "make_variants", str(media.id))

    try:
        doc, html_warnings = await asyncio.wait_for(asyncio.to_thread(convert, extracted.html, urls), TIME_LIMIT)
    except TimeoutError:
        raise AppError(422, "IMPORT_TIMEOUT", "This document took too long to convert") from None
    except RecursionError:
        raise AppError(422, "DOCX_UNREADABLE", "This document is too deeply nested to import") from None
    warnings.extend(w for w in html_warnings if w not in warnings)

    post = await posts_service.create_post(
        session, user,
        PostCreate(locale=locale, title=_title_from(doc, title, filename), content_json=doc, category_id=category_id),
    )
    return post, ImportReport(images=len(urls), warnings=warnings)


def build_out(post: Post, report: ImportReport) -> ImportOut:
    return ImportOut(post=PostOut.model_validate(post), report=report)
