from __future__ import annotations

import json
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


# Map the guest-reported status string to a Kriterion Status enum value.
_GUEST_STATUS_MAP: dict[str, Status] = {
    "PASS": Status.PASS,
    "FAIL": Status.FAIL,
    "ERROR": Status.ERROR,
}


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

        # The runner manages its own internal timeout for the VM payload.
        # The outer subprocess timeout must cover image creation + VM boot +
        # payload execution + VM shutdown + result extraction.
        # Minimum of 120 s; add 90 s of headroom on top of the payload budget.
        outer_timeout_s = max(120.0, timeout_ms / 1000 + 90.0)

        try:
            completed = subprocess.run(
                [runner, str(manifest_path)],
                capture_output=True,
                text=True,
                timeout=outer_timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            duration = max(1, int((time.perf_counter() - started) * 1000))
            return SandboxExecutionResult(
                status=Status.ERROR,
                observed=f"Firecracker runner timed out after {outer_timeout_s:.0f}s.",
                duration_ms=duration,
                sandbox=SandboxRecord(
                    required=True, used=True, provider="firecracker", available=True,
                    detail="runner_timeout",
                ),
                error="runner_timeout",
                artifacts=[str(manifest_path)],
            )

        artifacts.append(str(manifest_path))
        if result.exists():
            artifacts.append(str(result))

        duration = max(1, int((time.perf_counter() - started) * 1000))

        # ----------------------------------------------------------------
        # CRITICAL: do NOT equate runner exit code 0 with payload PASS.
        #
        # Runner exit code 0 only means the host-side infrastructure
        # succeeded (VM booted, ran, and result.json was retrieved).
        # The guest runner can successfully handle a FAILING payload and
        # write {"status": "FAIL"}.  Always read result.json for the truth.
        # ----------------------------------------------------------------

        if completed.returncode != 0:
            # The Firecracker runner itself failed — infrastructure error,
            # not a payload failure.
            return SandboxExecutionResult(
                status=Status.ERROR,
                observed=(completed.stdout + completed.stderr)[-500:]
                    or "Firecracker runner failed without output.",
                duration_ms=duration,
                sandbox=SandboxRecord(
                    required=True, used=True, provider="firecracker", available=True,
                    detail="runner_failed",
                ),
                error=f"runner_exit={completed.returncode}",
                artifacts=artifacts,
            )

        if not result.exists():
            return SandboxExecutionResult(
                status=Status.ERROR,
                observed="Runner exited 0 but did not write result.json.",
                duration_ms=duration,
                sandbox=SandboxRecord(
                    required=True, used=True, provider="firecracker", available=True,
                    detail="result_missing",
                ),
                error="result_missing",
                artifacts=artifacts,
            )

        # Parse the guest's result.json and map it to Kriterion Status.
        try:
            guest = json.loads(result.read_text(encoding="utf-8"))
        except Exception as exc:
            return SandboxExecutionResult(
                status=Status.ERROR,
                observed=f"result.json parse error: {exc}",
                duration_ms=duration,
                sandbox=SandboxRecord(
                    required=True, used=True, provider="firecracker", available=True,
                    detail="result_parse_error",
                ),
                error=f"result_parse_error: {exc}",
                artifacts=artifacts,
            )

        guest_status_str = str(guest.get("status", "ERROR")).upper()
        guest_status = _GUEST_STATUS_MAP.get(guest_status_str, Status.ERROR)
        observed = str(guest.get("detail", f"Guest reported {guest_status_str}"))
        guest_error = str(guest["error"]) if guest.get("error") else None

        return SandboxExecutionResult(
            status=guest_status,
            observed=observed,
            duration_ms=duration,
            sandbox=SandboxRecord(
                required=True, used=True, provider="firecracker", available=True,
                detail=f"guest:{guest_status_str}",
            ),
            error=guest_error,
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
