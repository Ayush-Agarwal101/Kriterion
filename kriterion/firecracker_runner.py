#!/usr/bin/env python3
"""
Host-side Firecracker runner for Kriterion.

Invoked by kriterion/sandbox.py as:

    $KRITERION_FIRECRACKER_RUNNER <manifest.json>

Manifest fields (all provided by sandbox.py):

    payload      - host path to payload.py to execute inside the VM
    result       - host path where this runner must write result.json
    kernel       - host path to vmlinux kernel image
    rootfs       - host path to runner rootfs ext4 image (read-only)
    timeout_ms   - guest payload budget in milliseconds
    network      - "forbidden" (enforced: no network interface is attached)
    filesystem   - "restricted"

Exit codes:
    0  - guest result.json was retrieved and written to manifest["result"]
         (sandbox.py MUST read result.json to determine PASS/FAIL/ERROR)
    2  - payload image creation failed
    3  - Firecracker API socket did not appear
    4  - Firecracker API configuration failed
    5  - VM timed out
    6  - Guest did not write result.json
    1  - usage / manifest error

CRITICAL: exit code 0 means the host-side infrastructure succeeded and
result.json was recovered.  It does NOT mean the payload PASSed.
The sandbox.py caller is responsible for reading result.json["status"].
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Unix-socket HTTP client for the Firecracker management API
# ---------------------------------------------------------------------------

class _UnixSocketHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection that speaks over a Unix domain socket."""

    def __init__(self, sock_path: str) -> None:
        super().__init__("localhost")
        self._sock_path = sock_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self._sock_path)
        self.sock = sock


