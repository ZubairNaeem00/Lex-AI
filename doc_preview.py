"""DOCX ⇄ HTML bridge behind the in-app draft editor.

The preview is read from the generated document itself and every editable block
keeps the index of the paragraph it came from, so a saved revision is written
back into those same paragraphs. Only the runs are replaced — the template's
styles, numbering, spacing and margins stay exactly as they were, which is what
keeps a revised draft looking like the original filing.
"""

from __future__ import annotations

import copy
import html as html_escape
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote

import lxml.etree as ET
import lxml.html as LH
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.text.paragraph import Paragraph

MAX_HTML_CHARS = 400_000

ALIGN_TO_CSS = {
    WD_ALIGN_PARAGRAPH.LEFT: "left",
    WD_ALIGN_PARAGRAPH.CENTER: "center",
    WD_ALIGN_PARAGRAPH.RIGHT: "right",
    WD_ALIGN_PARAGRAPH.JUSTIFY: "justify",
}
CSS_TO_ALIGN = {value: key for key, value in ALIGN_TO_CSS.items()}

NUM_FMT_TO_CSS = {
    "bullet": "disc",
    "decimal": "decimal",
    "lowerLetter": "lower-alpha",
    "upperLetter": "upper-alpha",
    "lowerRoman": "lower-roman",
    "upperRoman": "upper-roman",
    "none": "none",
}

# Tags the editor may use for a block of text. <ol>/<ul> are excluded on purpose:
# their <li> children are the paragraphs.
BLOCK_TAGS = {
    "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "pre", "section", "article",
}

# <font size="1..7"> sizes left behind by contenteditable toolbars.
HTML_FONT_SIZES = {1: 8.0, 2: 10.0, 3: 12.0, 4: 14.0, 5: 18.0, 6: 24.0, 7: 36.0}

RUN_TAGS = (qn("w:r"), qn("w:hyperlink"), qn("w:smartTag"), qn("w:ins"))


# ---------------------------------------------------------------------------
# Reading a .docx
# ---------------------------------------------------------------------------

def _doc_defaults(doc: Document) -> Dict[str, Any]:
    """Font family and size Word falls back to when nothing is set explicitly."""
    defaults: Dict[str, Any] = {"font": None, "size": None}
    element = doc.styles.element.find(qn("w:docDefaults"))
    if element is None:
        return defaults
    rpr = element.find(qn("w:rPrDefault") + "/" + qn("w:rPr"))
    if rpr is None:
        return defaults
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is not None:
        defaults["font"] = fonts.get(qn("w:ascii")) or fonts.get(qn("w:hAnsi"))
    size = rpr.find(qn("w:sz"))
    if size is not None:
        try:
            defaults["size"] = float(size.get(qn("w:val"))) / 2.0
        except (TypeError, ValueError):
            pass
    return defaults


def _numbering_map(doc: Document) -> Dict[int, Dict[int, Dict[str, Any]]]:
    """numId → level → format, so the preview can draw the same markers as Word."""
    try:
        root = doc.part.numbering_part.element
    except (AttributeError, KeyError, NotImplementedError):
        return {}

    abstracts: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for abstract in root.findall(qn("w:abstractNum")):
        levels: Dict[int, Dict[str, Any]] = {}
        for lvl in abstract.findall(qn("w:lvl")):
            try:
                ilvl = int(lvl.get(qn("w:ilvl") or "0"))
            except ValueError:
                ilvl = 0
            fmt = lvl.find(qn("w:numFmt"))
            start = lvl.find(qn("w:start"))
            levels[ilvl] = {
                "fmt": fmt.get(qn("w:val")) if fmt is not None else "decimal",
                "start": int(start.get(qn("w:val"))) if start is not None else 1,
            }
        abstracts[abstract.get(qn("w:abstractNumId"))] = levels

    mapping: Dict[int, Dict[int, Dict[str, Any]]] = {}
    for num in root.findall(qn("w:num")):
        ref = num.find(qn("w:abstractNumId"))
        if ref is None:
            continue
        num_id = num.get(qn("w:numId"))
        if num_id is None:
            continue
        mapping[int(num_id)] = abstracts.get(ref.get(qn("w:val")), {})
    return mapping


def _paragraph_numbering(paragraph, numbering: Dict[int, Dict[int, Dict[str, Any]]]):
    pPr = paragraph._p.pPr
    if pPr is None or pPr.numPr is None:
        return None
    num_pr = pPr.numPr
    num_id = num_pr.numId.val if num_pr.numId is not None else None
    if not num_id:
        return None
    ilvl = num_pr.ilvl.val if num_pr.ilvl is not None else 0
    level = (numbering.get(num_id) or {}).get(int(ilvl))
    if level is None:
        return {"fmt": "decimal", "start": 1}
    return level


