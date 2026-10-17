"""Mammoth's semantic HTML -> TipTap JSON, restricted to what posts/render.py renders.

Anything the renderer has no node for keeps its text and is reported as a warning. Only http/https/mailto
links survive as link marks, and image nodes are only emitted for sources the caller resolved (our storage).
"""

from collections import Counter
from html.parser import HTMLParser

from app.modules.posts.render import LINK_SCHEMES

MAX_DEPTH = 64
VOID = {"br", "hr", "img", "meta", "link", "input", "col", "wbr"}
DROPPED = {"script", "style", "head", "title", "template"}  # element and contents vanish silently
MARKS = {"strong": "bold", "b": "bold", "em": "italic", "i": "italic", "u": "underline",
         "s": "strike", "strike": "strike", "del": "strike"}
BLOCKS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "hr", "table", "thead", "tbody",
          "tfoot", "tr", "td", "th", "div", "section", "article", "pre", "figure", "figcaption", "body", "html"}
INLINE_OK = {"a", "br", "img", "span", "sup", "sub"} | set(MARKS)  # span/sup/sub: text kept, no warning
GROUPING = {"div", "section", "article", "body", "html", "figure", "figcaption", "thead", "tbody", "tfoot"}


class _Node:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag: str, attrs: dict[str, str]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list[_Node | str] = []


