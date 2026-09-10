"""Router classification and confidence (PHASE_0 section 0-C)."""
from __future__ import annotations

import pytest

from app.services.model_router import route

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class TestDocumentRouting:
    def test_scanned_pdf_routes_to_the_vision_model(self):
        decision = route(
            "Draft an approval note from the attached scanned inspection report.",
            ["application/pdf"],
            ["inspection_report.pdf"],
        )
        assert decision.task_class == "multimodal-document"
        assert decision.model_id == "qwen25vl-7b"
        assert decision.confidence >= 0.8

    def test_image_upload_routes_to_the_vision_model(self):
        decision = route("Review this drawing.", ["image/png"], ["pid_drawing.png"])
        assert decision.task_class == "multimodal-document"
        assert decision.confidence >= 0.8

    def test_ocr_keyword_alone_still_reaches_the_vision_model(self):
        decision = route("Run OCR over the scanned corrosion survey.")
        assert decision.task_class == "multimodal-document"


class TestCodeRouting:
    def test_py_extension_alone_is_enough(self):
        decision = route("Have a look at this.", ["text/plain"], ["coding_fixture.py"])
        assert decision.task_class == "coding"
        assert decision.model_id == "qwen3-8b"
        assert decision.confidence >= 0.8

    def test_code_keywords_without_a_file(self):
        decision = route("Write a Python function that parses readings, with pytest tests.")
        assert decision.task_class == "coding"
        assert decision.model_id == "qwen3-8b"

    def test_py_file_plus_keywords_is_the_most_confident(self):
        decision = route(
            "Fix the bug in this code and run the unit tests.",
            ["text/x-python"],
            ["coding_fixture.py"],
        )
        assert decision.task_class == "coding"
        assert decision.confidence >= 0.9


class TestSpreadsheetRouting:
    def test_xlsx_with_a_threshold_question(self):
        decision = route(
            "Which readings exceed 2.0 in the wall_loss_mm column?",
            [XLSX_MIME],
            ["readings_log.xlsx"],
        )
        assert decision.task_class == "spreadsheet-analysis"
        assert decision.model_id == "qwen3-8b"
        assert decision.confidence >= 0.8

    def test_csv_upload(self):
        decision = route("Summarise this data.", ["text/csv"], ["readings.csv"])
        assert decision.task_class == "spreadsheet-analysis"


class TestFallback:
    def test_plain_prompt_falls_back_to_general_reasoning(self):
        decision = route("What does the escalation process involve?")
        assert decision.task_class == "general-reasoning"
        assert decision.model_id == "qwen3-8b"
        assert decision.fallback is True

    def test_empty_goal_and_no_files_is_still_answerable(self):
        decision = route("")
        assert decision.task_class == "general-reasoning"
        assert decision.fallback is True


class TestDecisionShape:
    def test_payload_carries_both_naming_conventions(self):
        payload = route("Inspect the report.", ["application/pdf"], ["r.pdf"]).to_dict()
        for key in ("task_class", "model_id", "confidence", "matched_signals", "fallback"):
            assert key in payload
        # plan.md documents the camelCase names; both must be present.
        assert payload["taskClass"] == payload["task_class"]
        assert payload["modelId"] == payload["model_id"]
        assert payload["matchedSignals"] == payload["matched_signals"]

    def test_confidence_never_exceeds_one(self):
        decision = route(
            "Inspect the scanned corrosion report and extract the findings for review.",
            ["application/pdf"],
            ["inspection_report.pdf"],
        )
        assert 0.0 <= decision.confidence <= 1.0

    def test_matched_signals_are_reported(self):
        decision = route("Analyse the spreadsheet.", [XLSX_MIME], ["readings_log.xlsx"])
        assert any(s.startswith("mime:") for s in decision.matched_signals)
        assert any(s.startswith("ext:") for s in decision.matched_signals)


@pytest.mark.parametrize(
    "goal,mimes,names,expected",
    [
        ("Draft the approval note", ["application/pdf"], ["r.pdf"], "multimodal-document"),
        ("Run the tests", ["text/x-python"], ["s.py"], "coding"),
        ("Which rows exceed 4400?", [XLSX_MIME], ["d.xlsx"], "spreadsheet-analysis"),
        ("Hello", [], [], "general-reasoning"),
    ],
)
def test_routing_is_deterministic(goal, mimes, names, expected):
    first = route(goal, mimes, names)
    second = route(goal, mimes, names)
    assert first.task_class == second.task_class == expected
    assert first.confidence == second.confidence
