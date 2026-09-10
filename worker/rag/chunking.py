"""Document -> page-aware, clause-aware chunks.

Page numbers survive all the way to the citation in the generated approval note,
so every chunk carries `source_file` and `page_number` from the moment it is cut.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

logger = logging.getLogger("sovereign.rag.chunking")

TARGET_CHARS = 900
OVERLAP_CHARS = 150
MIN_CHUNK_CHARS = 60
OCR_FALLBACK_MIN_CHARS = 40  # below this, a PDF page is treated as scanned

# "4.2 Escalation", "SECTION 3 -", "CLAUSE 802-A:" etc.
HEADING_RE = re.compile(
    r"^\s*((?:SECTION|CLAUSE|APPENDIX|ANNEX|PART)\s+[\w.\-]+|\d+(?:\.\d+)*)\s*[.\-:)]?\s+(\S.{0,80})$",
    re.IGNORECASE,
)


def _paragraphs(text: str) -> List[str]:
    """Break text into logical blocks.

    Blank lines are the natural boundary, but PDF text extraction usually emits
    single newlines only, which would leave a whole procedure as one block. So
    when blank-line splitting produces oversized blocks, split again at numbered
    clause headings — exactly the boundary a citation should land on.
    """
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if not blocks:
        return []

    out: List[str] = []
    for block in blocks:
        if len(block) <= TARGET_CHARS:
            out.append(block)
            continue

        current: List[str] = []
        for line in block.splitlines():
            if HEADING_RE.match(line) and current:
                out.append("\n".join(current).strip())
                current = [line]
            else:
                current.append(line)
        if current:
            out.append("\n".join(current).strip())

    return [b for b in out if b.strip()]


def _hard_split(text: str) -> List[str]:
    """Last resort for a block with no internal structure: split on sentence
    boundaries, then on raw length, so nothing exceeds TARGET_CHARS."""
    if len(text) <= TARGET_CHARS:
        return [text]

    pieces: List[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if current and len(current) + len(sentence) + 1 > TARGET_CHARS:
            pieces.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current.strip():
        pieces.append(current.strip())

    final: List[str] = []
    for piece in pieces:
        while len(piece) > TARGET_CHARS:
            final.append(piece[:TARGET_CHARS])
            piece = piece[TARGET_CHARS - OVERLAP_CHARS:]
        if piece.strip():
            final.append(piece.strip())
    return final


def _split_with_overlap(text: str) -> List[str]:
    """Pack logical blocks up to TARGET_CHARS, carrying an overlap across cuts."""
    blocks = _paragraphs(text)
    if not blocks:
        return []

    chunks: List[str] = []
    current = ""
    for block in blocks:
        if len(block) > TARGET_CHARS:
            if current.strip():
                chunks.append(current.strip())
                current = ""
            chunks.extend(_hard_split(block))
            continue

        if current and len(current) + len(block) + 2 > TARGET_CHARS:
            chunks.append(current.strip())
            tail = current[-OVERLAP_CHARS:] if len(current) > OVERLAP_CHARS else current
            current = f"{tail}\n\n{block}"
        else:
            current = f"{current}\n\n{block}" if current else block

    if current.strip():
        chunks.append(current.strip())
    return chunks


def _heading_for(text: str) -> str | None:
    for line in text.splitlines()[:6]:
        match = HEADING_RE.match(line)
        if match:
            return f"{match.group(1)} {match.group(2)}".strip()
    return None


def chunk_pages(pages: Iterable[Dict[str, Any]], source_file: str) -> List[Dict[str, Any]]:
    """pages: [{page_number, text}] -> [{text, source_file, page_number, heading}]"""
    out: List[Dict[str, Any]] = []
    for page in pages:
        text = (page.get("text") or "").strip()
        if len(text) < MIN_CHUNK_CHARS:
            continue
        for piece in _split_with_overlap(text):
            if len(piece) < MIN_CHUNK_CHARS:
                continue
            out.append({
                "text": piece,
                "source_file": source_file,
                "page_number": page.get("page_number"),
                "heading": _heading_for(piece),
            })
    return out


def extract_pdf_text_pages(path: Path, ocr_if_needed: bool = True) -> List[Dict[str, Any]]:
    """Per-page text from a PDF. Falls back to local Tesseract OCR on scanned pages."""
    import pymupdf

    pages: List[Dict[str, Any]] = []
    with pymupdf.open(str(path)) as doc:
        for idx, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            method = "text_layer"
            if len(text) < OCR_FALLBACK_MIN_CHARS and ocr_if_needed:
                ocr_text = _ocr_page(page)
                if len(ocr_text) > len(text):
                    text, method = ocr_text, "tesseract_ocr"
            pages.append({"page_number": idx, "text": text, "extraction_method": method})
    return pages


def _ocr_page(page: Any) -> str:
    try:
        import io

        import pytesseract
        from PIL import Image

        pix = page.get_pixmap(dpi=200)
        with Image.open(io.BytesIO(pix.tobytes("png"))) as img:
            return pytesseract.image_to_string(img).strip()
    except Exception as e:
        logger.warning("OCR fallback failed on page: %s", e)
        return ""


def extract_text_pages(path: Path, mime_type: str | None = None) -> List[Dict[str, Any]]:
    """Page-wise text for any supported knowledge-base source document."""
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return extract_pdf_text_pages(path)

    if suffix == ".docx":
        import docx

        doc = docx.Document(str(path))
        body = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        return [{"page_number": 1, "text": body, "extraction_method": "docx"}]

    if suffix in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"):
        import pytesseract
        from PIL import Image

        with Image.open(path) as img:
            return [{
                "page_number": 1,
                "text": pytesseract.image_to_string(img).strip(),
                "extraction_method": "tesseract_ocr",
            }]

    # .txt, .md, .csv and anything else textual
    text = path.read_text(encoding="utf-8", errors="replace")
    return [{"page_number": 1, "text": text, "extraction_method": "plain_text"}]
