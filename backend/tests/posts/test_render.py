from app.modules.posts.render import render_html


def doc(*blocks):
    return {"type": "doc", "content": list(blocks)}


def para(*inlines, **attrs):
    return {"type": "paragraph", "attrs": attrs, "content": list(inlines)}


def text(value, *marks):
    return {"type": "text", "text": value, "marks": list(marks)}


def test_bold_italic_and_colour():
    out = render_html(doc(para(
        text("Breaking", {"type": "bold"}),
        text(" red", {"type": "textStyle", "attrs": {"color": "#C8102E", "fontSize": "18px"}}),
    )))
    assert "<strong>Breaking</strong>" in out
    assert "#C8102E" in out and "18px" in out


def test_heading_level_is_clamped():
    out = render_html(doc({"type": "heading", "attrs": {"level": 9}, "content": [text("Title")]}))
    assert out == "<h2>Title</h2>"


def test_line_height_and_alignment():
    out = render_html(doc(para(text("x"), textAlign="center", lineHeight="1.5")))
    assert "text-align" in out and "center" in out and "line-height" in out


def test_script_in_text_is_escaped():
    out = render_html(doc(para(text("<script>alert(1)</script>"))))
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_javascript_link_is_dropped_but_text_kept():
    out = render_html(doc(para(text("click", {"type": "link", "attrs": {"href": "javascript:alert(1)"}}))))
    assert "javascript" not in out
    assert "click" in out


def test_safe_link_gets_rel():
    out = render_html(doc(para(text("site", {"type": "link", "attrs": {"href": "https://mawapress.com"}}))))
    assert 'href="https://mawapress.com"' in out
    assert "noopener" in out


def test_css_injection_in_colour_is_ignored():
    out = render_html(doc(para(text("x", {"type": "textStyle", "attrs": {"color": "red;background:url(evil)"}}))))
    assert "evil" not in out
    assert "<span" not in out


def test_image_with_caption_and_bad_src():
    good = render_html(doc({"type": "image", "attrs": {"src": "https://cdn.mawapress.com/a.webp", "alt": "बाढी", "caption": "Photo"}}))
    assert '<img src="https://cdn.mawapress.com/a.webp"' in good and "<figcaption>Photo</figcaption>" in good
    bad = render_html(doc({"type": "image", "attrs": {"src": "javascript:x"}}))
    assert bad == ""


def test_unknown_node_keeps_text():
    out = render_html(doc({"type": "mysteryWidget", "content": [para(text("still here"))]}))
    assert out == "<p>still here</p>"


def test_lists_and_blockquote():
    out = render_html(doc(
        {"type": "bulletList", "content": [{"type": "listItem", "content": [para(text("a"))]}]},
        {"type": "blockquote", "content": [para(text("q"))]},
    ))
    assert out == "<ul><li><p>a</p></li></ul><blockquote><p>q</p></blockquote>"


def test_malformed_input_never_raises():
    cases = [
        text("x", {"type": "textStyle", "attrs": {"fontFamily": ["Inter"]}}),
        "stray string child",
        {"type": "text", "text": None},
        {"type": "text", "text": "a", "marks": "bold"},
        {"type": "text", "text": "a", "marks": ["bold", {"type": "link", "attrs": "x"}]},
    ]
    for case in cases:
        assert isinstance(render_html(doc(para(case))), str)
    assert isinstance(render_html(doc(para(text("x"), textAlign=["center"], lineHeight=["2"]))), str)
    assert isinstance(render_html(doc({"type": "image", "attrs": {"src": "/a.png", "caption": 5}})), str)
    assert isinstance(render_html(doc({"type": "paragraph", "attrs": "bad", "content": "bad"})), str)


def test_deep_nesting_does_not_raise():
    node = para(text("deep"))
    for _ in range(200):
        node = {"type": "blockquote", "content": [node]}
    assert isinstance(render_html(doc(node)), str)


def test_backslash_image_src_rejected():
    assert render_html(doc({"type": "image", "attrs": {"src": "/\\evil.com/x.png"}})) == ""


def test_boolean_heading_level_defaults_to_h2():
    out = render_html(doc({"type": "heading", "attrs": {"level": True}, "content": [text("T")]}))
    assert out == "<h2>T</h2>"


def test_line_height_two_point_zero_allowed():
    assert "2.0" in render_html(doc(para(text("x"), lineHeight="2.0")))
