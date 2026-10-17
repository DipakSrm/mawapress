from app.modules.importer.html_to_tiptap import convert
from app.modules.posts.render import render_html


def text(t, *marks):
    node = {"type": "text", "text": t}
    if marks:
        node["marks"] = [m if isinstance(m, dict) else {"type": m} for m in marks]
    return node


def test_inline_marks_and_link():
    doc, warnings = convert('<p>a <strong>b</strong><em><u>c</u></em><s>d</s><a href="https://x.com/">e</a></p>')
    assert doc["content"] == [{"type": "paragraph", "content": [
        text("a "), text("b", "bold"), text("c", "italic", "underline"), text("d", "strike"),
        text("e", {"type": "link", "attrs": {"href": "https://x.com/"}}),
    ]}]
    assert warnings == []


def test_unsafe_links_become_plain_text():
    doc, warnings = convert('<p><a href="javascript:alert(1)">x</a><a href="data:text/html,hi">y</a><a href="/rel">z</a>'
                            '<a href="mailto:a@b.co">m</a></p>')
    content = doc["content"][0]["content"]
    assert content[:3] == [text("x"), text("y"), text("z")]
    assert content[3] == text("m", {"type": "link", "attrs": {"href": "mailto:a@b.co"}})
    assert warnings == ["link with an unsupported address was kept as plain text (x3)"]


def test_headings_lists_quote_rule_and_breaks():
    doc, _ = convert("<h2>H</h2><ul><li>a</li><li>b<ul><li>c</li></ul></li></ul><ol><li>1</li></ol>"
                     "<blockquote><p>q</p></blockquote><hr><p>x<br>y</p>")
    types = [n["type"] for n in doc["content"]]
    assert types == ["heading", "bulletList", "orderedList", "blockquote", "horizontalRule", "paragraph"]
    assert doc["content"][0]["attrs"] == {"level": 2}
    item = doc["content"][1]["content"][1]
    assert item["type"] == "listItem"
    assert [c["type"] for c in item["content"]] == ["paragraph", "bulletList"]
    assert doc["content"][5]["content"][1] == {"type": "hardBreak"}


def test_table_becomes_real_table_nodes():
    doc, warnings = convert("<table><thead><tr><th>H</th><th colspan=\"2\">I</th></tr></thead>"
                            "<tbody><tr><td><p>a</p></td><td rowspan=\"x\">b</td><td>c</td></tr></tbody></table>")
    assert warnings == []
    (table,) = doc["content"]
    assert table["type"] == "table"
    head, body = table["content"]
    assert [c["type"] for c in head["content"]] == ["tableHeader", "tableHeader"]
    assert head["content"][1]["attrs"] == {"colspan": 2}
    assert [c["type"] for c in body["content"]] == ["tableCell"] * 3
    assert "attrs" not in body["content"][1]  # invalid rowspan dropped
    assert body["content"][0]["content"] == [{"type": "paragraph", "content": [text("a")]}]
    assert body["content"][1]["content"] == [{"type": "paragraph", "content": [text("b")]}]
    out = render_html(doc)
    assert "<th>" in out and '<th colspan="2">' in out and "<td><p>a</p></td>" in out


def test_table_spans_are_clamped_and_cells_keep_safe_content_only():
    doc, warnings = convert('<table><tr><td colspan="99" rowspan="0"><a href="javascript:x">j</a>'
                            '<img src="evil.png"><ul><li>i</li></ul></td></tr></table>', {})
    cell = doc["content"][0]["content"][0]["content"][0]
    assert cell["attrs"] == {"colspan": 10}
    types = [n["type"] for n in cell["content"]]
    assert types == ["paragraph", "bulletList"]
    assert cell["content"][0]["content"] == [text("j")]
    assert any("image" in w for w in warnings) and any("link" in w for w in warnings)


def test_nested_table_and_empty_cells():
    doc, _ = convert("<table><tr><td><table><tr><td>in</td></tr></table></td><td></td></tr><tr></tr></table><table></table>")
    assert len(doc["content"]) == 1
    outer_row = doc["content"][0]["content"]
    assert len(outer_row) == 1  # the empty <tr> and the empty table are skipped
    first, second = outer_row[0]["content"]
    assert first["content"][0]["type"] == "table"
    assert second["content"] == [{"type": "paragraph"}]


def test_deeply_nested_tables_do_not_raise():
    html = "<table><tr><td>" * 300 + "x" + "</td></tr></table>" * 300
    doc, warnings = convert(html)
    assert isinstance(render_html(doc), str)
    assert any("deeply nested" in w for w in warnings)


def test_unknown_elements_keep_text_and_warn():
    doc, warnings = convert("<font><p>kept <code>code</code></p></font>")
    assert render_html(doc).startswith("<p>kept code</p>")
    assert any("code" in w for w in warnings) and any("font" in w for w in warnings)


def test_script_and_style_content_is_dropped():
    doc, _ = convert("<p>ok<script>alert(1)</script><style>p{}</style></p>")
    assert render_html(doc) == "<p>ok</p>"


def test_images_only_from_resolved_sources():
    html = '<p>t<img src="mawa-img:0" alt="A"></p><img src="https://evil.com/x.png"><img src="data:image/png;base64,AA==">'
    doc, warnings = convert(html, images={"mawa-img:0": "/media/2026/10/a.png"})
    assert doc["content"] == [
        {"type": "paragraph", "content": [text("t")]},
        {"type": "image", "attrs": {"src": "/media/2026/10/a.png", "alt": "A"}},
    ]
    assert warnings == ["an image with an unknown source was removed (x2)"]


def test_empty_input_gives_empty_paragraph():
    doc, _ = convert("")
    assert doc == {"type": "doc", "content": [{"type": "paragraph"}]}


def test_whitespace_only_heading_yields_no_heading():
    doc, _ = convert("<h2>   </h2><h3><br></h3><p>x</p>")
    assert [n["type"] for n in doc["content"]] == ["paragraph"]
