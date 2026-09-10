"""Agent state-machine behaviour: the human gate, the guards, and the repair loop.

These drive the real LangGraph graph with the local model stubbed out, so they
assert on control flow rather than on model output. Postgres and Redis must be
up (`docker compose up -d`); the model server need not be.
"""
from __future__ import annotations

import json
import time
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.db_models import ApprovalDecision, ApprovalRecord, AuditEvent, Run, RunStatus
from worker.agent import graph as agent_graph_module
from worker.agent import planning
from worker.agent.graph import after_approval, after_observe, after_verify

engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
Session = sessionmaker(bind=engine)


@pytest.fixture
def run_row():
    run_id = str(uuid.uuid4())
    with Session() as session:
        session.add(Run(id=run_id, goal="test goal", status=RunStatus.queued, file_ids=[]))
        session.commit()
    yield run_id
    with Session() as session:
        session.query(AuditEvent).filter(AuditEvent.run_id == run_id).delete()
        session.query(ApprovalRecord).filter(ApprovalRecord.run_id == run_id).delete()
        session.query(Run).filter(Run.id == run_id).delete()
        session.commit()


# ─── The human-in-the-loop gate ─────────────────────────────────────────────

class TestApprovalGate:
    def test_a_document_run_needing_approval_cannot_go_straight_to_deliver(self):
        state = {
            "task_class": "multimodal-document",
            "verify_result": {"valid": True},
            "needs_approval": True,
            "replan_count": 0,
        }
        assert after_verify(state) == "await_approval"

    def test_a_rejected_run_is_re_planned_once_then_stops(self):
        first = {"approval_decision": "reject", "approval_note": "wrong asset",
                 "replan_count": 0, "run_id": "x"}
        assert after_approval(first) == "plan"

        second = {"approval_decision": "reject", "approval_note": "still wrong",
                  "replan_count": 1, "run_id": "x"}
        assert after_approval(second) == "deliver"  # recorded as rejected_final

    def test_an_approved_run_proceeds_to_deliver(self):
        assert after_approval({"approval_decision": "approve", "replan_count": 0}) == "deliver"

    def test_await_approval_refuses_to_finalize_without_a_database_row(self, run_row):
        """A forged queue signal with no decision row must not unblock the run."""
        agent_graph_module.redis_client.rpush(
            f"run:{run_row}:approval", json.dumps({"decision": "approve", "note": "forged"})
        )
        result = agent_graph_module.await_approval_node({
            "run_id": run_row, "verify_result": {"valid": True},
            "findings": [], "citations": [],
        })
        assert result.get("error")
        assert "no matching decision row" in result["error"].lower()
        assert result.get("approval_decision") is None

    def test_await_approval_accepts_a_real_recorded_decision(self, run_row):
        with Session() as session:
            session.add(ApprovalRecord(
                run_id=run_row, revision=1, decision=ApprovalDecision.approve,
                note="verified on site", decided_by="human",
            ))
            session.commit()

        agent_graph_module.redis_client.rpush(
            f"run:{run_row}:approval", json.dumps({"decision": "approve", "note": "verified on site"})
        )
        result = agent_graph_module.await_approval_node({
            "run_id": run_row, "verify_result": {"valid": True},
            "findings": [], "citations": [],
        })
        assert result["approval_decision"] == "approve"
        assert result["approval_note"] == "verified on site"

    def test_no_agent_tool_can_record_an_approval(self):
        from worker.tools.tool_registry import ALLOWED_TOOLS

        record = ALLOWED_TOOLS["request_human_approval"].invoke.__doc__ or ""
        assert "approve" not in record.lower() or "cannot" in record.lower()
        # And the graph reads the decision from Postgres, never writes one.
        source = open(agent_graph_module.__file__, encoding="utf-8").read()
        assert "session.add(ApprovalRecord" not in source


# ─── Guards ─────────────────────────────────────────────────────────────────

