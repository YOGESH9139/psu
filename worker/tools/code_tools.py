"""Code writing + isolated test execution.

`run_code_tests` never executes anything in the worker container. It hands the
code to the `sandbox` service (network_mode: none, read-only rootfs, 512 MB,
1 CPU, 64 PIDs) over a shared volume and waits for the result file.
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.core.config import settings
from worker.tools.path_utils import PathPolicyError, run_workspace, validate_path

SANDBOX_QUEUE = Path(settings.sandbox_queue_dir)
SANDBOX_JOBS = SANDBOX_QUEUE / "jobs"
SANDBOX_HEARTBEAT = SANDBOX_QUEUE / "heartbeat.json"

ALLOWED_CODE_EXTENSIONS = {".py", ".sh", ".txt", ".cfg", ".ini", ".toml", ".json"}
ALLOWED_TEST_COMMANDS = {
    "pytest": ["python", "-m", "pytest", "-q"],
    "unittest": ["python", "-m", "unittest", "discover", "-v"],
    "python": None,  # resolved against a specific file below
}


class WriteCodeFileInput(BaseModel):
    file_path: str = Field(..., description="Relative path inside the run workspace, e.g. solution.py")
    code: str = Field(..., description="Full source code content of the file")
    run_id: str = Field(..., description="Run ID")


class RunCodeTestsInput(BaseModel):
    run_id: str = Field(..., description="Run ID")
    test_command: str = Field(
        "pytest",
        description="One of: 'pytest', 'unittest', or 'python <file.py>'",
    )


@tool("write_code_file", args_schema=WriteCodeFileInput)
def write_code_file(file_path: str, code: str, run_id: str) -> Dict[str, Any]:
    """Write source code to a file inside the run's isolated code directory."""
    # Path policy first, so an escape attempt is reported as an escape attempt
    # rather than being masked by the extension check.
    try:
        validate_path(file_path, run_id)
    except PathPolicyError as e:
        return {"status": "rejected", "error": str(e)}

    if Path(file_path).name != file_path:
        return {
            "status": "rejected",
            "error": f"Only a bare filename is accepted, not {file_path!r}. "
                     f"Code is always written into the run's code/ directory.",
        }

    ext = Path(file_path).suffix.lower()
    if ext not in ALLOWED_CODE_EXTENSIONS:
        return {
            "status": "rejected",
            "error": f"Extension '{ext}' is not writable by this tool. "
                     f"Allowed: {sorted(ALLOWED_CODE_EXTENSIONS)}",
        }

    try:
        resolved = validate_path(Path("code") / file_path, run_id)
    except PathPolicyError as e:
        return {"status": "rejected", "error": str(e)}

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(code, encoding="utf-8")

    return {
        "status": "success",
        "file_path": f"code/{file_path}",
        "absolute_path": str(resolved),
        "bytes_written": len(code.encode("utf-8")),
        "line_count": code.count("\n") + 1,
    }


def _resolve_command(test_command: str) -> list[str] | None:
    parts = (test_command or "pytest").strip().split()
    if not parts:
        return ALLOWED_TEST_COMMANDS["pytest"]

    head = Path(parts[0]).name
    if head in ("pytest",) or parts[:3] == ["python", "-m", "pytest"]:
        return ALLOWED_TEST_COMMANDS["pytest"]
    if parts[:3] == ["python", "-m", "unittest"] or head == "unittest":
        return ALLOWED_TEST_COMMANDS["unittest"]
    if head in ("python", "python3") and len(parts) == 2 and parts[1].endswith(".py"):
        target = Path(parts[1]).name  # strip any directory component
        return ["python", target]
    return None


def sandbox_available() -> bool:
    try:
        payload = json.loads(SANDBOX_HEARTBEAT.read_text(encoding="utf-8"))
        return bool(payload.get("component") == "sandbox")
    except Exception:
        return False


@tool("run_code_tests", args_schema=RunCodeTestsInput)
def run_code_tests(run_id: str, test_command: str = "pytest") -> Dict[str, Any]:
    """Execute the run's code in the network-isolated sandbox container and return
    exit code, stdout and stderr. Never runs code in the agent process."""
    command = _resolve_command(test_command)
    if command is None:
        return {
            "status": "rejected",
            "passed": False,
            "error": f"Command '{test_command}' is not permitted. Use 'pytest', "
                     f"'unittest', or 'python <file>.py'.",
        }

    code_dir = run_workspace(run_id) / "code"
    if not code_dir.exists() or not any(code_dir.iterdir()):
        return {
            "status": "error",
            "passed": False,
            "error": "No code files have been written for this run yet.",
        }

    job_id = f"{run_id}-{uuid.uuid4().hex[:8]}"
    job_dir = SANDBOX_JOBS / job_id
    job_workspace = job_dir / "workspace"
    try:
        job_workspace.mkdir(parents=True, exist_ok=True)
        shutil.copytree(code_dir, job_workspace, dirs_exist_ok=True)
        (job_dir / "request.json").write_text(
            json.dumps({"command": command, "timeout": settings.sandbox_timeout_seconds}),
            encoding="utf-8",
        )
        # The sandbox runs unprivileged under a different uid; it must be able to
        # write result.json back into this job directory.
        os.chmod(job_dir, 0o777)
        os.chmod(job_workspace, 0o777)
    except Exception as e:
        return {"status": "error", "passed": False, "error": f"Could not queue sandbox job: {e}"}

    # The sandbox writes result.json atomically; wait a little past its own limit.
    deadline = time.monotonic() + settings.sandbox_timeout_seconds + 20
    result_path = job_dir / "result.json"
    while time.monotonic() < deadline:
        if result_path.exists():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except Exception:
                time.sleep(0.2)
                continue
            result["sandbox_job_id"] = job_id
            result["isolation"] = {
                "network_mode": "none",
                "read_only_rootfs": True,
                "mem_limit": "512m",
                "pids_limit": 64,
                "timeout_seconds": settings.sandbox_timeout_seconds,
            }
            return result
        time.sleep(0.25)

    return {
        "status": "error",
        "passed": False,
        "error": "Sandbox did not return a result in time. Is the `sandbox` service running?",
        "sandbox_job_id": job_id,
        "sandbox_reachable": sandbox_available(),
    }
