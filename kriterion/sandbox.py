from __future__ import annotations

import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .schemas import SandboxRecord, Status
from .util import command_available, ensure_dir, stable_hash, write_json


@dataclass
class SandboxExecutionResult:
    status: Status
    observed: str
    duration_ms: int
    sandbox: SandboxRecord
    error: str | None = None
    artifacts: list[str] | None = None


def execute_generated_code(code: str, tests: str, timeout_ms: int) -> SandboxExecutionResult:
    started = time.perf_counter()
    artifacts: list[str] = []
    if not command_available("firecracker"):
        return _unavailable(started, "Firecracker binary was not found on PATH.")

    kernel = os.environ.get("FIRECRACKER_KERNEL")
    rootfs = os.environ.get("FIRECRACKER_ROOTFS")
    runner = os.environ.get("KRITERION_FIRECRACKER_RUNNER")
    if not kernel or not rootfs or not runner:
        return _unavailable(
            started,
            "Firecracker requires FIRECRACKER_KERNEL, FIRECRACKER_ROOTFS, and KRITERION_FIRECRACKER_RUNNER.",
        )

    with tempfile.TemporaryDirectory(prefix="kriterion_fc_") as tmp:
        tmp_path = Path(tmp)
        payload = tmp_path / "payload.py"
        result = tmp_path / "result.json"
        payload.write_text(code + "\n\n" + tests + "\n", encoding="utf-8")
        manifest = {
            "payload": str(payload),
            "result": str(result),
            "kernel": kernel,
            "rootfs": rootfs,
            "timeout_ms": timeout_ms,
            "network": "forbidden",
            "filesystem": "restricted",
            "payload_hash": stable_hash({"code": code, "tests": tests}),
        }
        manifest_path = tmp_path / "manifest.json"
        write_json(manifest_path, manifest)
        completed = subprocess.run(
            [runner, str(manifest_path)],
            capture_output=True,
            text=True,
            timeout=max(1, timeout_ms / 1000),
            check=False,
        )
        artifacts.append(str(manifest_path))
        if result.exists():
            artifacts.append(str(result))
        duration = max(1, int((time.perf_counter() - started) * 1000))
        if completed.returncode == 0 and result.exists():
            return SandboxExecutionResult(
                status=Status.PASS,
                observed="Firecracker runner completed payload and wrote result.",
                duration_ms=duration,
                sandbox=SandboxRecord(required=True, used=True, provider="firecracker", available=True, detail="runner completed"),
                artifacts=artifacts,
            )
        return SandboxExecutionResult(
            status=Status.FAIL,
            observed=(completed.stdout + completed.stderr)[-500:] or "Firecracker runner failed without output.",
            duration_ms=duration,
            sandbox=SandboxRecord(required=True, used=True, provider="firecracker", available=True, detail="runner failed"),
            error=f"runner_exit={completed.returncode}",
            artifacts=artifacts,
        )


def firecracker_attestation(required: bool) -> tuple[SandboxRecord, Status, str]:
    if not required:
        return SandboxRecord(required=False, used=False, provider=None, available=None), Status.PASS, "not required"
    result = execute_generated_code("def noop():\n    return True", "assert noop() is True", 1000)
    return result.sandbox, result.status, result.observed


def _unavailable(started: float, detail: str) -> SandboxExecutionResult:
    return SandboxExecutionResult(
        status=Status.INSUFFICIENT_EVIDENCE,
        observed=detail,
        duration_ms=max(1, int((time.perf_counter() - started) * 1000)),
        sandbox=SandboxRecord(required=True, used=False, provider="firecracker", available=False, detail=detail),
        error=detail,
        artifacts=[],
    )