def _fc_put(sock_path: str, path: str, body: dict) -> None:
    """Issue a single PUT to the Firecracker management API and assert success."""
    conn = _UnixSocketHTTPConnection(sock_path)
    data = json.dumps(body).encode()
    conn.request("PUT", path, body=data, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    if resp.status not in (200, 204):
        raise RuntimeError(
            f"Firecracker API PUT {path} → HTTP {resp.status}: {raw.decode('utf-8', errors='replace')[:400]}"
        )


def _wait_for_socket(path: str, timeout_s: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if Path(path).exists():
            return
        time.sleep(0.05)
    raise RuntimeError(f"Firecracker API socket did not appear within {timeout_s}s: {path}")


# ---------------------------------------------------------------------------
# ext4 payload image helpers (no root/mount required — uses debugfs)
# ---------------------------------------------------------------------------

def _create_payload_image(image_path: Path, payload_src: Path, size_mib: int = 8) -> None:
    """
    Create a small ext4 image and inject payload.py using debugfs.

    Requires: dd, mkfs.ext4, debugfs (all in e2fsprogs on Ubuntu).
    No root or loop-mount is needed.
    """
    subprocess.run(
        ["dd", "if=/dev/zero", f"of={image_path}", "bs=1M", f"count={size_mib}"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["mkfs.ext4", "-F", str(image_path)],
        check=True,
        capture_output=True,
    )
    # debugfs write <host_file> <guest_path>
    subprocess.run(
        ["debugfs", "-w", str(image_path), "-R", f"write {payload_src} payload.py"],
        check=True,
        capture_output=True,
    )


def _read_result_from_image(image_path: Path) -> dict | None:
    """
    Extract result.json from the payload ext4 image using debugfs cat.

    Returns the parsed dict, or None if the file is absent or unparseable.
    """
    proc = subprocess.run(
        ["debugfs", str(image_path), "-R", "cat result.json"],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    text = proc.stdout.decode("utf-8", errors="replace")
    # debugfs may emit warnings on stdout; locate the first JSON object.
    idx = text.find("{")
    if idx < 0:
        return None
    try:
        return json.loads(text[idx:])
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: kriterion-firecracker-runner <manifest.json>", file=sys.stderr)
        return 1

    manifest_path = Path(sys.argv[1])
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Cannot read manifest: {exc}", file=sys.stderr)
        return 1

    payload_src = Path(manifest["payload"])
    result_dst = Path(manifest["result"])
    kernel = manifest["kernel"]
    rootfs = manifest["rootfs"]
    timeout_ms = int(manifest.get("timeout_ms", 30_000))

    # Wall-clock budget for the whole Firecracker lifecycle:
    # payload budget + VM boot/shutdown overhead (90 s is generous but safe).
    wall_timeout_s = max(30.0, timeout_ms / 1000 + 90.0)

    with tempfile.TemporaryDirectory(prefix="fc_run_") as tmp:
        tmp_path = Path(tmp)
        api_sock = str(tmp_path / "fc.sock")
        payload_img = tmp_path / "payload.ext4"

        # 1. Build payload disk image
        try:
            _create_payload_image(payload_img, payload_src)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
            print(f"Payload image creation failed: {stderr[:400]}", file=sys.stderr)
            return 2

        # 2. Start Firecracker (it listens on the API socket and waits for config)
        fc_proc = subprocess.Popen(
            ["firecracker", "--api-sock", api_sock],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            _wait_for_socket(api_sock, timeout_s=10.0)
        except RuntimeError as exc:
            fc_stderr = b""
            try:
                fc_stderr = fc_proc.communicate(timeout=2)[1] or b""
            except Exception:
                fc_proc.kill()
            print(f"{exc}\nFirecracker stderr: {fc_stderr.decode('utf-8', errors='replace')[:300]}", file=sys.stderr)
            return 3

        # 3. Configure the VM via the Firecracker management API
        try:
            # Boot source
            _fc_put(api_sock, "/boot-source", {
                "kernel_image_path": kernel,
                "boot_args": "console=ttyS0 reboot=k panic=1 pci=off",
            })

            # Runner rootfs — root device, writable for the guest runtime.
            # Drive IDs must not contain hyphens (Firecracker v1.17 requirement).
            _fc_put(api_sock, "/drives/runner_rootfs", {
                "drive_id": "runner_rootfs",
                "path_on_host": rootfs,
                "is_root_device": True,
                "is_read_only": False,
            })

            # Payload disk — read-write so the guest can write result.json.
            _fc_put(api_sock, "/drives/payload", {
                "drive_id": "payload",
                "path_on_host": str(payload_img),
                "is_root_device": False,
                "is_read_only": False,
            })

            # Machine config — minimal resources sufficient for Python payload.
            _fc_put(
                api_sock, "/machine-config", {
                    "vcpu_count": 1, "mem_size_mib": 512, "smt": False,
                }
                )

            # No network interface is attached (network: "forbidden" in manifest).

            # Start the VM.
            _fc_put(api_sock, "/actions", {"action_type": "InstanceStart"})

        except Exception as exc:
            fc_proc.kill()
            print(f"Firecracker API configuration failed: {exc}", file=sys.stderr)
            return 4

        # 4. Wait for the guest result, not for the Firecracker process.
        #
        # Firecracker remains alive after the guest kernel halts, so waiting
        # for fc_proc.wait() causes a false host-side timeout.
        deadline = time.monotonic() + wall_timeout_s
        guest_result = None

        while time.monotonic() < deadline:
            guest_result = _read_result_from_image(payload_img)

            if guest_result is not None:
                break

            if fc_proc.poll() is not None:
                break

            time.sleep(0.2)

        if guest_result is None:
            if fc_proc.poll() is None:
                fc_proc.kill()

            stdout, stderr = fc_proc.communicate()

            print(
                f"Firecracker VM timed out after {wall_timeout_s:.0f}s "
                f"(payload timeout_ms={timeout_ms})",
                file=sys.stderr,
            )

            print(
                "===== FIRECRACKER STDOUT =====\n"
                + (stdout or b"").decode("utf-8", errors="replace")[-12000:],
                file=sys.stderr,
            )

            print(
                "===== FIRECRACKER STDERR =====\n"
                + (stderr or b"").decode("utf-8", errors="replace")[-12000:],
                file=sys.stderr,
            )

            return 5

        # Guest produced its result. Firecracker may still be alive because
        # a halted guest does not necessarily terminate the VMM.
        if fc_proc.poll() is None:
            fc_proc.kill()

        stdout, stderr = fc_proc.communicate()

        if guest_result is None:
            print(
                "Guest did not write result.json to the payload image.\n"
                f"Firecracker stderr: "
                f"{stderr.decode('utf-8', errors = 'replace')[-12000:]}", file = sys.stderr, )
            return 6

        # 6. Write result.json to the host path sandbox.py is watching
        result_dst.write_text(json.dumps(guest_result), encoding="utf-8")

    # Exit 0: infrastructure succeeded; sandbox.py MUST read result.json["status"].
    return 0


if __name__ == "__main__":
    sys.exit(main())