class _Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self.stack = [self.root]
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag in DROPPED:
                self.skip += 1
            return
        if tag in DROPPED:
            self.skip = 1
            return
        node = _Node(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        if tag in DROPPED:
            return
        self.handle_starttag(tag, attrs)
        if tag not in VOID and not self.skip:
            self.stack.pop()

    def handle_endtag(self, tag):
        if self.skip:
            if tag in DROPPED:
                self.skip -= 1
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if not self.skip:
            self.stack[-1].children.append(data)


def _text_of(node: _Node | str) -> str:
    """Plain text of a subtree, iteratively (no recursion limit to hit)."""
    out: list[str] = []
    todo: list[_Node | str] = [node]
    while todo:
        cur = todo.pop()
        if isinstance(cur, str):
            out.append(cur)
            continue
        if cur.tag in BLOCKS:
            todo.append(" ")
        todo.extend(reversed(cur.children))
    return " ".join("".join(out).split())


class _Converter:
    def __init__(self, images: dict[str, str]) -> None:
        self.images = images
        self.warnings: Counter[str] = Counter()  # insertion-ordered

    def warn(self, message: str) -> None:
        self.warnings[message] += 1

    # inline ---------------------------------------------------------------------------------------------

    def inline(self, children, marks: list[dict], depth: int) -> list[dict]:
        out: list[dict] = []
        for child in children:
            if isinstance(child, str):
                if child:
                    node = {"type": "text", "text": child}
                    if marks:
                        node["marks"] = [dict(m) for m in marks]
                    out.append(node)
            else:
                out.extend(self.inline_element(child, marks, depth + 1))
        return out

    def inline_element(self, el: _Node, marks: list[dict], depth: int) -> list[dict]:
        if depth > MAX_DEPTH:
            self.warn("deeply nested content was flattened to text")
            text = _text_of(el)
            return [{"type": "text", "text": text}] if text else []
        tag = el.tag
        if tag == "br":
            return [{"type": "hardBreak"}]
        if tag == "img":
            return self.image(el)
        if tag in MARKS:
            mark = {"type": MARKS[tag]}
            inner = marks if mark in marks else [*marks, mark]
            return self.inline(el.children, inner, depth)
        if tag == "a":
            href = el.attrs.get("href", "").strip()
            if href.lower().startswith(LINK_SCHEMES):
                mark = {"type": "link", "attrs": {"href": href}}
                return self.inline(el.children, [*marks, mark], depth)
            self.warn("link with an unsupported address was kept as plain text")
            return self.inline(el.children, marks, depth)
        if tag not in INLINE_OK and tag not in BLOCKS:
            self.warn(f"unsupported element <{tag}> was kept as plain text")
        return self.inline(el.children, marks, depth)

    def image(self, el: _Node) -> list[dict]:
        src = el.attrs.get("src", "")
        url = self.images.get(src)
        if url is None:
            self.warn("an image with an unknown source was removed")
            return []
        return [{"type": "image", "attrs": {"src": url, "alt": el.attrs.get("alt", "")}}]

    @staticmethod
    def paragraphs(nodes: list[dict]) -> list[dict]:
        """Inline nodes -> paragraphs, with images (block nodes in the renderer) lifted out between them."""
        blocks: list[dict] = []
        run: list[dict] = []

        def flush() -> None:
            if run and any(n["type"] == "hardBreak" or n["text"].strip() for n in run):
                blocks.append({"type": "paragraph", "content": list(run)})
            run.clear()

        for node in nodes:
            if node["type"] == "image":
                flush()
                blocks.append(node)
            else:
                run.append(node)
        flush()
        return blocks

    # blocks ---------------------------------------------------------------------------------------------

    def blocks(self, children, depth: int) -> list[dict]:
        out: list[dict] = []
        run: list[_Node | str] = []

        def flush() -> None:
            if run:
                out.extend(self.paragraphs(self.inline(run, [], depth)))
                run.clear()

        for child in children:
            if isinstance(child, str) or child.tag not in BLOCKS:
                run.append(child)
                continue
            flush()
            out.extend(self.block(child, depth + 1))
        flush()
        return out

    def block(self, el: _Node, depth: int) -> list[dict]:
        if depth > MAX_DEPTH:
            self.warn("deeply nested content was flattened to text")
            text = _text_of(el)
            return [{"type": "paragraph", "content": [{"type": "text", "text": text}]}] if text else []
        tag = el.tag
        if tag == "p" or tag == "pre":
            return self.paragraphs(self.inline(el.children, [], depth))
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            if level > 4:
                self.warn(f"heading level {level} was mapped to level 4")
                level = 4
            nodes = self.inline(el.children, [], depth)
            text = [n for n in nodes if n["type"] != "image"]
            if not any(n["type"] == "text" and n["text"].strip() for n in text):
                text = []
            heading = [{"type": "heading", "attrs": {"level": level}, "content": text}] if text else []
            return heading + [n for n in nodes if n["type"] == "image"]
        if tag in ("ul", "ol"):
            items = []
            for child in el.children:
                if isinstance(child, str):
                    if child.strip():
                        self.warn("text outside a list item was dropped")
                    continue
                if child.tag != "li":
                    self.warn(f"unsupported element <{child.tag}> inside a list was dropped")
                    continue
                items.append({"type": "listItem", "content": self.blocks(child.children, depth) or [{"type": "paragraph"}]})
            return [{"type": "bulletList" if tag == "ul" else "orderedList", "content": items}] if items else []
        if tag == "li":  # stray item outside a list: keep its content
            return self.blocks(el.children, depth)
        if tag == "blockquote":
            return [{"type": "blockquote", "content": self.blocks(el.children, depth) or [{"type": "paragraph"}]}]
        if tag == "hr":
            return [{"type": "horizontalRule"}]
        if tag == "table":
            return self.table(el)
        if tag not in GROUPING:
            self.warn(f"unsupported element <{tag}> was kept as plain text")
        return self.blocks(el.children, depth)

    def table(self, table: _Node) -> list[dict]:
        self.warn("table converted to plain text rows")
        rows: list[str] = []
        todo: list[_Node | str] = list(reversed(table.children))
        while todo:  # iterative: tables nest arbitrarily deep
            cur = todo.pop()
            if isinstance(cur, str):
                continue
            if cur.tag == "tr":
                cells = [_text_of(c) for c in cur.children if not isinstance(c, str) and c.tag in ("td", "th")]
                if any(cells):
                    rows.append(" | ".join(cells))
            else:
                todo.extend(reversed(cur.children))
        return [{"type": "paragraph", "content": [{"type": "text", "text": row}]} for row in rows]


def convert(html: str, images: dict[str, str] | None = None) -> tuple[dict, list[str]]:
    """Returns (TipTap doc, warnings). `images` maps an <img src> to our stored URL; other sources are dropped."""
    tree = _Tree()
    tree.feed(html)
    tree.close()
    conv = _Converter(images or {})
    content = conv.blocks(tree.root.children, 0) or [{"type": "paragraph"}]
    warnings = [f"{msg} (x{n})" if n > 1 else msg for msg, n in conv.warnings.items()]
    return {"type": "doc", "content": content}, warnings
