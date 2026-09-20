"""Deterministic model router — pure signal matching, no LLM call, no network.

Scoring is intentionally simple and explainable, because the router decision is
shown to the user (and to judges) before the agent takes a single step:

  * A recognised MIME type or file extension is an unambiguous signal  -> 0.80
  * Both agreeing adds a little more                                   -> +0.05
  * Each supporting keyword phrase adds a little more (max 2)          -> +0.05
  * With no file at all, keywords alone can carry a class              -> 0.35 + 0.15/hit
  * Nothing matched -> general-reasoning, flagged as a fallback
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

MULTIMODAL = "multimodal-document"
CODING = "coding"
SPREADSHEET = "spreadsheet-analysis"
GENERAL = "general-reasoning"

# Highest priority first — used only to break exact score ties.
TASK_PRIORITY = [CODING, SPREADSHEET, MULTIMODAL, GENERAL]

MIME_TO_TASK: dict[str, str] = {
    "application/pdf": MULTIMODAL,
    "image/png": MULTIMODAL,
    "image/jpeg": MULTIMODAL,
    "image/tiff": MULTIMODAL,
    "image/webp": MULTIMODAL,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": SPREADSHEET,
    "application/vnd.ms-excel": SPREADSHEET,
    "text/csv": SPREADSHEET,
    "text/x-python": CODING,
    "text/x-script.python": CODING,
    "application/x-python-code": CODING,
    "text/javascript": CODING,
    "application/javascript": CODING,
}

EXT_TO_TASK: dict[str, str] = {
    ".py": CODING,
    ".js": CODING,
    ".ts": CODING,
    ".sh": CODING,
    ".go": CODING,
    ".rs": CODING,
    ".cpp": CODING,
    ".java": CODING,
    ".xlsx": SPREADSHEET,
    ".xls": SPREADSHEET,
    ".csv": SPREADSHEET,
    ".pdf": MULTIMODAL,
    ".png": MULTIMODAL,
    ".jpg": MULTIMODAL,
    ".jpeg": MULTIMODAL,
    ".tif": MULTIMODAL,
    ".tiff": MULTIMODAL,
}

# Each entry is (human-readable label, compiled pattern).
KEYWORD_PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    CODING: [
        (
            "write/implement code",
            re.compile(r"\b(write|implement|generate|create)\b[^.]{0,30}\b(code|function|script|program|class|module)\b"),
        ),
        (
            "debug/fix/refactor",
            re.compile(r"\b(debug|fix|repair|refactor|patch)\b[^.]{0,30}\b(code|bug|function|script|test|error)\b"),
        ),
        ("run unit tests", re.compile(r"\b(unit test|pytest|unittest|test suite|run the tests)\b")),
    ],
    MULTIMODAL: [
        (
            "inspection/scan/OCR",
            re.compile(r"\b(ocr|scanned|scan|inspection|inspect|corrosion|weld|drawing|p&id|photograph|handwritten)\b"),
        ),
        (
            "read/review a document",
            re.compile(r"\b(read|review|analyse|analyze|extract|summarise|summarize)\b[^.]{0,30}\b(report|document|pdf|page|image|drawing|scan)\b"),
        ),
        ("approval note", re.compile(r"\b(approval note|approval memo|sign-?off note)\b")),
    ],
    SPREADSHEET: [
        (
            "threshold / exceed readings",
            re.compile(r"\b(threshold|exceeds?|exceeding|out of range|tolerance)\b"),
        ),
        (
            "spreadsheet vocabulary",
            re.compile(r"\b(spreadsheet|worksheet|workbook|xlsx|csv|column|row|cell)\b"),
        ),
        (
            "aggregate a dataset",
            re.compile(r"\b(average|mean|median|sum|total|max|min|count)\b[^.]{0,30}\b(column|row|reading|value|data)\b"),
        ),
    ],
}

TASK_TO_MODEL: dict[str, str] = {
    MULTIMODAL: "qwen25vl-7b",
    CODING: "qwen3-8b",
    SPREADSHEET: "qwen3-8b",
    GENERAL: "qwen3-8b",
}

FILE_SIGNAL_SCORE = 0.80
BOTH_SIGNALS_BONUS = 0.05
KEYWORD_SUPPORT_BONUS = 0.05
KEYWORD_ONLY_BASE = 0.35
KEYWORD_ONLY_PER_HIT = 0.15
MAX_KEYWORD_HITS = 2
GENERAL_BASELINE = 0.25
GENERAL_FALLBACK_CONFIDENCE = 0.80


class RouterDecision:
    def __init__(
        self,
        task_class: str,
        model_id: str,
        confidence: float,
        matched_signals: list[str],
        fallback: bool = False,
    ) -> None:
        self.task_class = task_class
        self.model_id = model_id
        self.confidence = round(min(confidence, 1.0), 3)
        self.matched_signals = matched_signals
        self.fallback = fallback

    def to_dict(self) -> dict[str, Any]:
        # snake_case is the primary contract; camelCase aliases match plan.md.
        return {
            "task_class": self.task_class,
            "model_id": self.model_id,
            "confidence": self.confidence,
            "matched_signals": self.matched_signals,
            "fallback": self.fallback,
            "taskClass": self.task_class,
            "modelId": self.model_id,
            "matchedSignals": self.matched_signals,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<RouterDecision {self.task_class} -> {self.model_id} @ {self.confidence}>"


def route(
    goal: str,
    file_mimes: list[str] | None = None,
    file_names: list[str] | None = None,
) -> RouterDecision:
    """Pure deterministic routing — no LLM, no network call."""
    mime_hits: dict[str, list[str]] = {}
    ext_hits: dict[str, list[str]] = {}
    kw_hits: dict[str, list[str]] = {}

    for mime in file_mimes or []:
        task = MIME_TO_TASK.get(mime)
        if task:
            mime_hits.setdefault(task, []).append(f"mime:{mime}")

    for name in file_names or []:
        ext = Path(name).suffix.lower()
        task = EXT_TO_TASK.get(ext)
        if task:
            ext_hits.setdefault(task, []).append(f"ext:{ext}")

    goal_lower = goal.lower()
    for task, patterns in KEYWORD_PATTERNS.items():
        for label, pattern in patterns:
            if pattern.search(goal_lower):
                kw_hits.setdefault(task, []).append(f"keyword:{label}")

    scores: dict[str, float] = {GENERAL: GENERAL_BASELINE}
    for task in (CODING, SPREADSHEET, MULTIMODAL):
        has_mime = task in mime_hits
        has_ext = task in ext_hits
        n_kw = min(len(kw_hits.get(task, [])), MAX_KEYWORD_HITS)

        if has_mime or has_ext:
            score = FILE_SIGNAL_SCORE
            if has_mime and has_ext:
                score += BOTH_SIGNALS_BONUS
            score += KEYWORD_SUPPORT_BONUS * n_kw
        elif n_kw:
            score = KEYWORD_ONLY_BASE + KEYWORD_ONLY_PER_HIT * n_kw
        else:
            score = 0.0
        scores[task] = min(score, 1.0)

    best_task = max(
        scores,
        key=lambda t: (scores[t], -TASK_PRIORITY.index(t)),
    )

    signals: list[str] = (
        mime_hits.get(best_task, [])
        + ext_hits.get(best_task, [])
        + kw_hits.get(best_task, [])
    )

    if best_task == GENERAL:
        # A plain prompt with no file and no domain keywords genuinely IS general
        # reasoning — say so with confidence, but flag it as the fallback branch.
        return RouterDecision(
            task_class=GENERAL,
            model_id=TASK_TO_MODEL[GENERAL],
            confidence=GENERAL_FALLBACK_CONFIDENCE,
            matched_signals=signals or ["no file signals, no domain keywords"],
            fallback=True,
        )

    return RouterDecision(
        task_class=best_task,
        model_id=TASK_TO_MODEL[best_task],
        confidence=scores[best_task],
        matched_signals=signals,
        fallback=False,
    )


class ModelRouter:
    """Thin object wrapper kept for call sites that prefer a class."""

    @staticmethod
    def route(
        goal: str,
        mime_type: str | None = None,
        file_mimes: list[str] | None = None,
        file_names: list[str] | None = None,
    ) -> dict[str, Any]:
        mimes = list(file_mimes or [])
        if mime_type:
            mimes.append(mime_type)
        return route(goal=goal, file_mimes=mimes, file_names=file_names).to_dict()


model_router = ModelRouter()


_DELIVERABLE_RE = re.compile(r"(draft|note|report|memo|approval|document|docx|word)")


def route_followup(goal, file_mimes=None, file_names=None):
    """A follow-up like "now show it as a table" is a conversation turn, not a new
    document job. Only look at the attached files when the operator explicitly
    asks for a deliverable again."""
    if _DELIVERABLE_RE.search((goal or "").lower()):
        return route(goal, file_mimes, file_names)
    return route(goal, [], [])
