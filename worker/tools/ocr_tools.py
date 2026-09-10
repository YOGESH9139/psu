"""OCR + vision tools. Tesseract and Ollama are both local; nothing leaves the host."""
from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, Dict, List

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.model_registry import registry
from worker.tools.path_utils import PathPolicyError, relative_to_workspace, validate_path

logger = logging.getLogger("sovereign.tools.ocr")

RENDER_DPI = 150
LOW_CONFIDENCE_THRESHOLD = 60.0
VISION_MODEL_ID = "qwen25vl-7b"

# A 150 DPI A4 page is ~1240x1754. Sent whole, that is thousands of vision
# tokens and, on an 8 GB card where the VL model is already partly offloaded to
# CPU, a single description took 220 s. Tesseract has already read the text; the
# vision pass is for the photograph, stamps and handwriting, which survive a
# downscale. Measured: ~35 s at 1024 px with no loss of the details we use.
VISION_MAX_EDGE_PX = 1024
VISION_MAX_TOKENS = 400


def _encode_for_vision(img_path: Path) -> tuple[str, list[int]]:
    """Base64 the image, downscaled so the vision model stays responsive."""
    import io

    from PIL import Image

    with Image.open(img_path) as img:
        img = img.convert("RGB")
        if max(img.size) > VISION_MAX_EDGE_PX:
            scale = VISION_MAX_EDGE_PX / max(img.size)
            img = img.resize(
                (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                Image.LANCZOS,
            )
        buffer = io.BytesIO()
        img.save(buffer, "JPEG", quality=85)
        size = list(img.size)

    return base64.b64encode(buffer.getvalue()).decode("ascii"), size


class ExtractPdfInput(BaseModel):
    file_path: str = Field(..., description="Workspace-relative path to the PDF, e.g. inputs/report.pdf")
    run_id: str = Field(..., description="Run ID")


class RunOcrInput(BaseModel):
    image_path: str = Field(..., description="Workspace-relative path to a page PNG/JPEG")
    run_id: str = Field(..., description="Run ID")


class InspectImageInput(BaseModel):
    image_path: str = Field(..., description="Workspace-relative path to the image to inspect")
    run_id: str = Field(..., description="Run ID")
    prompt: str = Field(
        "Describe this document page. List any equipment shown, visible defects, "
        "stamps, and handwritten annotations. Be specific and factual.",
        description="Instruction for the local vision model",
    )


@tool("extract_pdf_pages", args_schema=ExtractPdfInput)
def extract_pdf_pages(file_path: str, run_id: str) -> Dict[str, Any]:
    """Render each page of a local PDF to a PNG at 150 DPI inside the run workspace."""
    try:
        pdf = validate_path(file_path, run_id)
    except PathPolicyError as e:
        return {"status": "rejected", "error": str(e), "pages": []}

    if not pdf.exists():
        return {"status": "error", "error": f"PDF not found: {file_path}", "pages": []}

    out_dir = validate_path(Path("pages") / pdf.stem, run_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        import pymupdf
    except ImportError as e:
        return {"status": "error", "error": f"PyMuPDF unavailable: {e}", "pages": []}

    pages: List[Dict[str, Any]] = []
    try:
        with pymupdf.open(str(pdf)) as doc:
            for idx, page in enumerate(doc, start=1):
                img_path = out_dir / f"page_{idx}.png"
                page.get_pixmap(dpi=RENDER_DPI).save(str(img_path))
                # Embedded text layer, when the PDF has one (born-digital pages).
                embedded = page.get_text().strip()
                pages.append({
                    "page_number": idx,
                    "image_path": relative_to_workspace(img_path, run_id),
                    "has_text_layer": bool(embedded),
                    "embedded_text_chars": len(embedded),
                })
    except Exception as e:
        return {"status": "error", "error": f"PDF rendering failed: {e}", "pages": pages}

    return {
        "status": "success",
        "source_file": pdf.name,
        "page_count": len(pages),
        "pages": pages,
    }


@tool("run_ocr", args_schema=RunOcrInput)
def run_ocr(image_path: str, run_id: str) -> Dict[str, Any]:
    """Run local Tesseract OCR on a page image; returns text, per-word confidence
    and the low-confidence regions worth a second look from the vision model."""
    try:
        img_path = validate_path(image_path, run_id)
    except PathPolicyError as e:
        return {"status": "rejected", "error": str(e), "text": "", "confidence": 0.0}

    if not img_path.exists():
        return {"status": "error", "error": f"Image not found: {image_path}",
                "text": "", "confidence": 0.0, "word_count": 0}

    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:
        return {"status": "error", "error": f"OCR stack unavailable: {e}",
                "text": "", "confidence": 0.0, "word_count": 0}

    try:
        with Image.open(img_path) as img:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    except Exception as e:
        return {"status": "error", "error": f"Tesseract failed: {e}",
                "text": "", "confidence": 0.0, "word_count": 0}

    words: List[str] = []
    confidences: List[float] = []
    low_conf_words: List[Dict[str, Any]] = []

    for i, raw_word in enumerate(data["text"]):
        word = (raw_word or "").strip()
        if not word:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        words.append(word)
        if conf >= 0:
            confidences.append(conf)
            if conf < LOW_CONFIDENCE_THRESHOLD:
                low_conf_words.append({
                    "word": word,
                    "confidence": conf,
                    "bbox": [data["left"][i], data["top"][i], data["width"][i], data["height"][i]],
                })

    avg_conf = round(sum(confidences) / len(confidences), 2) if confidences else 0.0

    # Page number is encoded in the rendered filename (page_3.png).
    page_number = None
    stem = img_path.stem
    if stem.startswith("page_") and stem[5:].isdigit():
        page_number = int(stem[5:])

    return {
        "status": "success",
        "source_file": img_path.parent.name,
        "image_path": relative_to_workspace(img_path, run_id),
        "page_number": page_number,
        "text": " ".join(words),
        "confidence": avg_conf,
        "word_count": len(words),
        "low_confidence_word_count": len(low_conf_words),
        "low_confidence_sample": low_conf_words[:10],
        "needs_vision_review": avg_conf < LOW_CONFIDENCE_THRESHOLD or bool(low_conf_words),
    }


@tool("inspect_image", args_schema=InspectImageInput)
def inspect_image(image_path: str, run_id: str, prompt: str = "") -> Dict[str, Any]:
    """Send a page image to the local vision model (Ollama) for visual analysis."""
    try:
        img_path = validate_path(image_path, run_id)
    except PathPolicyError as e:
        return {"status": "rejected", "error": str(e), "description": ""}

    if not img_path.exists():
        return {"status": "error", "error": f"Image not found: {image_path}", "description": ""}

    model = registry.get_model(VISION_MODEL_ID)
    if model is None:
        return {"status": "error", "error": f"Vision model {VISION_MODEL_ID} not in registry",
                "description": ""}

    prompt = prompt or InspectImageInput.model_fields["prompt"].default
    encoded, sent_size = _encode_for_vision(img_path)

    try:
        with httpx.Client(timeout=300.0) as client:
            resp = client.post(
                f"{settings.ollama_url}/api/generate",
                json={
                    "model": model.ollama_model,
                    "prompt": prompt,
                    "images": [encoded],
                    "stream": False,
                    "keep_alive": model.keep_alive,
                    "options": {
                        "num_ctx": model.num_ctx,
                        "num_predict": VISION_MAX_TOKENS,
                    },
                },
            )
            resp.raise_for_status()
            description = (resp.json().get("response") or "").strip()
    except Exception as e:
        logger.warning("Vision inspection failed for %s: %s", img_path, e)
        return {
            "status": "error",
            "error": f"Local vision model unavailable: {e}",
            "image_path": relative_to_workspace(img_path, run_id),
            "description": "",
        }

    lowered = description.lower()
    anomaly_terms = ("corros", "crack", "fracture", "leak", "rust", "pitting",
                     "damage", "defect", "anomal", "wear", "deform")

    return {
        "status": "success",
        "model": model.ollama_model,
        "image_path": relative_to_workspace(img_path, run_id),
        "image_sent_px": sent_size,
        "description": description,
        "anomalies_found": any(t in lowered for t in anomaly_terms),
        "anomaly_terms_seen": [t for t in anomaly_terms if t in lowered],
    }
