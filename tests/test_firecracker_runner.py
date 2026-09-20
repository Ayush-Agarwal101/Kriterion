"""
tests/test_firecracker_runner.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Focused unit tests for the Firecracker integration without starting a VM.

Coverage areas
──────────────
1. Prerequisites / fail-closed behaviour
   - sandbox returns INSUFFICIENT_EVIDENCE when the 'firecracker' binary is absent.
   - sandbox returns INSUFFICIENT_EVIDENCE when any required env var is missing.

2. Host-runner manifest handling
   - main() exits 1 on missing CLI argument.
   - main() exits 1 on unreadable / malformed manifest.
   - main() exits 2 when _create_payload_image fails.

3. _read_result_from_image — all expected outputs from debugfs
   - Returns dict on valid JSON output (with or without debugfs warnings).
   - Returns None on empty stdout.
   - Returns None on non-JSON stdout.
   - Returns None on subprocess failure (returncode != 0).
   - JSON object located after leading debugfs warnings.

4. PASS / FAIL / ERROR status mapping in sandbox.py
   - Runner exit 0 + result.json{"status":"PASS"} → Status.PASS.
   - Runner exit 0 + result.json{"status":"FAIL"} → Status.FAIL.
   - Runner exit 0 + result.json{"status":"ERROR"} → Status.ERROR.
   - Runner exit 0 + result.json{"status":"UNKNOWN"} → Status.ERROR (default).
   - Runner exit non-zero → Status.ERROR (infrastructure error).
   - Runner exit 0 + result.json absent → Status.ERROR.
   - Runner exit 0 + result.json malformed → Status.ERROR.

5. config.py accessors
   - firecracker_kernel/rootfs/runner return None when env var is absent.
   - firecracker_configured() is False unless all three vars are set.
   - firecracker_configured() is True when all three are set and non-empty.

Run with:
    pytest tests/test_firecracker_runner.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import os
import tempfile
import importlib
import types

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    """Build a CompletedProcess stub."""
    cp = subprocess.CompletedProcess(args=[], returncode=returncode)
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


# ── import the modules under test ─────────────────────────────────────────────
# We import lazily inside each test function so that patching os.environ
# or built-ins takes effect before module-level code runs where needed.

sys.path.insert(0, str(Path(__file__).parent.parent))

import kriterion.firecracker_runner as fc_runner  # noqa: E402
from kriterion.schemas import Status               # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Prerequisites / fail-closed behaviour
# ═══════════════════════════════════════════════════════════════════════════════

class TestPrerequisiteFailClosed:
    """sandbox.execute_generated_code must fail-closed (INSUFFICIENT_EVIDENCE)
    whenever the Firecracker binary or any required env var is missing."""

    def _run(self, env_overrides: dict, firecracker_on_path: bool):
        """Call execute_generated_code with a controlled environment."""
        from kriterion import sandbox

        with patch("kriterion.sandbox.command_available") as mock_avail, \
             patch.dict(os.environ, env_overrides, clear=False):

            # Remove vars not supplied by the caller.
            for key in ("FIRECRACKER_KERNEL", "FIRECRACKER_ROOTFS", "KRITERION_FIRECRACKER_RUNNER"):
                if key not in env_overrides:
                    os.environ.pop(key, None)

            mock_avail.return_value = firecracker_on_path
            return sandbox.execute_generated_code("x = 1", "assert x == 1", 5_000)

    def test_no_firecracker_binary(self):
        result = self._run({}, firecracker_on_path=False)
        assert result.status == Status.INSUFFICIENT_EVIDENCE
        assert result.sandbox.available is False
        assert "firecracker" in result.observed.lower() or "not found" in result.observed.lower()

    def test_missing_kernel_env_var(self):
        env = {
            "FIRECRACKER_ROOTFS": "/fake/rootfs.ext4",
            "KRITERION_FIRECRACKER_RUNNER": "/fake/runner.py",
        }
        result = self._run(env, firecracker_on_path=True)
        assert result.status == Status.INSUFFICIENT_EVIDENCE

    def test_missing_rootfs_env_var(self):
        env = {
            "FIRECRACKER_KERNEL": "/fake/vmlinux",
            "KRITERION_FIRECRACKER_RUNNER": "/fake/runner.py",
        }
        result = self._run(env, firecracker_on_path=True)
        assert result.status == Status.INSUFFICIENT_EVIDENCE

    def test_missing_runner_env_var(self):
        env = {
            "FIRECRACKER_KERNEL": "/fake/vmlinux",
            "FIRECRACKER_ROOTFS": "/fake/rootfs.ext4",
        }
        result = self._run(env, firecracker_on_path=True)
        assert result.status == Status.INSUFFICIENT_EVIDENCE

    def test_all_env_vars_present_proceeds_to_runner(self):
        """When prerequisites are met, sandbox should call the runner subprocess.
        We patch subprocess.run to avoid actually launching Firecracker."""
        from kriterion import sandbox

        env = {
            "FIRECRACKER_KERNEL": "/fake/vmlinux",
            "FIRECRACKER_ROOTFS": "/fake/rootfs.ext4",
            "KRITERION_FIRECRACKER_RUNNER": "/fake/runner.py",
        }

        fake_result_json = json.dumps({"status": "PASS", "detail": "ok", "error": None})

        def _fake_run(cmd, **kwargs):
            # Write result.json to wherever the manifest told us.
            manifest_path = Path(cmd[1])
            manifest = json.loads(manifest_path.read_text())
            Path(manifest["result"]).write_text(fake_result_json)
            return _make_completed(0, stdout="", stderr="")

        with patch("kriterion.sandbox.command_available", return_value=True), \
             patch.dict(os.environ, env), \
             patch("kriterion.sandbox.subprocess.run", side_effect=_fake_run):
            result = sandbox.execute_generated_code("x = 1", "assert x == 1", 5_000)

        assert result.status == Status.PASS


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Host-runner manifest handling  (firecracker_runner.main)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunnerManifestHandling:
    """Unit-test main() argument and manifest parsing; no Firecracker binary needed."""

    def test_exits_1_with_no_args(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["kriterion-firecracker-runner"])
        rc = fc_runner.main()
        assert rc == 1
        assert "Usage" in capsys.readouterr().err

    def test_exits_1_on_missing_manifest_file(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(sys, "argv", ["fc", str(tmp_path / "no_such.json")])
        rc = fc_runner.main()
        assert rc == 1
        assert "Cannot read manifest" in capsys.readouterr().err

    def test_exits_1_on_malformed_manifest_json(self, monkeypatch, tmp_path, capsys):
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json}")
        monkeypatch.setattr(sys, "argv", ["fc", str(bad)])
        rc = fc_runner.main()
        assert rc == 1

    def test_exits_2_when_payload_image_creation_fails(self, monkeypatch, tmp_path, capsys):
        """_create_payload_image raises CalledProcessError → exit 2."""
        payload = tmp_path / "payload.py"
        payload.write_text("x = 1\nassert x == 1\n")
        result = tmp_path / "result.json"

        manifest = {
            "payload": str(payload),
            "result": str(result),
            "kernel": "/fake/vmlinux",
            "rootfs": "/fake/rootfs.ext4",
            "timeout_ms": 5000,
            "network": "forbidden",
            "filesystem": "restricted",
        }
        mf = tmp_path / "manifest.json"
        mf.write_text(json.dumps(manifest))
        monkeypatch.setattr(sys, "argv", ["fc", str(mf)])

        err = subprocess.CalledProcessError(1, "dd", stderr=b"no space left")
        with patch.object(fc_runner, "_create_payload_image", side_effect=err):
            rc = fc_runner.main()

        assert rc == 2
        assert "Payload image creation failed" in capsys.readouterr().err


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _read_result_from_image — debugfs output parsing
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadResultFromImage:
    """_read_result_from_image must handle all the edge-cases that debugfs
    produces in the wild, including warning lines mixed with the JSON body."""

    IMAGE = Path("/fake/payload.ext4")  # never actually opened

    def _call(self, stdout: bytes, returncode: int = 0):
        cp = subprocess.CompletedProcess(args=[], returncode=returncode,
                                         stdout=stdout, stderr=b"")
        with patch("subprocess.run", return_value=cp):
            return fc_runner._read_result_from_image(self.IMAGE)

    def test_returns_dict_on_clean_json(self):
        body = json.dumps({"status": "PASS", "detail": "ok", "error": None}).encode()
        result = self._call(body)
        assert result == {"status": "PASS", "detail": "ok", "error": None}

    def test_returns_dict_when_json_follows_debugfs_warnings(self):
        """debugfs sometimes emits warnings before the JSON body."""
        warning = b"debugfs: Warning: could not read block group descriptors\n"
        body = json.dumps({"status": "FAIL", "detail": "assertion failed", "error": "exit_code=1"}).encode()
        result = self._call(warning + body)
        assert result is not None
        assert result["status"] == "FAIL"

    def test_returns_none_on_empty_stdout(self):
        assert self._call(b"") is None

    def test_returns_none_on_non_json_stdout(self):
        assert self._call(b"debugfs: No such file or directory") is None

    def test_returns_none_on_subprocess_failure(self):
        assert self._call(b"", returncode=1) is None

    def test_returns_none_on_truncated_json(self):
        assert self._call(b'{"status": "PASS", "det') is None

    def test_all_three_status_values_parse(self):
        for status in ("PASS", "FAIL", "ERROR"):
            body = json.dumps({"status": status, "detail": "x", "error": None}).encode()
            result = self._call(body)
            assert result is not None
            assert result["status"] == status


# ═══════════════════════════════════════════════════════════════════════════════
# 4. PASS / FAIL / ERROR status mapping in sandbox.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestSandboxStatusMapping:
    """End-to-end status-mapping tests: runner subprocess is fully mocked."""

    _ENV = {
        "FIRECRACKER_KERNEL": "/fake/vmlinux",
        "FIRECRACKER_ROOTFS": "/fake/rootfs.ext4",
        "KRITERION_FIRECRACKER_RUNNER": "/fake/runner.py",
    }

    def _run_with_result(
        self,
        guest_status: str,
        runner_returncode: int = 0,
        write_result: bool = True,
        result_text: str | None = None,
    ) -> "SandboxExecutionResult":  # type: ignore[name-defined]
        from kriterion import sandbox

        def _fake_run(cmd, **kwargs):
            manifest = json.loads(Path(cmd[1]).read_text())
            if write_result:
                content = result_text or json.dumps(
                    {"status": guest_status, "detail": "test detail", "error": None}
                )
                Path(manifest["result"]).write_text(content)
            return _make_completed(runner_returncode, stdout="", stderr="runner stderr")

        with patch("kriterion.sandbox.command_available", return_value=True), \
             patch.dict(os.environ, self._ENV), \
             patch("kriterion.sandbox.subprocess.run", side_effect=_fake_run):
            return sandbox.execute_generated_code("x=1", "assert x==1", 5_000)

    def test_pass_maps_to_status_pass(self):
        result = self._run_with_result("PASS")
        assert result.status == Status.PASS

    def test_fail_maps_to_status_fail(self):
        result = self._run_with_result("FAIL")
        assert result.status == Status.FAIL

    def test_error_maps_to_status_error(self):
        result = self._run_with_result("ERROR")
        assert result.status == Status.ERROR

    def test_unknown_status_defaults_to_error(self):
        result = self._run_with_result("XYZZY")
        assert result.status == Status.ERROR

    def test_runner_nonzero_exit_is_infrastructure_error(self):
        result = self._run_with_result("PASS", runner_returncode=5, write_result=False)
        assert result.status == Status.ERROR
        assert result.error is not None
        assert "runner_exit=5" in (result.error or "")

    def test_missing_result_json_is_error(self):
        result = self._run_with_result("PASS", write_result=False)
        assert result.status == Status.ERROR
        assert "result_missing" in (result.error or "")

    def test_malformed_result_json_is_error(self):
        result = self._run_with_result("PASS", result_text="{bad json}")
        assert result.status == Status.ERROR
        assert result.error is not None
        assert "result_parse_error" in (result.error or "")

    def test_sandbox_record_provider_is_firecracker(self):
        result = self._run_with_result("PASS")
        assert result.sandbox.provider == "firecracker"
        assert result.sandbox.used is True
        assert result.sandbox.available is True

    def test_duration_ms_is_positive(self):
        result = self._run_with_result("PASS")
        assert result.duration_ms >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 5. config.py accessors
# ═══════════════════════════════════════════════════════════════════════════════

class TestFirecrackerConfig:
    """kriterion.config Firecracker accessors must reflect the env vars exactly."""

    def test_kernel_returns_none_when_unset(self, monkeypatch):
        from kriterion import config
        monkeypatch.delenv("FIRECRACKER_KERNEL", raising=False)
        assert config.firecracker_kernel() is None

    def test_kernel_returns_value_when_set(self, monkeypatch):
        from kriterion import config
        monkeypatch.setenv("FIRECRACKER_KERNEL", "/path/to/vmlinux")
        assert config.firecracker_kernel() == "/path/to/vmlinux"

    def test_rootfs_returns_none_when_unset(self, monkeypatch):
        from kriterion import config
        monkeypatch.delenv("FIRECRACKER_ROOTFS", raising=False)
        assert config.firecracker_rootfs() is None

    def test_rootfs_returns_value_when_set(self, monkeypatch):
        from kriterion import config
        monkeypatch.setenv("FIRECRACKER_ROOTFS", "/path/to/rootfs.ext4")
        assert config.firecracker_rootfs() == "/path/to/rootfs.ext4"

    def test_runner_returns_none_when_unset(self, monkeypatch):
        from kriterion import config
        monkeypatch.delenv("KRITERION_FIRECRACKER_RUNNER", raising=False)
        assert config.firecracker_runner() is None

    def test_runner_returns_value_when_set(self, monkeypatch):
        from kriterion import config
        monkeypatch.setenv("KRITERION_FIRECRACKER_RUNNER", "/path/to/runner.py")
        assert config.firecracker_runner() == "/path/to/runner.py"

    def test_configured_false_with_no_vars(self, monkeypatch):
        from kriterion import config
        for key in ("FIRECRACKER_KERNEL", "FIRECRACKER_ROOTFS", "KRITERION_FIRECRACKER_RUNNER"):
            monkeypatch.delenv(key, raising=False)
        assert config.firecracker_configured() is False

    def test_configured_false_with_partial_vars(self, monkeypatch):
        from kriterion import config
        monkeypatch.setenv("FIRECRACKER_KERNEL", "/k")
        monkeypatch.delenv("FIRECRACKER_ROOTFS", raising=False)
        monkeypatch.delenv("KRITERION_FIRECRACKER_RUNNER", raising=False)
        assert config.firecracker_configured() is False

    def test_configured_true_with_all_vars(self, monkeypatch):
        from kriterion import config
        monkeypatch.setenv("FIRECRACKER_KERNEL", "/k")
        monkeypatch.setenv("FIRECRACKER_ROOTFS", "/r")
        monkeypatch.setenv("KRITERION_FIRECRACKER_RUNNER", "/e")
        assert config.firecracker_configured() is True

    def test_empty_string_counts_as_unset(self, monkeypatch):
        from kriterion import config
        monkeypatch.setenv("FIRECRACKER_KERNEL", "  ")
        assert config.firecracker_kernel() is None

    def test_whitespace_only_counts_as_not_configured(self, monkeypatch):
        from kriterion import config
        monkeypatch.setenv("FIRECRACKER_KERNEL", "  ")
        monkeypatch.setenv("FIRECRACKER_ROOTFS", "/r")
        monkeypatch.setenv("KRITERION_FIRECRACKER_RUNNER", "/e")
        assert config.firecracker_configured() is False


# ═══════════════════════════════════════════════════════════════════════════════
# 6. _create_payload_image — subprocess call verification
# ═══════════════════════════════════════════════════════════════════════════════

class TestCreatePayloadImage:
    """_create_payload_image must call dd, mkfs.ext4, and debugfs in order."""

    def test_calls_dd_mkfs_debugfs(self, tmp_path):
        image_path = tmp_path / "payload.ext4"
        payload_src = tmp_path / "payload.py"
        payload_src.write_text("x = 1\n")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_completed(0)
            fc_runner._create_payload_image(image_path, payload_src, size_mib=8)

        assert mock_run.call_count == 3
        cmds = [c.args[0][0] for c in mock_run.call_args_list]
        assert cmds == ["dd", "mkfs.ext4", "debugfs"]

    def test_dd_receives_correct_count(self, tmp_path):
        image_path = tmp_path / "payload.ext4"
        payload_src = tmp_path / "payload.py"
        payload_src.write_text("x = 1\n")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_completed(0)
            fc_runner._create_payload_image(image_path, payload_src, size_mib=16)

        dd_args = mock_run.call_args_list[0].args[0]
        assert "count=16" in dd_args

    def test_raises_on_dd_failure(self, tmp_path):
        image_path = tmp_path / "payload.ext4"
        payload_src = tmp_path / "payload.py"
        payload_src.write_text("x = 1\n")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "dd", stderr=b"error")
            with pytest.raises(subprocess.CalledProcessError):
                fc_runner._create_payload_image(image_path, payload_src)

    def test_debugfs_write_command_contains_payload_py(self, tmp_path):
        image_path = tmp_path / "payload.ext4"
        payload_src = tmp_path / "payload.py"
        payload_src.write_text("x = 1\n")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_completed(0)
            fc_runner._create_payload_image(image_path, payload_src)

        debugfs_call = mock_run.call_args_list[2].args[0]
        assert "debugfs" in debugfs_call[0]
        # The -R argument should include 'write' and 'payload.py'
        r_arg = " ".join(debugfs_call)
        assert "payload.py" in r_arg
        assert "write" in r_arg
