"""Whitelist renderer for TipTap JSON. Raw client HTML is never trusted."""

import html
import re

import nh3

_COLOR = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\))$")
_FONT_SIZE = re.compile(r"^\d{1,2}(px|pt)$")
FONTS = {"Mukta", "Noto Sans Devanagari", "Inter"}
LINE_HEIGHTS = {"1", "1.15", "1.5", "2"}
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


def _valid(value: str | None, pattern: re.Pattern) -> str | None:
    return value if value and pattern.match(value) else None


def _style(pairs: dict[str, str | None]) -> str:
    parts = [f"{k}: {v}" for k, v in pairs.items() if v]
    return f' style="{html.escape("; ".join(parts))}"' if parts else ""


def _block_style(attrs: dict) -> str:
    align = attrs.get("textAlign")
    line_height = attrs.get("lineHeight")
    return _style({
        "text-align": align if align in ALIGNS else None,
        "line-height": line_height if line_height in LINE_HEIGHTS else None,
    })


def _render_text(node: dict) -> str:
    out = html.escape(node.get("text", ""))
    for mark in node.get("marks") or []:
        kind = mark.get("type")
        attrs = mark.get("attrs") or {}
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
                "font-family": attrs.get("fontFamily") if attrs.get("fontFamily") in FONTS else None,
            })
            if style:
                out = f"<span{style}>{out}</span>"
        elif kind == "link":
            href = attrs.get("href") or ""
            if href.startswith(LINK_SCHEMES):
                out = f'<a href="{html.escape(href)}" target="_blank">{out}</a>'
    return out


def _children(node: dict) -> str:
    return "".join(_render(child) for child in node.get("content") or [])


def _render(node: dict) -> str:
    attrs = node.get("attrs") or {}
    match node.get("type"):
        case "text":
            return _render_text(node)
        case "paragraph":
            return f"<p{_block_style(attrs)}>{_children(node)}</p>"
        case "heading":
            level = attrs.get("level") if attrs.get("level") in (1, 2, 3, 4) else 2
            return f"<h{level}{_block_style(attrs)}>{_children(node)}</h{level}>"
        case "bulletList":
            return f"<ul>{_children(node)}</ul>"
        case "orderedList":
            return f"<ol>{_children(node)}</ol>"
        case "listItem":
            return f"<li>{_children(node)}</li>"
        case "blockquote":
            return f"<blockquote>{_children(node)}</blockquote>"
        case "hardBreak":
            return "<br>"
        case "horizontalRule":
            return "<hr>"
        case "image":
            src = attrs.get("src") or ""
            if not (src.startswith("https://") or (src.startswith("/") and not src.startswith("//"))):
                return ""
            img = f'<img src="{html.escape(src)}" alt="{html.escape(attrs.get("alt") or "")}" loading="lazy">'
            caption = attrs.get("caption")
            return f"<figure>{img}<figcaption>{html.escape(caption)}</figcaption></figure>" if caption else f"<figure>{img}</figure>"
        case _:
            return _children(node)


def render_html(doc: dict) -> str:
    return nh3.clean(
        _render(doc),
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        filter_style_properties=STYLE_PROPS,
        link_rel="noopener nofollow",
        url_schemes={"http", "https", "mailto"},
    )
