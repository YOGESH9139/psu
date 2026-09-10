"""Deliverable generation/verification and chunk metadata integrity."""
from __future__ import annotations

from pathlib import Path

import pytest

from worker.rag.chunking import chunk_pages, _split_with_overlap
from worker.tools.docx_tools import (
    MANDATORY_HEADINGS,
    create_approval_docx,
    stamp_human_decision,
    verify_docx,
)
from worker.tools.path_utils import run_workspace

RUN_ID = "docx-test-run"

FINDINGS = [
    {"item": "Elbow E-07", "detail": "Maximum wall loss of 2.7 mm at grid point G-06",
     "severity": "High", "evidence": "OCR page 2"},
]
CLAUSES = [
    {"clause": "corrosion_sop §3.4", "content": "Wall loss exceeding 2.0 mm is recorded as ESCALATE.",
     "source_file": "corrosion_sop.pdf", "page_number": 1},
    {"clause": "corrosion_sop §4.1", "content": "An ESCALATE finding is referred to an integrity engineer.",
     "source_file": "corrosion_sop.pdf", "page_number": 2},
]


def _build(filename="approval_note.docx", clauses=CLAUSES, findings=FINDINGS):
    return create_approval_docx.invoke({
        "output_filename": filename,
        "purpose": "Support an engineer's decision on elbow E-07.",
        "source_metadata": {"source_file": "inspection_report.pdf", "run_id": RUN_ID},
        "findings": findings,
        "sop_clauses": clauses,
        "recommended_action": "Refer to an authorized integrity engineer for assessment.",
        "run_id": RUN_ID,
    })


class TestApprovalNote:
    def test_generation_produces_a_readable_file(self):
        result = _build()
        assert result["status"] == "success"
        assert result["file_size"] > 5 * 1024

    def test_verification_passes_on_a_complete_note(self):
        _build()
        verdict = verify_docx.invoke({"docx_path": "artifacts/approval_note.docx", "run_id": RUN_ID})
        assert verdict["valid"], verdict.get("reason")
        assert verdict["citation_count"] >= 2
        assert not verdict["missing_headings"]

    def test_every_mandatory_heading_is_present(self):
        _build()
        verdict = verify_docx.invoke({"docx_path": "artifacts/approval_note.docx", "run_id": RUN_ID})
        for heading in MANDATORY_HEADINGS:
            assert any(heading.lower() in found.lower() for found in verdict["headings_found"]), heading

    def test_a_note_without_enough_citations_fails_verification(self):
        _build("thin_note.docx", clauses=CLAUSES[:1])
        verdict = verify_docx.invoke({"docx_path": "artifacts/thin_note.docx", "run_id": RUN_ID})
        assert verdict["valid"] is False
        assert "citation" in verdict["reason"].lower()

    def test_a_note_with_no_citations_fails_verification(self):
        _build("uncited_note.docx", clauses=[])
        verdict = verify_docx.invoke({"docx_path": "artifacts/uncited_note.docx", "run_id": RUN_ID})
        assert verdict["valid"] is False

    def test_verification_reports_a_missing_file_rather_than_crashing(self):
        verdict = verify_docx.invoke({"docx_path": "artifacts/nope.docx", "run_id": RUN_ID})
        assert verdict["valid"] is False
        assert "exist" in verdict["reason"].lower()

    def test_a_fresh_note_is_unsigned_until_a_human_decides(self):
        import docx

        result = _build("pending_note.docx")
        document = docx.Document(result["absolute_path"])
        text = "\n".join(p.text for p in document.paragraphs)
        assert "Status: PENDING" in text
        assert "no human decision has been recorded" in text.lower()

    def test_the_recorded_decision_is_stamped_into_the_note(self):
        import docx

        result = _build("decided_note.docx")
        stamped = stamp_human_decision(result["absolute_path"], "approve", "checked on site")
        assert stamped["status"] == "success"

        document = docx.Document(result["absolute_path"])
        text = "\n".join(p.text for p in document.paragraphs)
        assert "Status: APPROVE" in text
        assert "checked on site" in text
        assert "Status: PENDING" not in text

    def test_the_risk_notice_never_claims_certification(self):
        import docx

        result = _build("risk_note.docx")
        text = "\n".join(p.text for p in docx.Document(result["absolute_path"]).paragraphs).lower()
        assert "not an engineering certification" in text
        assert "requires authorized engineer approval" in text

    def test_output_filename_cannot_escape_the_workspace(self):
        result = _build("../../escape.docx")
        assert result["status"] == "success"  # the directory component is stripped
        written = Path(result["absolute_path"])
        assert written.is_relative_to(run_workspace(RUN_ID) / "artifacts")
        assert written.name == "escape.docx"


class TestChunkMetadata:
    def test_page_numbers_survive_chunking(self):
        pages = [
            {"page_number": 1, "text": "1. PURPOSE\n" + "Alpha clause text. " * 60},
            {"page_number": 2, "text": "4. ESCALATION\n" + "Beta clause text. " * 60},
        ]
        chunks = chunk_pages(pages, "sop.pdf")
        assert chunks
        assert {c["page_number"] for c in chunks} == {1, 2}
        assert all(c["source_file"] == "sop.pdf" for c in chunks)

    def test_an_oversized_block_is_split_not_kept_whole(self):
        # A PDF text layer arrives as single newlines, with no blank lines at all.
        body = "\n".join(f"{i}.1 Clause {i} " + "text " * 40 for i in range(1, 8))
        chunks = _split_with_overlap(body)
        assert len(chunks) > 1, "a 2 kB procedure must not collapse into one chunk"

    def test_clause_headings_are_captured(self):
        pages = [{"page_number": 1,
                  "text": "3.4 ESCALATION\n" + "Wall loss exceeding 2.0 mm escalates. " * 20}]
        chunks = chunk_pages(pages, "sop.pdf")
        assert any(c["heading"] and "3.4" in c["heading"] for c in chunks)

    def test_short_pages_are_skipped(self):
        assert chunk_pages([{"page_number": 1, "text": "too short"}], "x.pdf") == []
