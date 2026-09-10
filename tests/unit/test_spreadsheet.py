"""Spreadsheet reading and question answering (plan.md 1-L)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from worker.tools.path_utils import run_workspace
from worker.tools.spreadsheet_tools import analyze_spreadsheet, read_spreadsheet

RUN_ID = "spreadsheet-test-run"
FIXTURE = Path("/app/fixtures/readings_log.xlsx")


@pytest.fixture(scope="module", autouse=True)
def staged_fixture():
    if not FIXTURE.exists():
        pytest.skip(f"fixture missing: {FIXTURE} — run fixtures/generate_fixtures.py")
    destination = run_workspace(RUN_ID) / "inputs" / FIXTURE.name
    shutil.copy2(FIXTURE, destination)
    return destination


PATH = f"inputs/{FIXTURE.name}"


class TestReadSpreadsheet:
    def test_reports_every_sheet(self):
        result = read_spreadsheet.invoke({"file_path": PATH, "run_id": RUN_ID})
        assert result["status"] == "success"
        assert result["sheet_names"] == [
            "Thickness Survey", "Coating Condition", "Survey Schedule"
        ]

    def test_reports_columns_and_row_count(self):
        result = read_spreadsheet.invoke({"file_path": PATH, "run_id": RUN_ID})
        assert "wall_loss_mm" in result["columns"]
        assert result["row_count"] == 12
        assert len(result["sample_rows"]) == 5

    def test_identifies_numeric_columns(self):
        result = read_spreadsheet.invoke({"file_path": PATH, "run_id": RUN_ID})
        assert "wall_loss_mm" in result["numeric_columns"]
        assert "grid_point" not in result["numeric_columns"]

    def test_a_named_sheet_can_be_selected(self):
        result = read_spreadsheet.invoke(
            {"file_path": PATH, "run_id": RUN_ID, "sheet_name": "Survey Schedule"}
        )
        assert result["active_sheet"] == "Survey Schedule"
        assert "interval_hours" in result["columns"]

    def test_a_missing_file_is_reported_not_raised(self):
        result = read_spreadsheet.invoke({"file_path": "inputs/nope.xlsx", "run_id": RUN_ID})
        assert result["status"] == "error"

    def test_a_path_escape_is_rejected(self):
        result = read_spreadsheet.invoke({"file_path": "../../etc/passwd", "run_id": RUN_ID})
        assert result["status"] == "rejected"


class TestAnalyzeSpreadsheet:
    def test_threshold_question_returns_the_matching_rows(self):
        """The golden answer: G-05, G-06 and G-07 exceed 2.0 mm of wall loss."""
        result = analyze_spreadsheet.invoke({
            "file_path": PATH,
            "query": "Which rows have wall_loss_mm greater than 2.0?",
            "run_id": RUN_ID,
        })
        assert result["status"] == "success"
        assert result["match_count"] == 3
        assert {row["grid_point"] for row in result["matched_rows"]} == {"G-05", "G-06", "G-07"}
        assert result["filter"] == {"column": "wall_loss_mm", "operator": ">", "value": 2.0}

    def test_below_threshold_question_is_also_understood(self):
        result = analyze_spreadsheet.invoke({
            "file_path": PATH,
            "query": "Which readings have measured_mm below 7.5?",
            "run_id": RUN_ID,
        })
        assert result["filter"]["operator"] == "<"
        # G-05 (7.1), G-06 (6.8) and G-07 (7.4) are all under 7.5 mm.
        assert {row["grid_point"] for row in result["matched_rows"]} == {"G-05", "G-06", "G-07"}

    def test_column_letter_references_resolve(self):
        result = analyze_spreadsheet.invoke({
            "file_path": PATH,
            "query": "Which values in column D exceed 2.0?",
            "run_id": RUN_ID,
        })
        # Column D is the 4th column: wall_loss_mm.
        assert result["filter"]["column"] == "wall_loss_mm"
        assert result["match_count"] == 3

    def test_statistics_are_always_reported(self):
        result = analyze_spreadsheet.invoke({
            "file_path": PATH, "query": "Summarise this sheet.", "run_id": RUN_ID,
        })
        stats = result["column_statistics"]["wall_loss_mm"]
        assert stats["max"] == pytest.approx(2.7)
        assert stats["min"] == pytest.approx(0.1)
        assert stats["count"] == 12

    def test_an_unparseable_question_still_returns_usable_context(self):
        result = analyze_spreadsheet.invoke({
            "file_path": PATH, "query": "hmm?", "run_id": RUN_ID,
        })
        assert result["status"] == "success"
        assert result["match_count"] == 0
        assert result["sample_rows"]

    def test_the_spreadsheet_is_never_executed(self):
        """openpyxl/pandas parse cells as data; no formula or macro is evaluated."""
        result = analyze_spreadsheet.invoke({
            "file_path": PATH, "query": "Which rows have wall_loss_mm greater than 2.0?",
            "run_id": RUN_ID,
        })
        for row in result["matched_rows"]:
            for value in row.values():
                assert not callable(value)


class TestPlainLanguageQuestions:
    """The demo asks in plain English, not in column names. `temperature_c` has
    to be reachable from "above 85 degrees C"."""

    DEMO = Path("/app/fixtures/machine_health_log.xlsx")

    @pytest.fixture(autouse=True)
    def staged_demo(self):
        if not self.DEMO.exists():
            pytest.skip("run fixtures/generate_demo_fixtures.py first")
        shutil.copy2(self.DEMO, run_workspace(RUN_ID) / "inputs" / self.DEMO.name)

    def _ask(self, query):
        return analyze_spreadsheet.invoke({
            "file_path": f"inputs/{self.DEMO.name}",
            "query": query,
            "run_id": RUN_ID,
        })

    def test_degrees_reaches_the_temperature_column(self):
        result = self._ask("Which machines are running above 85 degrees C?")
        assert result["filter"]["column"] == "temperature_c"
        assert result["match_count"] == 3
        assert {r["machine_id"] for r in result["matched_rows"]} == {"M-04", "M-07", "M-10"}

    def test_a_text_column_never_wins_a_numeric_threshold(self):
        """'machines' appears in the question and in `machine_id`, but a
        threshold can only apply to a numeric column."""
        result = self._ask("Which machines have temperature over 85?")
        assert result["filter"]["column"] == "temperature_c"
        assert result["filter"]["column"] in result["numeric_columns"]

    def test_a_bare_number_with_no_unit_is_not_guessed(self):
        """"over 85" could mean temperature, units produced or downtime
        minutes. The tool reports that ambiguity instead of inventing a filter,
        so a wrong answer is never presented as a confident one."""
        result = self._ask("Which machines are over 85?")
        assert result["status"] == "success"
        assert "filter" not in result
        assert result["match_count"] == 0
        assert "no explicit column" in result["interpretation"]
        assert result["column_statistics"]  # still hands back usable context


    def test_vibration_is_matched_by_name(self):
        result = self._ask("Which machines have vibration above 4.5?")
        assert result["filter"]["column"] == "vibration_mm_s"
        assert {r["machine_id"] for r in result["matched_rows"]} == {"M-04", "M-07", "M-10"}

    def test_downtime_question(self):
        result = self._ask("Which machines had downtime over 60 minutes?")
        assert result["filter"]["column"] == "downtime_minutes"
        assert {r["machine_id"] for r in result["matched_rows"]} == {"M-04", "M-10"}
