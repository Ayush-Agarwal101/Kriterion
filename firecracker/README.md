# Firecracker Boundary

Kriterion routes sandbox-required evidence through `kriterion.sandbox`.

When the `firecracker` binary is present on `PATH` **and** the three
environment variables below are set, tests are executed inside a
micro-VM with no network access and an ephemeral ext4 payload drive.

When any prerequisite is absent, `execute_generated_code()` returns
`INSUFFICIENT_EVIDENCE` — sandbox-required tests produce an automatic
`BLOCK` decision.  This **fail-closed** behaviour is intentional: the
system never claims Firecracker isolation when it cannot provide it.

---

## Repository layout

```
firecracker/
  Dockerfile.rootfs    # builds the minimal Alpine + Python 3 guest image
  build_rootfs.sh      # script: produces assets/rootfs.ext4
  fetch_kernel.sh      # script: downloads and verifies assets/vmlinux
  assets/
    .gitkeep           # tracked; actual binaries are git-ignored
    vmlinux            # ← produced by fetch_kernel.sh   (NOT committed)
    rootfs.ext4        # ← produced by build_rootfs.sh   (NOT committed)
  runner/
    guest_init.sh      # PID-1 init inside the VM
    payload_runner.py  # executes payload.py, writes result.json
```

> **Never commit** `assets/vmlinux` or `assets/rootfs.ext4`.
> They are listed in `firecracker/.gitignore`.

---

## Required environment variables

| Variable | Purpose |
|---|---|
| `FIRECRACKER_KERNEL` | Absolute path to the `vmlinux` ELF kernel image |
| `FIRECRACKER_ROOTFS` | Absolute path to the guest rootfs `ext4` image |
| `KRITERION_FIRECRACKER_RUNNER` | Absolute path (or PATH name) of the host-side runner |

`kriterion/sandbox.py` reads these three variables at call time.
`kriterion/config.py` exposes `firecracker_kernel()`, `firecracker_rootfs()`,
`firecracker_runner()`, and `firecracker_configured()` as typed accessors.

---

## Host prerequisites

| Tool | Used by | Install (Ubuntu 22 / 24) |
|---|---|---|
| `firecracker` | sandbox.py availability check + VM launch | see below |
| `docker` ≥ 24 | `build_rootfs.sh` | `apt install docker.io` or Docker Engine |
| `curl` | `fetch_kernel.sh` | `apt install curl` |
| `dd`, `mkfs.ext4`, `debugfs` | `firecracker_runner.py` payload image | `apt install e2fsprogs` |

### Install Firecracker

```bash
# Download the latest Firecracker release bundle for x86_64
LATEST=$(curl -fsSLI -o /dev/null -w '%{url_effective}' \
    https://github.com/firecracker-microvm/firecracker/releases/latest \
  | xargs basename)

curl -fsSL \
    "https://github.com/firecracker-microvm/firecracker/releases/download/${LATEST}/firecracker-${LATEST}-x86_64.tgz" \
  | tar -xz --strip-components 1 "release-${LATEST}-x86_64/firecracker-${LATEST}-x86_64"

sudo install firecracker-${LATEST}-x86_64 /usr/local/bin/firecracker
firecracker --version
```

> **KVM access** — Firecracker requires `/dev/kvm`.
> On Ubuntu: `sudo usermod -aG kvm $USER` then log out and back in.
> On EC2: use an instance type with bare-metal or nested-virt support.

---

## One-time provisioning

Run these commands **once** from the repository root.  Both scripts are
idempotent and can be re-run to rebuild after changes to the runner files.

### 1 — Download the kernel

```bash
./firecracker/fetch_kernel.sh
```

Expected output (abbreviated):

```
==> Downloading Firecracker vmlinux ...
    URL: https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.8/x86_64/vmlinux-5.10.225
    SHA-256: <hash>
INFO: Pin this hash in firecracker/fetch_kernel.sh: FC_KERNEL_SHA256="<hash>"
==> Done.
    firecracker/assets/vmlinux

Export: export FIRECRACKER_KERNEL=/path/to/repo/firecracker/assets/vmlinux
```

After the first download, copy the printed hash into `fetch_kernel.sh`
as `FC_KERNEL_SHA256` to enable integrity verification on future runs.

### 2 — Build the guest rootfs

```bash
./firecracker/build_rootfs.sh
```

This requires Docker and takes 1–3 minutes on first run (Alpine layers
are cached afterward).  Expected output:

```
==> Building Kriterion Firecracker guest rootfs
[1/4] Building Docker image kriterion-fc-rootfs:build ...
[2/4] Exporting container filesystem ...
[3/4] Creating ext4 image (300 MiB) ...
[4/4] Verifying image contents ...
    /sbin/init              : present
    /sbin/payload_runner.py : present
==> Done.
    firecracker/assets/rootfs.ext4

Export for kriterion/sandbox.py:
    export FIRECRACKER_ROOTFS=/path/to/repo/firecracker/assets/rootfs.ext4
```

### 3 — Export environment variables

Add the following to your shell profile, `.env`, or CI environment:

```bash
REPO=$(pwd)   # must be the repository root
export FIRECRACKER_KERNEL="${REPO}/firecracker/assets/vmlinux"
export FIRECRACKER_ROOTFS="${REPO}/firecracker/assets/rootfs.ext4"
export KRITERION_FIRECRACKER_RUNNER="${REPO}/kriterion/firecracker_runner.py"
```

Verify:

```bash
python3 -c "
from kriterion.config import firecracker_configured
print('Firecracker configured:', firecracker_configured())
"
# Expected: Firecracker configured: True
```

