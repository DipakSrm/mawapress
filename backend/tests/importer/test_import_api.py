import io
import os
import zipfile

from PIL import Image

from sqlalchemy import select

from app.modules.media.models import Media
from app.modules.taxonomy.models import Category
from app.modules.posts.render import render_html
from tests.factories import auth_header, make_category, make_user
from tests.importer.conftest import build_docx, docx_files, image_bytes, zip_with


async def do_import(mclient, session, data, *, title=None, user=None, name="report.docx"):
    cat = await session.scalar(select(Category)) or await make_category(session)
    user = user or await make_user(session)
    form = {"locale": "en", "category_id": str(cat.id)}
    if title:
        form["title"] = title
    r = await mclient.post("/api/import/docx", data=form, files=docx_files(data, name), headers=auth_header(user))
    return r, user


def noisy_bmp() -> bytes:
    buf = io.BytesIO()
    Image.frombytes("RGB", (40, 40), os.urandom(40 * 40 * 3)).save(buf, "BMP")  # a format the media service refuses
    return buf.getvalue()


def walk(node):
    yield node
    for c in node.get("content", []):
        yield from walk(c)


async def test_import_builds_draft_with_expected_nodes_and_marks(mclient, session, jobs):
    r, user = await do_import(mclient, session, build_docx(image=image_bytes(), bad_link=True))
    assert r.status_code == 201, r.text
    body = r.json()
    post = body["post"]
    assert post["status"] == "draft" and post["author_id"] == str(user.id)
    tr = post["translations"][0]
    assert tr["title"] == "Flood Report"  # the H1
    content = tr["content_json"]["content"]
    assert content[0]["type"] == "heading" and content[0]["attrs"]["level"] == 2  # H1 removed from the body
    nodes = list(walk(tr["content_json"]))
    marks = {m["type"] for n in nodes for m in n.get("marks", [])}
    assert marks == {"bold", "italic", "underline", "strike", "link"}
    links = [m["attrs"]["href"] for n in nodes for m in n.get("marks", []) if m["type"] == "link"]
    assert links == ["https://example.com/a"]  # javascript: link dropped
    types = {n["type"] for n in nodes}
    assert {"bulletList", "orderedList", "listItem", "blockquote", "image"} <= types
    texts = " ".join(n["text"] for n in nodes if n["type"] == "text")
    assert "r0c0 | r0c1" in texts  # table kept as text
    warnings = body["report"]["warnings"]
    assert any("table" in w for w in warnings) and any("link" in w for w in warnings)
    assert body["report"]["images"] == 1


async def test_embedded_image_is_uploaded_media_with_variant_job(mclient, session, storage, jobs):
    r, _ = await do_import(mclient, session, build_docx(image=image_bytes("PNG", (50, 40))))
    assert r.status_code == 201, r.text
    media = (await session.scalars(select(Media))).all()
    assert len(media) == 1
    imgs = [n for n in walk(r.json()["post"]["translations"][0]["content_json"]) if n["type"] == "image"]
    assert len(imgs) == 1 and imgs[0]["attrs"]["src"] == storage.url(media[0].key)
    assert jobs == [("make_variants", (str(media[0].id),))]
    assert len(await storage.get(media[0].key)) > 0


