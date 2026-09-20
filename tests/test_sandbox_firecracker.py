"""
Focused tests for the Firecracker sandbox integration in kriterion/sandbox.py.

These tests do NOT require a real Firecracker binary, KVM, or configured
environment variables.  They exercise the host-side logic by:

  - patching command_available() to simulate Firecracker presence/absence
  - patching subprocess.run() with side-effects that write a synthetic
    result.json (or don't, to simulate failure)
  - directly manipulating env vars inside each test

Tests:
  1. test_firecracker_not_on_path
     → command_available("firecracker") returns False
     → Status.INSUFFICIENT_EVIDENCE, sandbox.available=False

  2. test_missing_env_vars
     → firecracker on PATH, but env vars not set
     → Status.INSUFFICIENT_EVIDENCE, sandbox.available=False

  3. test_successful_pass_execution
     → runner exits 0, writes {"status": "PASS", "detail": "all tests passed"}
     → SandboxExecutionResult.status == Status.PASS

  4. test_failing_payload_execution
     → runner exits 0, writes {"status": "FAIL", "detail": "assertion failed"}
     → SandboxExecutionResult.status == Status.FAIL
     (not PASS — exit code 0 must NOT be equated with payload PASS)

  5. test_error_payload_execution
     → runner exits 0, writes {"status": "ERROR", "detail": "...", "error": "..."}
     → SandboxExecutionResult.status == Status.ERROR

  6. test_runner_nonzero_exit_is_infrastructure_error
     → runner exits non-zero (e.g. VM failed to boot)
     → SandboxExecutionResult.status == Status.ERROR (not FAIL, not PASS)

  7. test_runner_exits_0_but_no_result_json
     → runner exits 0 but never writes result.json
     → SandboxExecutionResult.status == Status.ERROR

  8. test_result_json_unrecognised_status_maps_to_error
     → guest writes {"status": "UNKNOWN"}
     → SandboxExecutionResult.status == Status.ERROR (fail-closed)

  9. test_sandbox_record_fields_on_pass
     → SandboxRecord.required=True, used=True, provider="firecracker", available=True

  10. test_firecracker_attestation_not_required
      → firecracker_attestation(required=False)
      → Status.PASS without calling execute_generated_code
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

# ---------------------------------------------------------------------------
# We import the functions under test directly so we are not coupled to the
# package installation path; adjust if the package layout differs.
# ---------------------------------------------------------------------------
from kriterion.sandbox import execute_generated_code, firecracker_attestation
from kriterion.schemas import Status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FC_BINARY = "/usr/local/bin/firecracker"

_ENV_BASE = {
    "FIRECRACKER_KERNEL": "/home/user/kriterion-firecracker/vmlinux",
    "FIRECRACKER_ROOTFS": "/home/user/kriterion-firecracker/kriterion-runner-rootfs.ext4",
    "KRITERION_FIRECRACKER_RUNNER": "/usr/local/bin/kriterion-firecracker-runner",
}


def _make_runner_side_effect(guest_result: dict | None, exit_code: int = 0):
    """
    Return a side-effect callable for unittest.mock.patch("subprocess.run").

    When the fake runner is called (cmd[0] is the runner path), it reads the
    manifest to find the result path, optionally writes guest_result there, and
    returns a CompletedProcess with the given exit_code.

    All other subprocess.run calls (e.g. write_json internally) are passed
    through as a simple no-op MagicMock.
    """
    def _side_effect(cmd, **kwargs):  # noqa: ANN001
        if not isinstance(cmd, (list, tuple)) or len(cmd) < 2:
            return MagicMock(returncode=0, stdout="", stderr="")
        runner_path = os.environ.get("KRITERION_FIRECRACKER_RUNNER", "")
        if str(cmd[0]) == runner_path:
            manifest_path = Path(cmd[1])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if guest_result is not None:
                Path(manifest["result"]).write_text(
                    json.dumps(guest_result), encoding="utf-8"
                )
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=exit_code,
                stdout="",
                stderr="" if exit_code == 0 else "VM boot failed",
            )
        return MagicMock(returncode=0, stdout="", stderr="")

    return _side_effect


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestFirecrackerNotOnPath(unittest.TestCase):
    def test_firecracker_not_on_path(self):
        with patch("kriterion.sandbox.command_available", return_value=False):
            result = execute_generated_code("x = 1", "assert x == 1", timeout_ms=1000)
        self.assertEqual(result.status, Status.INSUFFICIENT_EVIDENCE)
        self.assertFalse(result.sandbox.available)
        self.assertEqual(result.sandbox.provider, "firecracker")
        self.assertFalse(result.sandbox.used)


class TestMissingEnvVars(unittest.TestCase):
    def _run_with_env(self, env: dict[str, str]):
        with patch("kriterion.sandbox.command_available", return_value=True):
            with patch.dict(os.environ, env, clear=True):
                return execute_generated_code("x = 1", "assert x == 1", timeout_ms=1000)

    def test_all_vars_missing(self):
        result = self._run_with_env({})
        self.assertEqual(result.status, Status.INSUFFICIENT_EVIDENCE)
        self.assertFalse(result.sandbox.available)

    def test_kernel_missing(self):
        env = dict(_ENV_BASE)
        del env["FIRECRACKER_KERNEL"]
        result = self._run_with_env(env)
        self.assertEqual(result.status, Status.INSUFFICIENT_EVIDENCE)

    def test_rootfs_missing(self):
        env = dict(_ENV_BASE)
        del env["FIRECRACKER_ROOTFS"]
        result = self._run_with_env(env)
        self.assertEqual(result.status, Status.INSUFFICIENT_EVIDENCE)

    def test_runner_missing(self):
        env = dict(_ENV_BASE)
        del env["KRITERION_FIRECRACKER_RUNNER"]
        result = self._run_with_env(env)
        self.assertEqual(result.status, Status.INSUFFICIENT_EVIDENCE)


class TestSuccessfulPassExecution(unittest.TestCase):
    def test_guest_pass_maps_to_status_pass(self):
        guest = {"status": "PASS", "detail": "all tests passed"}
        with patch("kriterion.sandbox.command_available", return_value=True), \
             patch.dict(os.environ, _ENV_BASE), \
             patch("subprocess.run", side_effect=_make_runner_side_effect(guest, exit_code=0)):
            result = execute_generated_code(
                "def add(a, b): return a + b",
                "assert add(1, 2) == 3",
                timeout_ms=5000,
            )
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.observed, "all tests passed")
        self.assertTrue(result.sandbox.required)
        self.assertTrue(result.sandbox.used)
        self.assertTrue(result.sandbox.available)
        self.assertEqual(result.sandbox.provider, "firecracker")
        self.assertIn("PASS", result.sandbox.detail)
        self.assertIsNone(result.error)


class TestFailingPayloadExecution(unittest.TestCase):
    def test_guest_fail_maps_to_status_fail(self):
        """
        CRITICAL: runner exit code 0 must NOT be equated with Status.PASS.
        The guest can successfully handle a failing payload and write FAIL.
        """
        guest = {"status": "FAIL", "detail": "assertion failed: expected 4 got 3"}
        with patch("kriterion.sandbox.command_available", return_value=True), \
             patch.dict(os.environ, _ENV_BASE), \
             patch("subprocess.run", side_effect=_make_runner_side_effect(guest, exit_code=0)):
            result = execute_generated_code(
                "def add(a, b): return a + b",
                "assert add(2, 2) == 5",   # deliberately wrong
                timeout_ms=5000,
            )
        # Runner exited 0, but payload FAILED — must be FAIL, not PASS.
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("assertion failed", result.observed)
        self.assertTrue(result.sandbox.used)


class TestErrorPayloadExecution(unittest.TestCase):
    def test_guest_error_maps_to_status_error(self):
        guest = {
            "status": "ERROR",
            "detail": "payload raised NameError",
            "error": "NameError: name 'undefined_fn' is not defined",
        }
        with patch("kriterion.sandbox.command_available", return_value=True), \
             patch.dict(os.environ, _ENV_BASE), \
             patch("subprocess.run", side_effect=_make_runner_side_effect(guest, exit_code=0)):
            result = execute_generated_code(
                "undefined_fn()",
                "",
                timeout_ms=5000,
            )
        self.assertEqual(result.status, Status.ERROR)
        self.assertIsNotNone(result.error)
        self.assertIn("NameError", result.error)


class TestRunnerNonZeroExit(unittest.TestCase):
    def test_infrastructure_failure_is_error_not_fail(self):
        """
        When the runner itself fails (non-zero exit), that is an infrastructure
        error — NOT a payload failure.  Status must be ERROR.
        """
        with patch("kriterion.sandbox.command_available", return_value=True), \
             patch.dict(os.environ, _ENV_BASE), \
             patch("subprocess.run", side_effect=_make_runner_side_effect(None, exit_code=3)):
            result = execute_generated_code("x = 1", "assert x == 1", timeout_ms=5000)
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("runner_exit=3", result.error)
        # Infrastructure failure must NOT report PASS or FAIL
        self.assertNotEqual(result.status, Status.PASS)
        self.assertNotEqual(result.status, Status.FAIL)


class TestRunnerExitsZeroButNoResultJson(unittest.TestCase):
    def test_missing_result_json_is_error(self):
        """Runner exits 0 but never wrote result.json → ERROR (fail-closed)."""
        with patch("kriterion.sandbox.command_available", return_value=True), \
             patch.dict(os.environ, _ENV_BASE), \
             patch("subprocess.run", side_effect=_make_runner_side_effect(None, exit_code=0)):
            result = execute_generated_code("x = 1", "assert x == 1", timeout_ms=5000)
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("result", result.error.lower())


class TestUnrecognisedGuestStatus(unittest.TestCase):
    def test_unknown_status_maps_to_error(self):
        """Unknown status strings must map to ERROR (fail-closed)."""
        guest = {"status": "UNKNOWN", "detail": "something weird"}
        with patch("kriterion.sandbox.command_available", return_value=True), \
             patch.dict(os.environ, _ENV_BASE), \
             patch("subprocess.run", side_effect=_make_runner_side_effect(guest, exit_code=0)):
            result = execute_generated_code("x = 1", "assert x == 1", timeout_ms=5000)
        self.assertEqual(result.status, Status.ERROR)


class TestSandboxRecordFieldsOnPass(unittest.TestCase):
    def test_sandbox_record_required_fields(self):
        guest = {"status": "PASS", "detail": "ok"}
        with patch("kriterion.sandbox.command_available", return_value=True), \
             patch.dict(os.environ, _ENV_BASE), \
             patch("subprocess.run", side_effect=_make_runner_side_effect(guest, exit_code=0)):
            result = execute_generated_code("x = 1", "assert x == 1", timeout_ms=2000)
        sb = result.sandbox
        self.assertTrue(sb.required)
        self.assertTrue(sb.used)
        self.assertEqual(sb.provider, "firecracker")
        self.assertTrue(sb.available)
        self.assertIsNotNone(sb.detail)


class TestFirecrackerAttestationNotRequired(unittest.TestCase):
    def test_not_required_returns_pass_without_execution(self):
        """
        firecracker_attestation(required=False) must return PASS immediately
        without attempting to execute any code.
        """
        with patch("kriterion.sandbox.execute_generated_code") as mock_exec:
            sandbox_rec, status, observed = firecracker_attestation(required=False)
        mock_exec.assert_not_called()
        self.assertEqual(status, Status.PASS)
        self.assertFalse(sandbox_rec.required)
        self.assertFalse(sandbox_rec.used)

    def test_required_delegates_to_execute_generated_code(self):
        """firecracker_attestation(required=True) must call execute_generated_code."""
        guest = {"status": "PASS", "detail": "noop passed"}
        with patch("kriterion.sandbox.command_available", return_value=True), \
             patch.dict(os.environ, _ENV_BASE), \
             patch("subprocess.run", side_effect=_make_runner_side_effect(guest, exit_code=0)):
            sandbox_rec, status, observed = firecracker_attestation(required=True)
        self.assertEqual(status, Status.PASS)
        self.assertTrue(sandbox_rec.required)


if __name__ == "__main__":
    unittest.main()
