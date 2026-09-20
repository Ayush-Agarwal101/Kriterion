from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


def ollama_base_url() -> str:
    return os.environ.get("KRITERION_OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).rstrip("/")


def finch_ollama_base_url() -> str:
    configured = os.environ.get("KRITERION_FINCH_OLLAMA_BASE_URL")
    if configured:
        return configured.rstrip("/")
    return _container_reachable_url(ollama_base_url())


def strands_ollama_model_id() -> str | None:
    value = os.environ.get("KRITERION_STRANDS_OLLAMA_MODEL")
    return value.strip() if value and value.strip() else None


def _container_reachable_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        return url.rstrip("/")

    port = f":{parsed.port}" if parsed.port else ""
    username = parsed.username or ""
    password = f":{parsed.password}" if parsed.password else ""
    auth = f"{username}{password}@" if username or password else ""
    netloc = f"{auth}host.docker.internal{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)).rstrip("/")


# ── Firecracker sandbox configuration ─────────────────────────────────────────
#
# kriterion/sandbox.py reads these three env vars directly; the functions
# below centralise the names so operators and tests reference a single source
# of truth.
#
# Typical .env / shell setup produced by the provisioning scripts:
#
#   export FIRECRACKER_KERNEL=$(pwd)/firecracker/assets/vmlinux
#   export FIRECRACKER_ROOTFS=$(pwd)/firecracker/assets/rootfs.ext4
#   export KRITERION_FIRECRACKER_RUNNER=$(pwd)/kriterion/firecracker_runner.py
#
# All three must be set for sandbox.py to route tests through Firecracker;
# when any is missing, execute_generated_code() returns INSUFFICIENT_EVIDENCE
# (fail-closed behaviour is intentional).


def firecracker_kernel() -> str | None:
    """
    Host path to the vmlinux kernel image for Firecracker guests.

    Set via the ``FIRECRACKER_KERNEL`` environment variable.
    Obtain the binary via ``./firecracker/fetch_kernel.sh``.
    """
    value = os.environ.get("FIRECRACKER_KERNEL", "").strip()
    return value or None


def firecracker_rootfs() -> str | None:
    """
    Host path to the guest rootfs ext4 image.

    Set via the ``FIRECRACKER_ROOTFS`` environment variable.
    Build the image via ``./firecracker/build_rootfs.sh``.
    """
    value = os.environ.get("FIRECRACKER_ROOTFS", "").strip()
    return value or None


def firecracker_runner() -> str | None:
    """
    Executable path for the host-side Firecracker runner.

    Set via the ``KRITERION_FIRECRACKER_RUNNER`` environment variable.
    Defaults to the bundled ``kriterion/firecracker_runner.py`` in normal
    deployments; override in tests to point at a mock runner.
    """
    value = os.environ.get("KRITERION_FIRECRACKER_RUNNER", "").strip()
    return value or None


def firecracker_configured() -> bool:
    """
    Return True only when all three Firecracker env vars are set and non-empty.

    Mirrors the exact gate that kriterion/sandbox.py enforces before it will
    attempt a VM-based test run.
    """
    return bool(firecracker_kernel() and firecracker_rootfs() and firecracker_runner())
