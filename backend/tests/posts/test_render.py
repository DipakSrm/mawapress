from html.parser import HTMLParser

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


class _StartTags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def start_tags(markup: str) -> list[tuple[str, dict[str, str | None]]]:
    parser = _StartTags()
    parser.feed(markup)
    parser.close()
    return parser.tags


def test_quote_in_alt_cannot_break_out_of_attribute():
    hostile = '" onerror="alert(1)'
    out = render_html(doc({"type": "image", "attrs": {"src": "https://cdn.mawapress.com/a.webp", "alt": hostile}}))
    img = next(attrs for tag, attrs in start_tags(out) if tag == "img")
    assert set(img) == {"src", "alt", "loading"}
    assert img["alt"] == hostile  # survives as text, inside the attribute


def test_quote_in_href_cannot_add_attributes():
    hostile = 'https://mawapress.com/" onclick="alert(1)'
    out = render_html(doc(para(text("x", {"type": "link", "attrs": {"href": hostile}}))))
    link = next(attrs for tag, attrs in start_tags(out) if tag == "a")
    assert set(link) == {"href", "target", "rel"}
    assert link["href"] == hostile


def test_markup_in_caption_stays_text():
    hostile = "</figcaption><script>alert(1)</script>"
    out = render_html(doc({"type": "image", "attrs": {"src": "https://cdn.mawapress.com/a.webp", "caption": hostile}}))
    assert [tag for tag, _ in start_tags(out)] == ["figure", "img", "figcaption"]
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


# --- tables, YouTube and embeds ---------------------------------------------------------------------------


def cell(kind, value, **attrs):
    return {"type": kind, "attrs": attrs, "content": [para(text(value))]}


def table(*rows):
    return {"type": "table", "content": [{"type": "tableRow", "content": list(r)} for r in rows]}


def test_table_renders_header_and_cells_with_spans():
    out = render_html(doc(table(
        [cell("tableHeader", "H1", colspan=2, rowspan=1)],
        [cell("tableCell", "a", colspan=1, rowspan=3), cell("tableCell", "b")],
    )))
    assert out == (
        '<div class="table-wrap"><table><tbody>'
        '<tr><th colspan="2"><p>H1</p></th></tr>'
        '<tr><td rowspan="3"><p>a</p></td><td><p>b</p></td></tr>'
        "</tbody></table></div>"
    )


def test_table_bad_spans_are_dropped():
    for bad in (0, 11, -1, True, "2", 1.5, None, [2]):
        out = render_html(doc(table([cell("tableCell", "x", colspan=bad, rowspan=bad)])))
        assert "colspan" not in out and "rowspan" not in out, bad
        assert "<td><p>x</p></td>" in out


def test_table_nesting_lists_and_nested_tables():
    inner = table([cell("tableCell", "inner")])
    outer = table([{"type": "tableCell", "attrs": {}, "content": [
        {"type": "bulletList", "content": [{"type": "listItem", "content": [para(text("li"))]}]},
        inner,
    ]}])
    out = render_html(doc(outer))
    assert out.count("<table>") == 2
    assert "<ul><li><p>li</p></li></ul>" in out and "<td><p>inner</p></td>" in out


def test_table_cell_formatting_marks_survive():
    out = render_html(doc(table([{"type": "tableCell", "content": [
        para(text("x", {"type": "bold"}), textAlign="center"),
    ]}])))
    assert "<strong>x</strong>" in out and "text-align" in out


def yt(src):
    return render_html(doc({"type": "youtube", "attrs": {"src": src}}))


def test_youtube_renders_privacy_enhanced_iframe():
    for src in (
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?t=5",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://m.youtube.com/watch?feature=x&v=dQw4w9WgXcQ",
        "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
    ):
        out = yt(src)
        iframe = next(attrs for tag, attrs in start_tags(out) if tag == "iframe")
        assert iframe["src"] == "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ", src
        assert "allowfullscreen" in iframe and iframe["allow"]
        assert out.startswith('<div class="video-embed">')


def test_youtube_rejects_other_hosts_and_bad_ids():
    for src in (
        "https://evil.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
        "https://evil.com/https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://user:pw@www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com:8080/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=short",
        'https://www.youtube.com/watch?v="onload="x',
        "javascript:alert(1)",
        "//www.youtube.com/watch?v=dQw4w9WgXcQ",
        "",
        None,
        123,
    ):
        assert yt(src) == "", src