---

## Smoke test

The smoke test runs a trivial Python assertion inside a real micro-VM.
It exercises the full path: payload image creation → VM boot → PID-1 init
→ Python payload → result.json recovery.

```bash
# From repository root (env vars must be set, see above)
python3 - << 'EOF'
import json, pathlib, tempfile, subprocess, sys

REPO = pathlib.Path(__file__).parent if "__file__" in dir() else pathlib.Path(".")

with tempfile.TemporaryDirectory(prefix="fc_smoke_") as tmp:
    tmp = pathlib.Path(tmp)
    payload = tmp / "payload.py"
    result  = tmp / "result.json"
    mf      = tmp / "manifest.json"

    payload.write_text("answer = 6 * 7\nassert answer == 42, f'got {answer}'\n")
    mf.write_text(json.dumps({
        "payload":    str(payload),
        "result":     str(result),
        "kernel":     str(pathlib.Path("firecracker/assets/vmlinux").resolve()),
        "rootfs":     str(pathlib.Path("firecracker/assets/rootfs.ext4").resolve()),
        "timeout_ms": 15000,
        "network":    "forbidden",
        "filesystem": "restricted",
    }))

    rc = subprocess.call(
        [sys.executable, "kriterion/firecracker_runner.py", str(mf)]
    )
    if rc != 0:
        print(f"Runner exited {rc}", file=sys.stderr)
        sys.exit(rc)

    r = json.loads(result.read_text())
    print(f"status : {r['status']}")
    print(f"detail : {r['detail']}")
    assert r["status"] == "PASS", f"Expected PASS, got {r['status']}: {r['detail']}"
    print("\n✓  Smoke test PASSED")
EOF
```

### Sandbox-level smoke test

This goes one level higher and exercises `sandbox.execute_generated_code`:

```bash
python3 -c "
from kriterion.sandbox import execute_generated_code
r = execute_generated_code('answer = 6 * 7', 'assert answer == 42', 15_000)
print('status :', r.status)
print('detail :', r.observed)
assert r.status.value == 'PASS'
print('✓  sandbox smoke test PASSED')
"
```

---

## Unit tests

```bash
pytest tests/test_firecracker_runner.py -v
```

The tests run **without** a Firecracker binary, KVM, or real kernel/rootfs.
All subprocess calls are mocked.  Expected output (abbreviated):

```
tests/test_firecracker_runner.py::TestPrerequisiteFailClosed::test_no_firecracker_binary PASSED
tests/test_firecracker_runner.py::TestPrerequisiteFailClosed::test_missing_kernel_env_var PASSED
...
tests/test_firecracker_runner.py::TestSandboxStatusMapping::test_pass_maps_to_status_pass PASSED
tests/test_firecracker_runner.py::TestSandboxStatusMapping::test_fail_maps_to_status_fail PASSED
...
== 30 passed in 0.xx s ==
```

---

## VM execution flow (reference)

```
host: sandbox.py
  └─ writes payload.py + manifest.json
  └─ subprocess: firecracker_runner.py <manifest.json>
       ├─ dd + mkfs.ext4 + debugfs  → payload.ext4  (payload.py injected)
       ├─ firecracker --api-sock /tmp/.../fc.sock
       ├─ PUT /boot-source  (kernel=vmlinux, boot_args=...)
       ├─ PUT /drives/runner_rootfs  (rootfs.ext4, is_root_device=True)   → /dev/vda
       ├─ PUT /drives/payload        (payload.ext4)                        → /dev/vdb
       ├─ PUT /machine-config  (1 vCPU, 512 MiB)
       └─ PUT /actions InstanceStart
            │
            ▼ inside VM (no network)
       kernel boots → /sbin/init (guest_init.sh, PID 1)
         ├─ mount /proc /sys /dev /dev/pts
         ├─ waits for /dev/vdb to appear
         ├─ mount /dev/vdb /mnt/payload
         ├─ python3 /sbin/payload_runner.py /mnt/payload
         │    ├─ subprocess: python3 /mnt/payload/payload.py  (30 s timeout)
         │    └─ writes /mnt/payload/result.json  {"status":"PASS|FAIL|ERROR",...}
         ├─ sync; umount /mnt/payload
         └─ echo o > /proc/sysrq-trigger  (power off)
            │
            ▼ back on host
       firecracker_runner.py polls debugfs → reads result.json from payload.ext4
       writes manifest["result"] (result.json) on the host
       exits 0

  sandbox.py reads result.json["status"] → maps to Status.PASS / .FAIL / .ERROR
```

---

## Rebuilding after guest code changes

When `firecracker/runner/guest_init.sh` or `firecracker/runner/payload_runner.py`
changes, rebuild the rootfs:

```bash
./firecracker/build_rootfs.sh
```

The kernel does **not** need to be re-downloaded for runner-only changes.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `INSUFFICIENT_EVIDENCE` | `firecracker` not on PATH or env vars unset | Run provisioning steps; verify `firecracker_configured()` |
| `Firecracker API socket did not appear` | KVM unavailable or binary version mismatch | Check `/dev/kvm` permissions; reinstall Firecracker |
| `payload device /dev/vdb did not appear` | Virtio-blk driver missing in kernel | Re-download kernel via `fetch_kernel.sh` |
| `payload.py not found` | `debugfs write` failed during image creation | Check `e2fsprogs` version; ensure `debugfs` is on PATH |
| `Guest did not write result.json` | Python 3 not installed in rootfs | Rebuild rootfs via `build_rootfs.sh` |
