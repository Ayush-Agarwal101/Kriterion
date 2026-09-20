#!/usr/bin/env python3
"""
Kriterion Firecracker guest payload runner.

Called by guest_init.sh as:

    python3 /sbin/payload_runner.py <payload_mount_dir>

Responsibilities:
  1. Locate payload.py on the mounted payload drive.
  2. Execute it in a subprocess with an internal timeout.
  3. Write result.json to the same payload drive directory.
  4. Exit 0 on successful write (regardless of PASS/FAIL/ERROR status).

result.json schema (must match sandbox.py _GUEST_STATUS_MAP consumer):
  {
    "status": "PASS" | "FAIL" | "ERROR",
    "detail": "<human-readable summary of up to ~600 chars>",
    "error":  null | "<error class or message>"
  }

This file is installed at /sbin/payload_runner.py in the guest rootfs by
firecracker/build_rootfs.sh.  Do not use any third-party packages — only
the Python 3 standard library is available in the minimal rootfs.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback

# Internal timeout for the Python payload itself.  The host-side runner has
# its own wall-clock timeout that covers VM boot + this budget + shutdown.
# 30 s is generous for any inline assertion test Kriterion generates.
_PAYLOAD_TIMEOUT_S: int = 30


def main() -> None:
    payload_dir: str = sys.argv[1] if len(sys.argv) > 1 else "/mnt/payload"
    payload_path: str = os.path.join(payload_dir, "payload.py")
    result_path: str = os.path.join(payload_dir, "result.json")

    # Verify payload.py was written onto the drive by the host runner.
    if not os.path.exists(payload_path):
        _write_result(
            result_path,
            "ERROR",
            f"payload.py not found at {payload_path}",
            "payload_missing",
        )
        return

    # Execute payload.py as a subprocess so an assert/exception in user code
    # cannot corrupt the runner process state.
    try:
        proc = subprocess.run(
            [sys.executable, payload_path],
            capture_output=True,
            text=True,
            timeout=_PAYLOAD_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        _write_result(
            result_path,
            "ERROR",
            f"payload timed out after {_PAYLOAD_TIMEOUT_S}s",
            "timeout",
        )
        return
    except Exception:
        detail = traceback.format_exc()[-600:]
        _write_result(result_path, "ERROR", detail, "runner_exception")
        return

    # Map exit code → status.
    # sandbox.py wrote the payload as:  <code>\n\n<tests>\n
    # The tests are bare assert statements; a failing assert raises AssertionError
    # (exit code 1) and a passing test exits 0.
    if proc.returncode == 0:
        stdout_snippet = _truncate(proc.stdout)
        detail = f"payload exited 0{stdout_snippet}"
        _write_result(result_path, "PASS", detail, None)
    else:
        combined = (proc.stdout + proc.stderr)[-600:].strip()
        detail = combined if combined else f"exit_code={proc.returncode}"
        _write_result(result_path, "FAIL", detail, f"exit_code={proc.returncode}")


def _write_result(path: str, status: str, detail: str, error: str | None) -> None:
    """Write result.json; emit to stderr as a last resort if the write fails."""
    record = {"status": status, "detail": detail, "error": error}
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh)
            fh.flush()
            os.fsync(fh.fileno())
    except Exception as exc:
        # The host-side runner captures Firecracker stdout/stderr via the log.
        print(f"kriterion-guest: CRITICAL failed to write {path}: {exc}", file=sys.stderr)
        print(f"kriterion-guest: result was {record}", file=sys.stderr)


def _truncate(text: str, limit: int = 200) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    return f": {stripped[:limit]}"


if __name__ == "__main__":
    main()