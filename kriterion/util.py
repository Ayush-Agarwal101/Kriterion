from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def append_jsonl(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, sort_keys=True) + "\n")


def command_available(name: str) -> bool:
    candidates = [name]
    if os.name == "nt":
        candidates.append(name + ".exe")
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        for candidate in candidates:
            if (Path(directory) / candidate).exists():
                return True
    return False


def git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return None


EVALUATOR_VERSION = "0.2.0"


def environment() -> dict[str, Any]:
    return {
        "os": platform.platform(),
        "python_version": sys.version.split()[0],
        "evaluator_version": EVALUATOR_VERSION,
        "git_commit": git_commit(),
        "finch_available": command_available("finch"),
        "firecracker_available": command_available("firecracker"),
        "cedar_cli_available": command_available("cedar"),
        "opensearch_configured": bool(os.environ.get("OPENSEARCH_URL")),
    }