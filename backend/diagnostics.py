"""System-queried facts about a volume and its connection.

This gathers everything we can learn *without* running the benchmark: the drive's
identity, its USB link, SMART/health, TRIM state, and the filesystem's allocation
unit. analysis.py later fuses this with measured throughput to reach a verdict.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Optional

from . import drives, smart, usb, winutil
from .drives import Drive
from .smart import SmartInfo
from .usb import UsbLinkInfo


@dataclass
class DiagnosticsReport:
    drive: Optional[dict] = None
    usb: Optional[dict] = None
    smart: Optional[dict] = None
    trim_enabled: Optional[bool] = None
    allocation_unit: Optional[int] = None
    filesystem: Optional[str] = None
    notes: list = field(default_factory=list)


def trim_enabled() -> Optional[bool]:
    """Windows delete-notification (TRIM) state. 0 in fsutil output == enabled."""
    try:
        proc = winutil.run(["fsutil", "behavior", "query", "DisableDeleteNotify"])
    except Exception:
        return None
    out = proc.stdout or ""
    # Prefer the NTFS line; value 0 => TRIM enabled.
    m = re.search(r"NTFS\s+DisableDeleteNotify\s*=\s*(\d+)", out)
    if not m:
        m = re.search(r"DisableDeleteNotify\s*=\s*(\d+)", out)
    if not m:
        return None
    return m.group(1) == "0"


def allocation_unit(letter: str) -> Optional[int]:
    """Bytes-per-cluster for an NTFS volume (best effort)."""
    try:
        proc = winutil.run(["fsutil", "fsinfo", "ntfsinfo", f"{letter}:"])
    except Exception:
        return None
    m = re.search(r"Bytes Per Cluster\s*:\s*(\d+)", proc.stdout or "")
    return int(m.group(1)) if m else None


def collect(letter: str, drive: Optional[Drive] = None) -> DiagnosticsReport:
    letter = letter.upper()[:1]
    drive = drive or drives.get_drive(letter)
    report = DiagnosticsReport()
    if not drive:
        report.notes.append(f"Drive {letter}: not found.")
        return report

    report.drive = drive.to_dict()
    report.filesystem = drive.filesystem
    report.trim_enabled = trim_enabled()
    report.allocation_unit = allocation_unit(letter)

    # USB link (only meaningful for USB drives, but harmless otherwise).
    link: UsbLinkInfo = usb.analyze_usb_link(drive.disk_number)
    report.usb = asdict(link)

    # SMART / health.
    sm: SmartInfo = smart.get_smart(drive.disk_number)
    report.smart = asdict(sm)

    if drive.bus_type and drive.bus_type.upper() == "USB" and not link.matched:
        report.notes.append("USB drive detected but its port record could not be "
                             "read; link tier will be inferred from throughput.")
    return report
