"""Isolated code-execution runner.

This process is the ONLY thing that ever executes agent-generated code. It runs
in a container with `network_mode: none`, a read-only root filesystem, dropped
capabilities and CPU/memory/PID limits. It has no Docker socket, no network
stack and no access to the run workspaces.

Protocol — a shared volume, deliberately not a network socket:

    /sandbox_queue/jobs/<job_id>/request.json   written by the worker
    /sandbox_queue/jobs/<job_id>/workspace/     code files, copied by the worker
    /sandbox_queue/jobs/<job_id>/result.json    written here when finished
    /sandbox_queue/heartbeat.json               liveness + measured egress state

request.json: {"command": ["python", "-m", "pytest", "-q"], "timeout": 60}
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

QUEUE_DIR = Path(os.environ.get("SANDBOX_QUEUE_DIR", "/sandbox_queue"))
JOBS_DIR = QUEUE_DIR / "jobs"
HEARTBEAT_PATH = QUEUE_DIR / "heartbeat.json"

MAX_TIMEOUT = int(os.environ.get("SANDBOX_MAX_TIMEOUT", "60"))
MAX_OUTPUT_CHARS = 8000
POLL_INTERVAL = 0.25
HEARTBEAT_INTERVAL = 10.0

# Only these executables may ever be launched, regardless of what the request says.
ALLOWED_EXECUTABLES = {"python", "python3", "pytest"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _egress_blocked() -> bool:
    """Confirm from the inside that this container cannot reach the internet."""
    for host, port in (("8.8.8.8", 443), ("1.1.1.1", 443)):
        try:
            socket.create_connection((host, port), timeout=2).close()
            return False
        except Exception:
            continue
    return True


def write_heartbeat() -> None:
    payload = {
        "component": "sandbox",
        "timestamp": _now(),
        "egress_blocked": _egress_blocked(),
        "network_mode": "none",
        "read_only_rootfs": not os.access("/etc", os.W_OK),
        "pid": os.getpid(),
    }
    tmp = HEARTBEAT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(HEARTBEAT_PATH)


def _validate_command(command: list[str]) -> list[str] | None:
    if not command or not isinstance(command, list):
        return None
    exe = Path(str(command[0])).name
    if exe not in ALLOWED_EXECUTABLES:
        return None
    if any(not isinstance(part, str) for part in command):
        return None
    return [str(part) for part in command]


def run_job(job_dir: Path) -> None:
    request_path = job_dir / "request.json"
    result_path = job_dir / "result.json"
    workspace = job_dir / "workspace"

    started = time.monotonic()
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except Exception as e:
        _write_result(result_path, {
            "status": "error",
            "error": f"Unreadable request.json: {e}",
            "passed": False,
            "exit_code": None,
        })
        return

    command = _validate_command(request.get("command") or [])
    if command is None:
        _write_result(result_path, {
            "status": "rejected",
            "error": f"Executable not permitted in sandbox. Allowed: "
                     f"{sorted(ALLOWED_EXECUTABLES)}",
            "passed": False,
            "exit_code": None,
        })
        return

    timeout = min(int(request.get("timeout", MAX_TIMEOUT) or MAX_TIMEOUT), MAX_TIMEOUT)
    workspace.mkdir(parents=True, exist_ok=True)

    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": str(workspace),
    }

    try:
        proc = subprocess.run(
            command,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        _write_result(result_path, {
            "status": "completed",
            "exit_code": proc.returncode,
            "passed": proc.returncode == 0,
            "stdout": proc.stdout[-MAX_OUTPUT_CHARS:],
            "stderr": proc.stderr[-MAX_OUTPUT_CHARS:],
            "duration_seconds": round(time.monotonic() - started, 3),
            "command": command,
        })
    except subprocess.TimeoutExpired as e:
        _write_result(result_path, {
            "status": "timeout",
            "exit_code": None,
            "passed": False,
            "stdout": (e.stdout or b"").decode(errors="replace")[-MAX_OUTPUT_CHARS:]
            if isinstance(e.stdout, bytes) else (e.stdout or "")[-MAX_OUTPUT_CHARS:],
            "stderr": f"Execution exceeded the {timeout}s sandbox limit and was killed.",
            "duration_seconds": round(time.monotonic() - started, 3),
            "command": command,
        })
    except Exception as e:
        _write_result(result_path, {
            "status": "error",
            "exit_code": None,
            "passed": False,
            "error": str(e),
            "duration_seconds": round(time.monotonic() - started, 3),
        })


def _write_result(result_path: Path, payload: dict) -> None:
    payload.setdefault("finished_at", _now())
    tmp = result_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(result_path)  # atomic: the worker never sees a partial result


def main() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    write_heartbeat()
    last_heartbeat = time.monotonic()
    print(f"[sandbox] runner ready; polling {JOBS_DIR}", flush=True)

    while True:
        try:
            for job_dir in sorted(JOBS_DIR.iterdir()):
                if not job_dir.is_dir():
                    continue
                if not (job_dir / "request.json").exists():
                    continue
                if (job_dir / "result.json").exists() or (job_dir / ".claimed").exists():
                    continue
                (job_dir / ".claimed").write_text(_now(), encoding="utf-8")
                print(f"[sandbox] running job {job_dir.name}", flush=True)
                run_job(job_dir)
                print(f"[sandbox] finished job {job_dir.name}", flush=True)
        except Exception as e:  # never let the loop die
            print(f"[sandbox] loop error: {e}", file=sys.stderr, flush=True)

        if time.monotonic() - last_heartbeat >= HEARTBEAT_INTERVAL:
            try:
                write_heartbeat()
            except Exception as e:
                print(f"[sandbox] heartbeat error: {e}", file=sys.stderr, flush=True)
            last_heartbeat = time.monotonic()

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