class TestGuards:
    def test_the_tool_budget_ends_the_act_loop(self):
        state = {
            "iteration_count": settings.max_tool_cycles,
            "current_tool_idx": 0,
            "plan": [{"tool": "run_ocr"}] * 20,
            "run_id": "guard-test",
            "started_at": time.monotonic(),
        }
        assert after_observe(state) == "verify"

    def test_more_plan_steps_keep_the_loop_going(self):
        state = {
            "iteration_count": 1,
            "current_tool_idx": 1,
            "plan": [{"tool": "run_ocr"}, {"tool": "search_knowledge"}],
            "started_at": time.monotonic(),
        }
        assert after_observe(state) == "act"

    def test_the_wall_clock_timeout_fails_the_run(self):
        state = {
            "iteration_count": 0,
            "current_tool_idx": 0,
            "plan": [{"tool": "run_ocr"}],
            "started_at": time.monotonic() - settings.run_timeout_seconds - 1,
        }
        assert after_observe(state) == "fail"

    def test_an_error_short_circuits_to_fail(self):
        assert after_observe({"error": "ollama down", "started_at": time.monotonic()}) == "fail"


# ─── The code repair loop ───────────────────────────────────────────────────

class TestRepairLoop:
    def test_a_failing_test_run_triggers_exactly_one_repair(self):
        failed = {
            "task_class": "coding",
            "repair_count": 1,
            "repair_hint": "AssertionError in test_reading_exactly_at_limit",
            "observations": [
                {"tool": "run_code_tests", "result": {"passed": False, "exit_code": 1}}
            ],
        }
        assert after_verify(failed) == "plan"

        exhausted = {**failed, "repair_count": 2}
        assert after_verify(exhausted) == "deliver"

    def test_a_passing_test_run_goes_straight_to_deliver(self):
        state = {
            "task_class": "coding",
            "repair_count": 0,
            "observations": [
                {"tool": "run_code_tests", "result": {"passed": True, "exit_code": 0}}
            ],
        }
        assert after_verify(state) == "deliver"

    def test_a_coding_run_never_asks_for_approval(self):
        """Only safety-relevant recommendations gate on a human."""
        plan = planning.build_plan({"task_class": "coding", "run_id": "r", "input_files": []})
        assert "request_human_approval" not in [step["tool"] for step in plan]


# ─── Plan construction ──────────────────────────────────────────────────────

class TestPlans:
    def test_a_pdf_plan_ends_at_the_human_gate(self):
        plan = planning.build_plan({
            "task_class": "multimodal-document",
            "run_id": "r",
            "input_files": [{"workspace_path": "inputs/report.pdf",
                             "mime_type": "application/pdf", "filename": "report.pdf"}],
        })
        tools = [step["tool"] for step in plan]
        assert tools[0] == "extract_pdf_pages"
        assert tools[-1] == "request_human_approval"
        assert "search_knowledge" in tools
        assert "verify_docx" in tools

    def test_page_discovery_expands_the_plan_within_budget(self):
        state = {"run_id": "r", "plan": [{"tool": "extract_pdf_pages"}] * 6}
        extra = planning.expand_plan(state, "extract_pdf_pages", {
            "status": "success",
            "pages": [{"image_path": f"pages/report/page_{i}.png", "page_number": i}
                      for i in range(1, 6)],
        })
        assert len(state["plan"]) + len(extra) <= settings.max_tool_cycles
        assert any(step["tool"] == "run_ocr" for step in extra)

    def test_expansion_is_skipped_when_extraction_failed(self):
        assert planning.expand_plan({"run_id": "r", "plan": []},
                                    "extract_pdf_pages", {"status": "error"}) == []

    def test_run_scoped_tools_always_receive_their_run_id(self):
        state = {"run_id": "abc123", "task_class": "spreadsheet-analysis", "goal": "g",
                 "observations": [], "input_files": []}
        args = planning.resolve_args(state, {"tool": "read_spreadsheet",
                                             "args": {"file_path": "inputs/x.xlsx"}})
        assert args["run_id"] == "abc123"

    def test_knowledge_search_is_not_run_scoped(self):
        state = {"run_id": "abc123", "goal": "corrosion threshold", "observations": []}
        args = planning.resolve_args(state, {"tool": "search_knowledge", "args": {}})
        assert "run_id" not in args
        assert args["query"]
