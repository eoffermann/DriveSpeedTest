"""Small Windows helpers shared across the diagnostics modules."""

from __future__ import annotations

import ctypes
import json
import subprocess
from typing import Any, List, Optional

_CREATE_NO_WINDOW = 0x08000000


def is_admin() -> bool:
    """True if the current process is elevated (needed for SMART on many drives)."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run(cmd: List[str], timeout: float = 20.0) -> subprocess.CompletedProcess:
    """Run a command without popping a console window; never raises on non-zero."""
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        creationflags=_CREATE_NO_WINDOW,
    )


def powershell(script: str, timeout: float = 25.0) -> subprocess.CompletedProcess:
    return run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", script],
        timeout=timeout,
    )


def powershell_json(script: str, timeout: float = 25.0) -> Optional[Any]:
    """Run a PowerShell snippet that ends in ConvertTo-Json; return parsed data.

    Normalizes PowerShell's habit of emitting a bare object (not a list) when a
    query returns exactly one row: callers that expect a list always get one.
    """
    try:
        proc = powershell(script, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    out = (proc.stdout or "").strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def as_list(data: Any) -> List[Any]:
    if data is None:
        return []
    return data if isinstance(data, list) else [data]