def test_non_youtube_iframe_cannot_be_smuggled_via_text_or_attrs():
    out = render_html(doc(para(text('<iframe src="https://evil.com"></iframe>'))))
    assert "<iframe" not in out
    out = yt("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert "evil" not in out


def test_iframe_attribute_filter_is_defence_in_depth():
    from app.modules.posts.render import _attribute_filter

    assert _attribute_filter("iframe", "src", "https://evil.com/embed/dQw4w9WgXcQ") is None
    assert _attribute_filter("iframe", "src", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ")
    assert _attribute_filter("div", "class", "evil") is None


def embed(provider, url):
    return render_html(doc({"type": "embed", "attrs": {"provider": provider, "url": url}}))


def test_embed_renders_blockquote_placeholder_without_script():
    cases = {
        "facebook": "https://www.facebook.com/mawapress/posts/123",
        "x": "https://x.com/user/status/1",
        "tiktok": "https://www.tiktok.com/@u/video/1",
    }
    for provider, url in cases.items():
        out = embed(provider, url)
        tags = start_tags(out)
        assert [t for t, _ in tags] == ["blockquote", "a"]
        assert tags[0][1] == {"class": "embed", "data-embed": provider}
        assert tags[1][1]["href"] == url
        assert "<script" not in out


def test_embed_rejects_wrong_provider_domain_scheme_and_junk():
    for provider, url in (
        ("x", "https://www.facebook.com/a"),
        ("facebook", "https://facebook.com.evil.com/a"),
        ("facebook", "http://www.facebook.com/a"),
        ("tiktok", "javascript:alert(1)"),
        ("x", "https://user@x.com/a"),
        ("x", 'https://x.com/a" onclick="x'),
        ("myspace", "https://myspace.com/a"),
        ("x", None),
        (None, "https://x.com/a"),
        (["x"], "https://x.com/a"),
        ("x", "https://x.com/" + "a" * 3000),
    ):
        assert embed(provider, url) == "", (provider, url)


def test_tables_and_embeds_malformed_input_never_raises():
    cases = [
        {"type": "table", "content": "bad"},
        {"type": "table", "content": [{"type": "tableRow", "content": [{"type": "tableCell", "attrs": "x"}]}]},
        {"type": "embed", "attrs": "bad"},
        {"type": "youtube"},
    ]
    for case in cases:
        assert isinstance(render_html(doc(case)), str)


# --- fix round: regex anchoring, pinned iframe attrs, depth cap and hostile HTML through nh3 ---------------


def test_trailing_newline_cannot_slip_past_anchored_patterns():
    from app.modules.posts.render import _attribute_filter

    assert _attribute_filter("iframe", "src", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ\n") is None
    assert yt("https://youtu.be/dQw4w9WgXcQ\n") == ""
    assert yt("https://www.youtube.com/watch?v=dQw4w9WgXcQ%0A") == ""
    assert "color" not in render_html(doc(para(text("x", {"type": "textStyle", "attrs": {"color": "#fff\n"}}))))
    assert "font-size" not in render_html(
        doc(para(text("x", {"type": "textStyle", "attrs": {"fontSize": "12px\n"}})))
    )


def test_iframe_title_loading_referrerpolicy_are_pinned():
    from app.modules.posts.render import _attribute_filter

    for attr in ("title", "loading", "referrerpolicy", "allow"):
        assert _attribute_filter("iframe", attr, "anything else") is None
    assert _attribute_filter("iframe", "loading", "lazy") == "lazy"
    assert _attribute_filter("td", "colspan", "²") is None  # non-ASCII digits are not spans


def test_nested_tables_hit_the_depth_cap_without_raising():
    node = {"type": "table", "content": [{"type": "tableRow", "content": [cell("tableCell", "deep")]}]}
    for _ in range(100):
        node = {"type": "table", "content": [{"type": "tableRow", "content": [
            {"type": "tableCell", "content": [node]}]}]}
    out = render_html(doc(node))
    assert "deep" not in out  # beyond MAX_DEPTH the content is dropped
    assert out.count("<table>") < 100


def test_hostile_html_is_stripped_by_the_real_nh3_config():
    import nh3

    from app.modules.posts import render as r

    hostile = (
        '<iframe src="https://evil.com/x" srcdoc="<script>1</script>" allow="camera" title="t" loading="eager" '
        'referrerpolicy="unsafe-url" onload="x()"></iframe>'
        '<iframe src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ" allow="camera; microphone"></iframe>'
        '<table onclick="x()"><tbody><tr><td colspan="99" rowspan="0" onclick="x()">a</td>'
        '<th colspan="3">b</th></tr></tbody></table>'
        '<div class="evil" onclick="x()">d</div><blockquote class="embed" data-embed="myspace">q</blockquote>'
        '<p onclick="x()" style="position:fixed;color:#fff">p</p>'
    )
    out = nh3.clean(
        hostile, tags=r.ALLOWED_TAGS, attributes=r.ALLOWED_ATTRS, filter_style_properties=r.STYLE_PROPS,
        link_rel="noopener nofollow", url_schemes={"http", "https", "mailto"}, attribute_filter=r._attribute_filter,
    )
    assert "evil.com" not in out and "srcdoc" not in out and "onload" not in out and "onclick" not in out
    assert "camera" not in out and "microphone" not in out and "unsafe-url" not in out and "eager" not in out
    assert "colspan=\"99\"" not in out and "rowspan" not in out and 'colspan="3"' in out
    assert 'class="evil"' not in out and "myspace" not in out and "position" not in out
    assert "#fff" in out.replace(" ", "")
    assert "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ" in out
