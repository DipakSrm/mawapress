"""Whitelist renderer for TipTap JSON. Raw client HTML is never trusted."""

import html
import re
from urllib.parse import SplitResult, parse_qs, urlsplit

import nh3

_COLOR = re.compile(r"(#[0-9a-fA-F]{3,8}|rgb\(\s*[0-9]{1,3}\s*,\s*[0-9]{1,3}\s*,\s*[0-9]{1,3}\s*\))")
_FONT_SIZE = re.compile(r"[0-9]{1,2}(px|pt)")
FONTS = {"Mukta", "Noto Sans Devanagari", "Inter"}
LINE_HEIGHTS = {"1", "1.0", "1.15", "1.5", "2", "2.0"}
ALIGNS = {"center", "right", "justify"}
LINK_SCHEMES = ("http://", "https://", "mailto:")

_STYLED = {"p", "h1", "h2", "h3", "h4", "span", "mark"}
ALLOWED_TAGS = _STYLED | {
    "strong", "em", "u", "s", "a", "ul", "ol", "li", "blockquote", "br", "hr", "figure", "img", "figcaption",
    "table", "tbody", "tr", "th", "td", "div", "iframe",
}
ALLOWED_ATTRS = {tag: {"style"} for tag in _STYLED} | {
    "a": {"href", "target"},
    "img": {"src", "alt", "loading"},
    "table": set(),
    "tr": set(),
    "th": {"colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
    "div": {"class"},
    "blockquote": {"class", "data-embed"},
    "iframe": {"src", "title", "allow", "allowfullscreen", "loading", "referrerpolicy"},
}
# Only values the renderer itself emits survive; nh3 enforces this after rendering as defence in depth.
_CLASS_VALUES = {"video-embed", "table-wrap", "embed"}
_IFRAME_SRC = re.compile(r"https://www\.youtube-nocookie\.com/embed/[A-Za-z0-9_-]{11}")
_IFRAME_ALLOW = "encrypted-media; picture-in-picture; fullscreen"
_IFRAME_FIXED = {
    "allow": _IFRAME_ALLOW,
    "title": "YouTube video",
    "loading": "lazy",
    "referrerpolicy": "strict-origin-when-cross-origin",
}
EMBED_HOSTS = {
    "facebook": {"facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch"},
    "x": {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"},
    "tiktok": {"tiktok.com", "www.tiktok.com", "vm.tiktok.com", "m.tiktok.com"},
}
_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com",
             "www.youtube-nocookie.com"}
_YT_ID = re.compile(r"[A-Za-z0-9_-]{11}")
MAX_URL = 2048
STYLE_PROPS = {"color", "background-color", "font-size", "font-family", "text-align", "line-height"}


MAX_DEPTH = 64


def _https_url(value: object, hosts: set[str]) -> SplitResult | None:
    """A plain https URL (no credentials, custom port or odd characters) on one of `hosts`; else None."""
    url = _str(value)
    if not url or len(url) > MAX_URL or any(c.isspace() or c in "\"'<>\\" for c in url):
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or parts.username or parts.password or port not in (None, 443):
        return None
    return parts if (parts.hostname or "") in hosts else None


def youtube_id(value: object) -> str | None:
    """The 11-character video id of a YouTube watch/short/embed/youtu.be URL, or None."""
    url = _str(value)
    if url and url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    parts = _https_url(url, _YT_HOSTS | {"youtu.be"})
    if parts is None:
        return None
    segments = [seg for seg in parts.path.split("/") if seg]
    if parts.hostname == "youtu.be":
        candidate = segments[0] if segments else None
    elif segments[:1] == ["watch"]:
        candidate = (parse_qs(parts.query).get("v") or [None])[0]
    elif len(segments) >= 2 and segments[0] in ("embed", "shorts", "live", "v"):
        candidate = segments[1]
    else:
        candidate = None
    return candidate if candidate and _YT_ID.fullmatch(candidate) else None


def _span(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 10 else None


def _cell(tag: str, attrs: dict, inner: str) -> str:
    extra = "".join(f' {name}="{n}"' for name in ("colspan", "rowspan")
                    if (n := _span(attrs.get(name))) not in (None, 1))
    return f"<{tag}{extra}>{inner}</{tag}>"


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _valid(value: object, pattern: re.Pattern) -> str | None:
    value = _str(value)
    return value if value and pattern.fullmatch(value) else None


def _choice(value: object, allowed: set[str]) -> str | None:
    value = _str(value)
    return value if value in allowed else None


def _style(pairs: dict[str, str | None]) -> str:
    parts = [f"{k}: {v}" for k, v in pairs.items() if v]
    return f' style="{html.escape("; ".join(parts))}"' if parts else ""


def _block_style(attrs: dict) -> str:
    return _style({
        "text-align": _choice(attrs.get("textAlign"), ALIGNS),
        "line-height": _choice(attrs.get("lineHeight"), LINE_HEIGHTS),
    })


def _render_text(node: dict) -> str:
    out = html.escape(_str(node.get("text")) or "")
    marks = node.get("marks")
    for mark in marks if isinstance(marks, list) else []:
        mark = _dict(mark)
        kind = mark.get("type")
        attrs = _dict(mark.get("attrs"))
        if kind == "bold":
            out = f"<strong>{out}</strong>"
        elif kind == "italic":
            out = f"<em>{out}</em>"
        elif kind == "underline":
            out = f"<u>{out}</u>"
        elif kind == "strike":
            out = f"<s>{out}</s>"
        elif kind == "highlight":
            out = f"<mark{_style({'background-color': _valid(attrs.get('color'), _COLOR)})}>{out}</mark>"
        elif kind == "textStyle":
            style = _style({
                "color": _valid(attrs.get("color"), _COLOR),
                "font-size": _valid(attrs.get("fontSize"), _FONT_SIZE),
                "font-family": _choice(attrs.get("fontFamily"), FONTS),
            })
            if style:
                out = f"<span{style}>{out}</span>"
        elif kind == "link":
            href = _str(attrs.get("href")) or ""
            if href.startswith(LINK_SCHEMES):
                out = f'<a href="{html.escape(href)}" target="_blank">{out}</a>'
    return out


def _children(node: dict, depth: int) -> str:
    content = node.get("content")
    if not isinstance(content, list):
        return ""
    return "".join(_render(child, depth + 1) for child in content if isinstance(child, dict))


def _render(node: dict, depth: int = 0) -> str:
    if depth > MAX_DEPTH or not isinstance(node, dict):
        return ""
    attrs = _dict(node.get("attrs"))
    match node.get("type"):
        case "text":
            return _render_text(node)
        case "paragraph":
            return f"<p{_block_style(attrs)}>{_children(node, depth)}</p>"
        case "heading":
            raw = attrs.get("level")
            level = raw if isinstance(raw, int) and not isinstance(raw, bool) and raw in (1, 2, 3, 4) else 2
            return f"<h{level}{_block_style(attrs)}>{_children(node, depth)}</h{level}>"
        case "bulletList":
            return f"<ul>{_children(node, depth)}</ul>"
        case "orderedList":
            return f"<ol>{_children(node, depth)}</ol>"
        case "listItem":
            return f"<li>{_children(node, depth)}</li>"
        case "blockquote":
            return f"<blockquote>{_children(node, depth)}</blockquote>"
        case "hardBreak":
            return "<br>"
        case "horizontalRule":
            return "<hr>"
        case "image":
            src = _str(attrs.get("src")) or ""
            if not (src.startswith("https://") or (src.startswith("/") and not src.startswith(("//", "/\\")))):
                return ""
            img = f'<img src="{html.escape(src)}" alt="{html.escape(_str(attrs.get("alt")) or "")}" loading="lazy">'
            caption = _str(attrs.get("caption"))
            return f"<figure>{img}<figcaption>{html.escape(caption)}</figcaption></figure>" if caption else f"<figure>{img}</figure>"
        case "table":
            return f'<div class="table-wrap"><table><tbody>{_children(node, depth)}</tbody></table></div>'
        case "tableRow":
            return f"<tr>{_children(node, depth)}</tr>"
        case "tableHeader":
            return _cell("th", attrs, _children(node, depth))
        case "tableCell":
            return _cell("td", attrs, _children(node, depth))
        case "youtube":
            video = youtube_id(attrs.get("src"))
            if not video:
                return ""
            return (
                '<div class="video-embed">'
                f'<iframe src="https://www.youtube-nocookie.com/embed/{video}" title="YouTube video" '
                f'allow="{_IFRAME_ALLOW}" allowfullscreen loading="lazy" referrerpolicy="strict-origin-when-cross-origin">'
                "</iframe></div>"
            )
        case "embed":
            provider = _choice(attrs.get("provider"), set(EMBED_HOSTS))
            if provider is None or _https_url(attrs.get("url"), EMBED_HOSTS[provider]) is None:
                return ""
            url = html.escape(attrs["url"])
            return f'<blockquote class="embed" data-embed="{provider}"><a href="{url}">{url}</a></blockquote>'
        case _:
            return _children(node, depth)


def _attribute_filter(tag: str, attr: str, value: str) -> str | None:
    if attr == "class":
        return value if value in _CLASS_VALUES else None
    if tag == "iframe":
        if attr == "src":
            return value if _IFRAME_SRC.fullmatch(value) else None
        if attr in _IFRAME_FIXED:
            return _IFRAME_FIXED[attr] if value == _IFRAME_FIXED[attr] else None
        if attr == "allowfullscreen":
            return ""
    if attr == "data-embed":
        return value if value in EMBED_HOSTS else None
    if attr in ("colspan", "rowspan"):
        return value if value.isascii() and value.isdigit() and 1 <= int(value) <= 10 else None
    return value


def render_html(doc: dict) -> str:
    return nh3.clean(
        _render(doc),
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        filter_style_properties=STYLE_PROPS,
        link_rel="noopener nofollow",
        url_schemes={"http", "https", "mailto"},
        attribute_filter=_attribute_filter,
    )
