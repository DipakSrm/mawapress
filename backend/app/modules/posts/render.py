"""Whitelist renderer for TipTap JSON. Raw client HTML is never trusted."""

import html
import re

import nh3

_COLOR = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\))$")
_FONT_SIZE = re.compile(r"^\d{1,2}(px|pt)$")
FONTS = {"Mukta", "Noto Sans Devanagari", "Inter"}
LINE_HEIGHTS = {"1", "1.0", "1.15", "1.5", "2", "2.0"}
ALIGNS = {"center", "right", "justify"}
LINK_SCHEMES = ("http://", "https://", "mailto:")

_STYLED = {"p", "h1", "h2", "h3", "h4", "span", "mark"}
ALLOWED_TAGS = _STYLED | {
    "strong", "em", "u", "s", "a", "ul", "ol", "li", "blockquote", "br", "hr", "figure", "img", "figcaption",
}
ALLOWED_ATTRS = {tag: {"style"} for tag in _STYLED} | {
    "a": {"href", "target"},
    "img": {"src", "alt", "loading"},
}
STYLE_PROPS = {"color", "background-color", "font-size", "font-family", "text-align", "line-height"}


MAX_DEPTH = 64


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _valid(value: object, pattern: re.Pattern) -> str | None:
    value = _str(value)
    return value if value and pattern.match(value) else None


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
        case _:
            return _children(node, depth)


def render_html(doc: dict) -> str:
    return nh3.clean(
        _render(doc),
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        filter_style_properties=STYLE_PROPS,
        link_rel="noopener nofollow",
        url_schemes={"http", "https", "mailto"},
    )