def _effective_alignment(paragraph) -> Optional[str]:
    value = paragraph.alignment
    if value is None:
        try:
            value = paragraph.style.paragraph_format.alignment
        except (AttributeError, KeyError):
            value = None
    return ALIGN_TO_CSS.get(value) if value is not None else None


def _effective_indent_px(paragraph) -> Optional[float]:
    for source in (paragraph.paragraph_format, getattr(paragraph.style, "paragraph_format", None)):
        if source is None:
            continue
        try:
            indent = source.left_indent
        except (AttributeError, KeyError):
            indent = None
        if indent:
            return round(indent.emu / 914400.0 * 96.0, 1)
    return None


def _run_text(run) -> str:
    """Run text with tabs and breaks kept, which python-docx's .text drops."""
    parts: List[str] = []
    for child in run._element:
        tag = child.tag
        if tag == qn("w:t"):
            parts.append(child.text or "")
        elif tag == qn("w:tab"):
            parts.append("\t")
        elif tag in (qn("w:br"), qn("w:cr")):
            parts.append("\n")
    return "".join(parts)


def _run_format(run) -> Dict[str, Any]:
    font = run.font
    return {
        "bold": bool(run.bold),
        "italic": bool(run.italic),
        "underline": bool(run.underline),
        "strike": bool(font.strike),
        "size": font.size.pt if font.size is not None else None,
        "font": font.name,
    }


def _wrap_inline(text: str, fmt: Dict[str, Any]) -> str:
    escaped = html_escape.escape(text, quote=False)
    escaped = escaped.replace("\xa0", "&nbsp;").replace("\n", "<br/>").replace("\t", "&#9;")
    if not escaped:
        return ""
    styles: List[str] = []
    if fmt.get("size"):
        styles.append(f"font-size:{fmt['size']:g}pt")
    if fmt.get("font"):
        styles.append(f"font-family:{fmt['font']}")
    markup = escaped
    if styles:
        markup = f'<span style="{";".join(styles)}">{markup}</span>'
    if fmt.get("strike"):
        markup = f"<s>{markup}</s>"
    if fmt.get("underline"):
        markup = f"<u>{markup}</u>"
    if fmt.get("italic"):
        markup = f"<em>{markup}</em>"
    if fmt.get("bold"):
        markup = f"<strong>{markup}</strong>"
    return markup


def _paragraph_inner(paragraph) -> str:
    chunks: List[str] = []
    for run in paragraph.runs:
        text = _run_text(run)
        if not text:
            continue
        chunks.append(_wrap_inline(text, _run_format(run)))
    return "".join(chunks) or "<br/>"


def _block_attrs(index: int, align: Optional[str], indent: Optional[float]) -> str:
    styles: List[str] = []
    if align:
        styles.append(f"text-align:{align}")
    if indent:
        styles.append(f"margin-left:{indent}px")
    attrs = [f'data-idx="{index}"']
    if styles:
        attrs.append(f'style="{";".join(styles)}"')
    return " ".join(attrs)


def _is_plain_paragraph_flow(document: Document) -> bool:
    """True when the body is a flat list of paragraphs and nothing else.

    Content controls, shapes and text boxes hold paragraphs that python-docx does
    not list, so previewing such a document would silently drop text on save.
    """
    body_children = [child.tag for child in document.element.body]
    return all(tag in (qn("w:p"), qn("w:sectPr")) for tag in body_children)


def docx_to_html(path: Path) -> Dict[str, Any]:
    """Editable HTML for a .docx, or a reason the document cannot be edited."""
    document = Document(str(path))
    if document.tables:
        return {
            "editable": False,
            "reason": "This draft contains tables, which the editor cannot safely rewrite.",
            "html": "",
        }
    if not _is_plain_paragraph_flow(document):
        return {
            "editable": False,
            "reason": "This draft has embedded content the editor cannot rewrite safely.",
            "html": "",
        }

    defaults = _doc_defaults(document)
    numbering = _numbering_map(document)
    out: List[str] = []
    open_list: Optional[Tuple[str, str]] = None

    def close_list() -> None:
        nonlocal open_list
        if open_list:
            out.append(f"</{open_list[0]}>")
            open_list = None

    for index, paragraph in enumerate(document.paragraphs):
        align = _effective_alignment(paragraph)
        indent = _effective_indent_px(paragraph)
        attrs = _block_attrs(index, align, indent)
        inner = _paragraph_inner(paragraph)
        number = _paragraph_numbering(paragraph, numbering)

        if number:
            css = NUM_FMT_TO_CSS.get(number["fmt"], "decimal")
            tag = "ul" if css == "disc" else "ol"
            if open_list != (tag, css):
                close_list()
                start = f' start="{number["start"]}"' if tag == "ol" else ""
                out.append(f'<{tag}{start} data-list="{css}">')
                open_list = (tag, css)
            out.append(f"<li {attrs}>{inner}</li>")
        else:
            close_list()
            out.append(f"<p {attrs}>{inner}</p>")

    close_list()
    return {
        "editable": True,
        "html": "\n".join(out),
        "base_font": defaults.get("font") or "Times New Roman",
        "base_size": defaults.get("size") or 12.0,
    }