async def test_explicit_title_wins_and_h1_stays_in_body(mclient, session):
    r, _ = await do_import(mclient, session, build_docx(), title="Given Title")
    tr = r.json()["post"]["translations"][0]
    assert tr["title"] == "Given Title"
    assert tr["content_json"]["content"][0] == {
        "type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "Flood Report"}]}


async def test_title_falls_back_to_file_name(mclient, session):
    from docx import Document

    d = Document()
    d.add_paragraph("just text")
    buf = io.BytesIO()
    d.save(buf)
    r, _ = await do_import(mclient, session, buf.getvalue(), name="My Notes.v2.docx")
    assert r.json()["post"]["translations"][0]["title"] == "My Notes.v2"


async def test_round_trip_html_is_renderer_stable(mclient, session):
    r, _ = await do_import(mclient, session, build_docx(image=image_bytes()))
    tr = r.json()["post"]["translations"][0]
    assert tr["content_html"] == render_html(tr["content_json"])
    assert "<strong>bold</strong>" in tr["content_html"] and "<figure>" in tr["content_html"]


async def test_bad_embedded_image_is_a_warning_not_a_failure(mclient, session, jobs):
    r, _ = await do_import(mclient, session, build_docx(image=noisy_bmp()))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["report"]["images"] == 0
    assert any("image" in w for w in body["report"]["warnings"])
    assert jobs == []
    assert not [n for n in walk(body["post"]["translations"][0]["content_json"]) if n["type"] == "image"]


async def test_not_a_docx_is_415(mclient, session):
    for data in (b"plain text", zip_with({"hello.txt": b"x"})):
        r, _ = await do_import(mclient, session, data)
        assert r.status_code == 415, r.text
        assert r.json()["error"]["code"] == "NOT_A_DOCX"


async def test_oversize_file_is_413(mclient, session):
    r, _ = await do_import(mclient, session, b"x" * (15 * 1024 * 1024 + 1))
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "FILE_TOO_LARGE"


async def test_requires_login(mclient, session):
    cat = await make_category(session)
    r = await mclient.post("/api/import/docx", data={"locale": "en", "category_id": str(cat.id)},
                           files=docx_files(build_docx()))
    assert r.status_code == 401


async def test_unknown_category_is_422(mclient, session):
    user = await make_user(session)
    r = await mclient.post("/api/import/docx", data={"locale": "en", "category_id": "999999"},
                           files=docx_files(build_docx()), headers=auth_header(user))
    assert r.status_code == 422


async def test_zip_bomb_guards(mclient, session):
    doc_xml = b"<w:document/>"
    many = zip_with({"word/document.xml": doc_xml, **{f"f{i}.txt": b"a" for i in range(2001)}})
    ratio = zip_with({"word/document.xml": doc_xml, "big.bin": b"\0" * (5 * 1024 * 1024)})
    for data in (many, ratio):
        r, _ = await do_import(mclient, session, data)
        assert r.status_code == 413, r.text
        assert r.json()["error"]["code"] == "DOCX_TOO_LARGE"


def docx_with_document_xml(xml: bytes, rels: bytes | None = None) -> bytes:
    good = zipfile.ZipFile(io.BytesIO(build_docx()))
    members = {n: good.read(n) for n in good.namelist()}
    members["word/document.xml"] = xml
    if rels is not None:
        members["word/_rels/document.xml.rels"] = rels
    return zip_with(members)


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


async def test_xxe_expands_to_nothing(mclient, session, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRETVALUE")
    xml = (
        f'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "{secret.as_uri()}">]>'
        f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>before&x;after</w:t></w:r></w:p></w:body></w:document>'
    ).encode()
    r, _ = await do_import(mclient, session, docx_with_document_xml(xml))
    assert "TOPSECRETVALUE" not in r.text
    assert r.status_code in (201, 422), r.text
    if r.status_code == 201:
        texts = [n.get("text", "") for n in walk(r.json()["post"]["translations"][0]["content_json"])]
        assert "".join(texts) in ("beforeafter", "")


async def test_billion_laughs_is_neutralised(mclient, session):
    ents = '<!ENTITY a0 "lollollollollollollollollollol">' + "".join(
        f'<!ENTITY a{i} "{"&a%d;" % (i - 1) * 10}">' for i in range(1, 10))
    xml = (f'<?xml version="1.0"?><!DOCTYPE d [{ents}]><w:document xmlns:w="{W}"><w:body><w:p><w:r>'
           "<w:t>&a9;</w:t></w:r></w:p></w:body></w:document>").encode()
    r, _ = await do_import(mclient, session, docx_with_document_xml(xml))
    assert r.status_code in (201, 422), r.text
    assert len(r.text) < 100_000  # nothing close to the 3 GB the entity would expand to


async def test_oversize_xml_part_is_413(mclient, session):
    # hex of random bytes: ~26 MB of XML that deflates only ~2x, so neither the 15 MB upload cap nor the ratio guard fires
    xml = b"<w:document/><!--" + os.urandom(13 * 1024 * 1024 + 1024).hex().encode() + b"-->"
    r, _ = await do_import(mclient, session, zip_with({"word/document.xml": xml}))
    assert r.status_code == 413 and r.json()["error"]["code"] == "DOCX_TOO_LARGE"


async def test_external_linked_image_is_not_fetched(mclient, session, tmp_path, jobs):
    secret = tmp_path / "secret.png"
    secret.write_bytes(image_bytes())
    xml = (
        f'<w:document xmlns:w="{W}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body><w:p><w:r><w:drawing>'
        '<wp:inline><wp:docPr id="1" name="x" descr="d"/><a:graphic><a:graphicData><pic:pic><pic:blipFill>'
        '<a:blip r:link="rId77"/></pic:blipFill></pic:pic></a:graphicData></a:graphic></wp:inline>'
        "</w:drawing></w:r></w:p></w:body></w:document>"
    ).encode()
    rels = (
        '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId77" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        f'Target="{secret.as_uri()}" TargetMode="External"/></Relationships>'
    ).encode()
    r, _ = await do_import(mclient, session, docx_with_document_xml(xml, rels))
    assert r.status_code == 201, r.text
    assert r.json()["report"]["images"] == 0 and jobs == []
    assert (await session.scalars(select(Media))).all() == []
    assert any("image" in w.lower() for w in r.json()["report"]["warnings"])


async def test_busy_when_both_slots_taken_and_slot_survives_timeout(mclient, session, monkeypatch):
    import threading
    import time

    from app.modules.importer import service

    # a third request while both slots are held is rejected at once
    await service._slots.acquire()
    await service._slots.acquire()
    try:
        r, _ = await do_import(mclient, session, build_docx())
        assert r.status_code == 503, r.text
        assert r.json()["error"]["code"] == "IMPORT_BUSY" and r.headers["retry-after"] == "30"
    finally:
        service._slots.release()
        service._slots.release()

    # a timed-out conversion keeps its slot until the thread really finishes
    gate = threading.Event()
    monkeypatch.setattr(service, "_extract", lambda raw: gate.wait(10))
    monkeypatch.setattr(service, "TIME_LIMIT", 0.2)
    r, _ = await do_import(mclient, session, build_docx())
    assert r.status_code == 422 and r.json()["error"]["code"] == "IMPORT_TIMEOUT"
    assert service._slots._value == service.CONVERSION_SLOTS - 1
    gate.set()
    for _ in range(100):
        if service._slots._value == service.CONVERSION_SLOTS:
            break
        await __import__("asyncio").sleep(0.05)
    assert service._slots._value == service.CONVERSION_SLOTS


async def test_failure_after_image_upload_removes_the_media(mclient, session, storage, jobs, monkeypatch):
    from app.core.errors import AppError
    from app.modules.importer import service

    async def boom(*a, **kw):
        raise AppError(422, "BOOM", "create failed")

    monkeypatch.setattr(service.posts_service, "create_post", boom)
    r, _ = await do_import(mclient, session, build_docx(image=image_bytes()))
    assert r.status_code == 422 and r.json()["error"]["code"] == "BOOM"
    assert (await session.scalars(select(Media))).all() == []
    assert not any((storage.root / "media").rglob("*.png"))
    assert jobs == []


async def test_upload_deadline_skips_remaining_images(mclient, session, monkeypatch):
    from app.modules.importer import service

    monkeypatch.setattr(service, "UPLOAD_DEADLINE", -1)
    r, _ = await do_import(mclient, session, build_docx(image=image_bytes()))
    assert r.status_code == 201, r.text
    assert r.json()["report"]["images"] == 0
    assert any("took too long" in w for w in r.json()["report"]["warnings"])
