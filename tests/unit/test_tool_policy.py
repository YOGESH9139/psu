"""Tool allowlist and run-scoped path policy (plan.md: Sovereignty & Security)."""
from __future__ import annotations

import pytest

from worker.tools.path_utils import PathPolicyError, run_workspace, validate_path
from worker.tools.tool_registry import (
    ALLOWED_TOOLS,
    ToolNotAllowed,
    get_allowed_tool,
    sanitize_args,
    tool_schemas_for_prompt,
)

RUN_ID = "policy-test-run"

# Every tool plan.md commits to exposing must actually be registered.
REQUIRED_TOOLS = {
    "extract_pdf_pages", "run_ocr", "inspect_image",
    "search_knowledge", "read_source_excerpt",
    "read_spreadsheet", "analyze_spreadsheet",
    "create_approval_docx", "verify_docx", "list_run_artifacts",
    "write_code_file", "run_code_tests",
    "request_human_approval",
}

# Capabilities plan.md explicitly forbids.
FORBIDDEN_TOOL_NAMES = [
    "shell_exec", "run_shell", "bash", "exec",
    "http_get", "fetch_url", "browse", "web_search",
    "docker_exec", "read_host_file", "write_host_file",
    "record_approval", "approve_run",
]


class TestAllowlist:
    def test_every_promised_tool_is_registered(self):
        assert REQUIRED_TOOLS <= set(ALLOWED_TOOLS)

    @pytest.mark.parametrize("name", FORBIDDEN_TOOL_NAMES)
    def test_forbidden_capabilities_are_absent(self, name):
        assert name not in ALLOWED_TOOLS
        with pytest.raises(ToolNotAllowed):
            get_allowed_tool(name)

    def test_unknown_tool_is_rejected_not_silently_ignored(self):
        with pytest.raises(ToolNotAllowed) as excinfo:
            get_allowed_tool("definitely_not_a_tool")
        assert "allowlist" in str(excinfo.value).lower()

    def test_no_tool_can_record_an_approval_decision(self):
        """The agent may draft a note and REQUEST review. Recording the decision
        is the HTTP endpoint's job alone, so no tool module may write to the
        approval_decisions table."""
        import inspect

        for name, tool in ALLOWED_TOOLS.items():
            module = inspect.getmodule(tool.func if hasattr(tool, "func") else tool)
            source = inspect.getsource(module)
            assert "ApprovalRecord" not in source, (
                f"tool module for {name} references the approval decision table"
            )

    def test_the_approval_request_tool_only_requests(self):
        tool = ALLOWED_TOOLS["request_human_approval"]
        result = tool.invoke({
            "run_id": "policy-test-run",
            "artifact_path": "artifacts/does_not_exist.docx",
            "summary": "n/a",
        })
        # It can never return an "approved" state — only a request or an error.
        assert result["status"] in ("approval_requested", "error", "rejected")
        assert result["status"] != "approved"

    def test_schemas_are_exportable_for_prompting(self):
        schemas = tool_schemas_for_prompt()
        assert {s["name"] for s in schemas} == set(ALLOWED_TOOLS)
        for schema in schemas:
            assert schema["description"]
            assert isinstance(schema["arguments"], dict)


class TestPathPolicy:
    @pytest.mark.parametrize("bad", [
        "../../etc/passwd",
        "../../../root/.ssh/id_rsa",
        "/etc/passwd",
        "/var/run/docker.sock",
        "inputs/../../../etc/shadow",
    ])
    def test_escapes_are_rejected(self, bad):
        with pytest.raises(PathPolicyError):
            validate_path(bad, RUN_ID)

    @pytest.mark.parametrize("url", [
        "http://example.com/payload.py",
        "https://example.com/x.pdf",
        "file:///etc/passwd",
        "code/http://example.com/x.py",
    ])
    def test_urls_are_rejected(self, url):
        with pytest.raises(PathPolicyError) as excinfo:
            validate_path(url, RUN_ID)
        assert "url" in str(excinfo.value).lower()

    def test_relative_paths_resolve_inside_the_workspace(self):
        resolved = validate_path("inputs/report.pdf", RUN_ID)
        assert resolved.is_relative_to(run_workspace(RUN_ID))

    def test_absolute_path_inside_the_workspace_is_allowed(self):
        inside = run_workspace(RUN_ID) / "artifacts" / "note.docx"
        assert validate_path(str(inside), RUN_ID) == inside

    def test_another_runs_workspace_is_out_of_bounds(self):
        other = run_workspace("some-other-run") / "artifacts" / "secret.docx"
        with pytest.raises(PathPolicyError):
            validate_path(str(other), RUN_ID)

    @pytest.mark.parametrize("bad_run_id", ["../escape", "a/b", "..", "with\\slash"])
    def test_malformed_run_ids_are_rejected(self, bad_run_id):
        with pytest.raises(PathPolicyError):
            validate_path("file.txt", bad_run_id)


class TestArgumentSanitisation:
    def test_long_payloads_are_summarised_not_copied(self):
        sanitized = sanitize_args({"code": "x" * 5000, "run_id": RUN_ID})
        assert "x" * 100 not in sanitized["code"]
        assert "omitted" in sanitized["code"]
        assert sanitized["run_id"] == RUN_ID

    def test_long_lists_are_summarised(self):
        sanitized = sanitize_args({"pages": list(range(50))})
        assert "omitted" in sanitized["pages"]

    def test_short_values_pass_through_unchanged(self):
        args = {"query": "corrosion threshold", "top_k": 5}
        assert sanitize_args(args) == args
