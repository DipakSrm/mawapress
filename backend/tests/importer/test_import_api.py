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


async def test_xxe_is_not_resolved(mclient, session, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRETVALUE")
    xml = (
        f'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "{secret.as_uri()}">]>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>&x;</w:t></w:r></w:p></w:body></w:document>"
    ).encode()
    good = zipfile.ZipFile(io.BytesIO(build_docx()))
    members = {n: good.read(n) for n in good.namelist()}
    members["word/document.xml"] = xml
    r, _ = await do_import(mclient, session, zip_with(members))
    assert "TOPSECRETVALUE" not in r.text
