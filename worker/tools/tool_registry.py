"""Tool allowlist. Anything not named here cannot be executed, ever.

The allowlist is the security boundary: no shell exec, no Docker socket, no URL
fetch, no unrestricted filesystem path. Blocked attempts raise `ToolNotAllowed`
so the agent records them as audit rows instead of failing silently.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from worker.tools.code_tools import run_code_tests, write_code_file
from worker.tools.docx_tools import create_approval_docx, verify_docx
from worker.tools.ocr_tools import extract_pdf_pages, inspect_image, run_ocr
from worker.tools.rag_tools import read_source_excerpt, search_knowledge
from worker.tools.spreadsheet_tools import analyze_spreadsheet, read_spreadsheet
from worker.tools.system_tools import list_run_artifacts, request_human_approval

logger = logging.getLogger("sovereign.tool_registry")


class ToolNotAllowed(PermissionError):
    """Raised when the agent proposes a tool outside the allowlist."""


# ─── Roadmap stubs (declared, deliberately not wired into the demo flow) ─────

class RoadmapArtifactInput(BaseModel):
    run_id: str = Field(..., description="Run ID")
    output_filename: str = Field(..., description="Requested output filename")


@tool("create_calculation_xlsx", args_schema=RoadmapArtifactInput)
def create_calculation_xlsx(run_id: str, output_filename: str) -> Dict[str, Any]:
    """XLSX artifact generation — declared adapter, not part of the MVP flow."""
    return {"status": "roadmap", "tool": "create_calculation_xlsx",
            "message": "XLSX generation is a roadmap adapter, not an MVP deliverable."}


@tool("create_presentation_pptx", args_schema=RoadmapArtifactInput)
def create_presentation_pptx(run_id: str, output_filename: str) -> Dict[str, Any]:
    """PPTX artifact generation — declared adapter, not part of the MVP flow."""
    return {"status": "roadmap", "tool": "create_presentation_pptx",
            "message": "PPTX generation is a roadmap adapter, not an MVP deliverable."}


ALLOWED_TOOLS: Dict[str, BaseTool] = {
    # Document intake / multimodal
    "extract_pdf_pages": extract_pdf_pages,
    "run_ocr": run_ocr,
    "inspect_image": inspect_image,
    # Local knowledge base
    "search_knowledge": search_knowledge,
    "read_source_excerpt": read_source_excerpt,
    # Spreadsheets
    "read_spreadsheet": read_spreadsheet,
    "analyze_spreadsheet": analyze_spreadsheet,
    # Deliverables
    "create_approval_docx": create_approval_docx,
    "verify_docx": verify_docx,
    "list_run_artifacts": list_run_artifacts,
    # Code
    "write_code_file": write_code_file,
    "run_code_tests": run_code_tests,
    # Human-in-the-loop
    "request_human_approval": request_human_approval,
    # Roadmap adapters
    "create_calculation_xlsx": create_calculation_xlsx,
    "create_presentation_pptx": create_presentation_pptx,
}

# Tools whose arguments always carry a run-scoped path.
RUN_SCOPED_TOOLS = {
    name for name, t in ALLOWED_TOOLS.items()
    if "run_id" in (t.args_schema.model_fields if t.args_schema else {})
}


def get_allowed_tool(tool_name: str) -> BaseTool:
    """Return the tool, or raise ToolNotAllowed (which the caller must audit)."""
    if tool_name not in ALLOWED_TOOLS:
        logger.warning("SECURITY BLOCK: disallowed tool requested: %r", tool_name)
        raise ToolNotAllowed(
            f"Tool '{tool_name}' is not in the allowlist. Allowed tools: "
            f"{sorted(ALLOWED_TOOLS)}"
        )
    return ALLOWED_TOOLS[tool_name]


def get_all_tools() -> List[BaseTool]:
    return list(ALLOWED_TOOLS.values())


def tool_schemas_for_prompt(exclude: set[str] | None = None) -> List[Dict[str, Any]]:
    """Compact JSON-schema list handed to the local model when it plans."""
    exclude = exclude or set()
    schemas = []
    for name, t in ALLOWED_TOOLS.items():
        if name in exclude:
            continue
        fields = {}
        if t.args_schema is not None:
            for field_name, field in t.args_schema.model_fields.items():
                fields[field_name] = {
                    "type": getattr(field.annotation, "__name__", str(field.annotation)),
                    "required": field.is_required(),
                    "description": field.description or "",
                }
        schemas.append({
            "name": name,
            "description": (t.description or "").strip().split("\n")[0],
            "arguments": fields,
        })
    return schemas


def sanitize_args(args: Dict[str, Any], max_len: int = 300) -> Dict[str, Any]:
    """Audit-safe view of tool arguments — long payloads (source code, prompts)
    are summarised rather than copied into the audit log."""
    out: Dict[str, Any] = {}
    for key, value in (args or {}).items():
        if isinstance(value, str) and len(value) > max_len:
            out[key] = f"<{len(value)} chars omitted>"
        elif isinstance(value, (list, tuple)) and len(value) > 10:
            out[key] = f"<{len(value)} items omitted>"
        else:
            out[key] = value
    return out