# ---------------------------------------------------------------------------
# Writing edits back
# ---------------------------------------------------------------------------

_STYLE_PROPERTY = re.compile(r"(?P<name>[-\w]+)\s*:\s*(?P<value>[^;]+)")


def _parse_styles(value: Optional[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    if not value:
        return parsed
    for match in _STYLE_PROPERTY.finditer(value):
        parsed[match.group("name").strip().lower()] = match.group("value").strip()
    return parsed


def _size_from(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    match = re.search(r"([\d.]+)\s*(pt|px|em)?", value.strip().lower())
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or "pt"
    if unit == "px":
        return round(number * 0.75, 1)
    if unit == "em":
        return round(number * 12.0, 1)
    return number


def _font_from(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    family = value.split(",")[0].strip().strip("\"'").title()
    return family or None


NON_DOCUMENT_TAGS = (
    "script", "style", "head", "title", "meta", "link", "noscript",
    "iframe", "object", "embed", "form", "input", "button", "svg", "math",
)


def _parse_html(html_text: str) -> ET._Element:
    """Parse the editor's markup leniently, without resolving anything external.

    The markup comes from a contenteditable region, so it is HTML: entities like
    &nbsp; and open tags like <br> are ordinary and an XML parser rejects them.
    """
    parser = LH.HTMLParser(no_network=True, huge_tree=False)
    container = LH.fragment_fromstring(
        html_text[:MAX_HTML_CHARS], create_parent="div", parser=parser
    )
    for element in list(container.iter(*NON_DOCUMENT_TAGS)):
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)
    return container


def _local_tag(node) -> str:
    tag = getattr(node, "tag", None)
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


class _Format:
    """Inline formatting inherited from the enclosing tags."""

    __slots__ = ("bold", "italic", "underline", "strike", "size", "font")

    def __init__(self, bold=False, italic=False, underline=False, strike=False,
                 size=None, font=None):
        self.bold = bold
        self.italic = italic
        self.underline = underline
        self.strike = strike
        self.size = size
        self.font = font

    def inherit(self, **changes) -> "_Format":
        return _Format(
            bold=changes.get("bold", self.bold),
            italic=changes.get("italic", self.italic),
            underline=changes.get("underline", self.underline),
            strike=changes.get("strike", self.strike),
            size=changes.get("size", self.size),
            font=changes.get("font", self.font),
        )


def _inline_format(node, fmt: _Format) -> _Format:
    tag = _local_tag(node)
    if tag in ("strong", "b"):
        fmt = fmt.inherit(bold=True)
    elif tag in ("em", "i"):
        fmt = fmt.inherit(italic=True)
    elif tag in ("u", "ins"):
        fmt = fmt.inherit(underline=True)
    elif tag in ("s", "strike", "del"):
        fmt = fmt.inherit(strike=True)
    elif tag == "font" and node.get("size"):
        try:
            fmt = fmt.inherit(size=HTML_FONT_SIZES.get(int(node.get("size")), fmt.size))
        except ValueError:
            pass
    styles = _parse_styles(node.get("style"))
    if "font-size" in styles:
        size = _size_from(styles["font-size"])
        if size:
            fmt = fmt.inherit(size=size)
    if "font-family" in styles:
        family = _font_from(styles["font-family"])
        if family:
            fmt = fmt.inherit(font=family)
    return fmt


def _append_text(target: List[Tuple[str, _Format]], text: Optional[str], fmt: _Format) -> None:
    """Literal text from the editor, kept verbatim: python-docx maps tabs and
    newlines to <w:tab/> and <w:br/>, and &nbsp; arrives as U+00A0."""
    if text:
        target.append((text.replace("\r\n", "\n").replace("\r", "\n"), fmt))


def _collect_inline(node, fmt: _Format, target: List[Tuple[str, _Format]]) -> None:
    """Depth-first walk so nested tags keep their inherited formatting.

    An element's own text carries that element's formatting; the text after it
    (its tail) belongs to the parent again.
    """
    for child in node:
        child_fmt = _inline_format(child, fmt)
        if _local_tag(child) == "br":
            target.append(("\n", child_fmt))
        else:
            _append_text(target, child.text, child_fmt)
            _collect_inline(child, child_fmt, target)
        _append_text(target, child.tail, fmt)


def _paragraph_texts(node, fmt: _Format) -> List[Tuple[str, _Format]]:
    target: List[Tuple[str, _Format]] = []
    _append_text(target, node.text, fmt)
    _collect_inline(node, fmt, target)
    return target


def _detach_runs(element) -> None:
    for child in list(element):
        if child.tag in RUN_TAGS:
            element.remove(child)


def _write_runs(paragraph, pieces: List[Tuple[str, _Format]]) -> None:
    wrote = False
    for text, fmt in pieces:
        run = paragraph.add_run(text)
        run.bold = fmt.bold or None
        run.italic = fmt.italic or None
        run.underline = True if fmt.underline else None
        run.font.strike = fmt.strike or None
        if fmt.size:
            run.font.size = Pt(fmt.size)
        if fmt.font:
            run.font.name = fmt.font
        wrote = True
    if not wrote:
        paragraph.add_run("")


def _set_alignment(paragraph, css_align: Optional[str]) -> None:
    if css_align in CSS_TO_ALIGN:
        paragraph.alignment = CSS_TO_ALIGN[css_align]
    elif css_align:
        paragraph.alignment = None


def _index_of(node) -> Optional[int]:
    raw = node.get("data-idx")
    if raw and raw.isdigit():
        return int(raw)
    return None


def _blocks_of(container) -> Tuple[List[Any], Set[int]]:
    """Outermost editable blocks in order, plus every paragraph index present.

    Indexes are collected from anywhere in the tree, not only from the blocks we
    rewrite, so markup the browser nested can never delete a paragraph.
    """
    mentioned: Set[int] = set()
    blocks: List[Any] = []
    for node in container.iter():
        index = _index_of(node)
        if index is not None:
            mentioned.add(index)
        if node is container or _local_tag(node) not in BLOCK_TAGS:
            continue
        if any(
            parent is not container and _local_tag(parent) in BLOCK_TAGS
            for parent in node.iterancestors()
        ):
            continue
        blocks.append(node)
    return blocks, mentioned


def write_revision(
    html_text: str,
    source_path: Path,
    output_dir: Path,
    session_id: str,
    template_name: str = "",
) -> Dict[str, Any]:
    """Rebuild paragraphs from the edited HTML into a new .docx revision.

    Each block carries the index of the paragraph it came from, so the original
    paragraph element — and with it the template style, numbering and spacing —
    is kept and only its runs are replaced.
    """
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"Generated document '{source.name}' is missing.")

    document = Document(str(source))
    paragraphs = list(document.paragraphs)

    container = _parse_html(html_text)
    blocks, mentioned = _blocks_of(container)
    if not mentioned:
        raise ValueError("The edited document lost its paragraph references.")

    written = 0
    added = 0
    used: Set[int] = set()
    cursor: Optional[ET._Element] = None
    donor = paragraphs[0]._p if paragraphs else None

    for node in blocks:
        styles = _parse_styles(node.get("style"))
        fmt = _Format(size=_size_from(styles.get("font-size")), font=_font_from(styles.get("font-family")))
        pieces = _paragraph_texts(node, fmt)
        index = _index_of(node)

        if index is not None and index < len(paragraphs) and index not in used:
            used.add(index)
            paragraph = paragraphs[index]
            _detach_runs(paragraph._p)
            _write_runs(paragraph, pieces)
            _set_alignment(paragraph, styles.get("text-align"))
            cursor = paragraph._p
            written += 1
            continue

        # A paragraph the lawyer typed in (or a repeated reference): borrow the
        # layout of the paragraph before it and insert a copy right after it.
        neighbour = cursor if cursor is not None else donor
        if neighbour is None:
            continue
        new_element = copy.deepcopy(neighbour)
        _detach_runs(new_element)
        neighbour.addnext(new_element)
        cursor = new_element
        added += 1
        paragraph = Paragraph(new_element, None)
        _write_runs(paragraph, pieces)
        _set_alignment(paragraph, styles.get("text-align"))

    # Paragraphs removed in the editor are dropped from this revision only.
    for offset, paragraph in enumerate(paragraphs):
        if offset in mentioned:
            continue
        element = paragraph._p
        if element.getparent() is not None:
            element.getparent().remove(element)

    stem = Path(template_name).stem.replace(" ", "_") if template_name else source.stem
    safe_session = "".join(
        char for char in session_id if char.isalnum() or char in ("-", "_")
    )[:60] or "case"
    filename = (
        f"{stem[:60]}_edited_{safe_session}_"
        f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}.docx"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    document.save(str(output_path))
    return {
        "file_path": str(output_path),
        "filename": filename,
        "download_url": f"/sessions/{quote(safe_session)}/download/{quote(filename)}",
        "paragraphs_written": written,
        "paragraphs_added": added,
    }
