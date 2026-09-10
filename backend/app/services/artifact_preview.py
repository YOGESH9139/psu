"""Structured, renderable preview of a generated artifact.

The browser cannot display a .docx, and a download-only deliverable forces the
reviewer out of the workbench to see what they are approving. This turns an
artifact into an ordered block list the UI can lay out as a document page.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("sovereign.preview")

MAX_TEXT_BYTES = 256 * 1024
MAX_BLOCKS = 400

TEXT_SUFFIXES = {".py", ".txt", ".md", ".json", ".csv", ".sh", ".cfg", ".ini", ".toml"}
LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".sh": "bash",
    ".json": "json",
    ".md": "markdown",
    ".csv": "csv",
}


def preview_artifact(path: Path, filename: str) -> dict[str, Any]:
    """-> {kind, blocks|content, ...}. Never raises; reports its own failure."""
    suffix = path.suffix.lower()

    if suffix == ".docx":
        return _preview_docx(path, filename)
    if suffix in TEXT_SUFFIXES:
        return _preview_text(path, filename, suffix)

    return {
        "kind": "unsupported",
        "filename": filename,
        "message": f"No inline preview for {suffix or 'this file type'}. "
                   f"Download it to open in the right application.",
    }


def _preview_text(path: Path, filename: str, suffix: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()[:MAX_TEXT_BYTES]
        content = raw.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("Text preview failed for %s: %s", path, e)
        return {"kind": "error", "filename": filename, "message": str(e)}

    return {
        "kind": "text",
        "filename": filename,
        "language": LANGUAGE_BY_SUFFIX.get(suffix, "text"),
        "content": content,
        "line_count": content.count("\n") + 1,
        "truncated": path.stat().st_size > MAX_TEXT_BYTES,
    }


def _preview_docx(path: Path, filename: str) -> dict[str, Any]:
    try:
        import docx
        from docx.document import Document as DocxDocument
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as e:
        return {"kind": "error", "filename": filename,
                "message": f"python-docx unavailable: {e}"}

    try:
        document = docx.Document(str(path))
    except Exception as e:
        logger.warning("DOCX preview failed for %s: %s", path, e)
        return {"kind": "error", "filename": filename,
                "message": f"Not a readable DOCX: {e}"}

    def iter_body(parent: DocxDocument):
        """Paragraphs and tables in the order they appear in the document."""
        body = parent.element.body
        for child in body.iterchildren():
            if child.tag == qn("w:p"):
                yield Paragraph(child, parent)
            elif child.tag == qn("w:tbl"):
                yield Table(child, parent)

    blocks: list[dict[str, Any]] = []
    for item in iter_body(document):
        if len(blocks) >= MAX_BLOCKS:
            break

        if isinstance(item, Paragraph):
            text = item.text.strip()
            if not text:
                continue
            style = item.style.name if item.style is not None else ""
            if style.startswith("Title"):
                blocks.append({"type": "title", "text": text})
            elif style.startswith("Heading"):
                level = "".join(c for c in style if c.isdigit())
                blocks.append({"type": "heading", "level": int(level or 1), "text": text})
            elif style.startswith("List"):
                blocks.append({"type": "bullet", "text": text})
            else:
                blocks.append({"type": "paragraph", "text": text})
            continue

        rows = [[cell.text.strip() for cell in row.cells] for row in item.rows]
        rows = [r for r in rows if any(c for c in r)]
        if not rows:
            continue
        # A two-column table with no repeated header reads as a key/value block;
        # anything wider is a real table with a header row.
        if len(rows[0]) == 2 and len(rows) > 1:
            blocks.append({"type": "fields", "rows": rows})
        else:
            blocks.append({"type": "table", "header": rows[0], "rows": rows[1:]})

    return {
        "kind": "document",
        "filename": filename,
        "blocks": blocks,
        "block_count": len(blocks),
        "truncated": len(blocks) >= MAX_BLOCKS,
    }
