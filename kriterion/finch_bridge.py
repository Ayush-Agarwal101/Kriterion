from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Sequence


_WINDOWS_FINCH_DEFAULT = Path("/mnt/c/Program Files/Finch/bin/finch.exe")


def is_wsl() -> bool:
    if os.environ.get("WSL_INTEROP"):
        return True
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text(
            encoding="utf-8", errors="ignore"
        ).lower()
    except OSError:
        return False


def _windows_finch_exe() -> str | None:
    configured = os.environ.get("KRITERION_FINCH_EXE")
    if configured:
        return configured
    if _WINDOWS_FINCH_DEFAULT.exists():
        return str(_WINDOWS_FINCH_DEFAULT)
    return shutil.which("finch.exe")


def _to_windows_path(path: str | os.PathLike[str]) -> str:
    result = subprocess.run(
        ["wslpath", "-w", str(Path(path).resolve())],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"wslpath failed for {path}: {(result.stdout + result.stderr).strip()}"
        )
    return result.stdout.strip()


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def finch_available() -> bool:
    if is_wsl():
        return bool(_windows_finch_exe() and shutil.which("powershell.exe"))
    return shutil.which("finch") is not None


def run_finch(
    args: Sequence[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    capture_output: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str]:
    """
    Execute Finch.

    If a native `finch` executable is available, use the normal subprocess
    path. This preserves the existing unit-test seam and normal native Finch
    behavior.

    In WSL, when native `finch` is unavailable, delegate to the working
    Windows Finch executable through PowerShell. Finch therefore talks to its
    Windows-managed VM instead of trying to translate WSL paths internally.
    """
    from .util import command_available

    args = [str(x) for x in args]

    if command_available("finch"):
        return subprocess.run(
            ["finch", *args],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=capture_output,
            text=text,
            check=False,
        )

    if not is_wsl():
        return subprocess.run(
            ["finch", *args],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=capture_output,
            text=text,
            check=False,
        )

    exe = _windows_finch_exe()

    if not exe:
        raise FileNotFoundError(
            "Windows Finch executable not found. Expected "
            f"{_WINDOWS_FINCH_DEFAULT} or KRITERION_FINCH_EXE."
        )

    # WSL cannot directly execute the mounted Windows .exe path.
    # Use WSL's Windows command interop through cmd.exe.
    powershell = shutil.which("powershell.exe")
    if not powershell:
        raise FileNotFoundError("powershell.exe is not available from WSL.")

    windows_cwd = _to_windows_path(cwd or Path.cwd())
    call = " ".join(_ps_quote(x) for x in [exe, *args])
    script = (f"Set-Location -LiteralPath {_ps_quote(windows_cwd)}; "
              f"& {call}; "
              "exit $LASTEXITCODE")

    return subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output = capture_output, text = text, check = False, )


def run_finch_with_volume(
    args: Sequence[str],
    *,
    cwd: str | os.PathLike[str],
    host_volume_path: str | os.PathLike[str],
    container_volume_path: str,
) -> subprocess.CompletedProcess[str]:
    args = [str(x) for x in args]

    if not is_wsl():
        return run_finch(args, cwd=cwd)

    # If native Finch is somehow available inside WSL, preserve normal behavior.
    from .util import command_available
    if command_available("finch"):
        return run_finch(args, cwd=cwd)

    windows_host = _to_windows_path(host_volume_path)
    replaced = list(args)

    for i, value in enumerate(replaced):
        if value == "-v" and i + 1 < len(replaced):
            replaced[i + 1] = f"{windows_host}:{container_volume_path}"
            break
    else:
        raise ValueError("Finch volume mapping requires a -v argument.")

    return run_finch(replaced, cwd=cwd)
