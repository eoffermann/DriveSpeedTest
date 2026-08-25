"""S.M.A.R.T. / drive-health readout with graceful degradation.

Order of preference:
  1. smartctl (smartmontools) if installed -- richest data, and the only tool
     that reliably reaches SMART *through* a USB-SATA/USB-NVMe bridge via its
     `-d sat` / `-d auto` translation.
  2. Get-StorageReliabilityCounter -- built into Windows, but the CIM resource is
     admin-gated and thin over USB bridges.

If neither yields data, we return a structured "unavailable" result telling the
UI whether elevation would help. This never blocks the benchmark.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

from . import winutil

_SMARTCTL_CANDIDATES = [
    r"C:\Program Files\smartmontools\bin\smartctl.exe",
    r"C:\Program Files (x86)\smartmontools\bin\smartctl.exe",
]


@dataclass
class SmartInfo:
    available: bool = False
    source: str = "none"           # smartctl | reliability-counter | none
    needs_admin: bool = False
    temperature_c: Optional[float] = None
    power_on_hours: Optional[int] = None
    percent_used: Optional[float] = None      # SSD endurance used (0-100)
    reallocated_sectors: Optional[int] = None
    pending_sectors: Optional[int] = None
    read_errors: Optional[int] = None
    write_errors: Optional[int] = None
    health: Optional[str] = None
    attributes: List[dict] = field(default_factory=list)  # [{name,value}] for the UI table
    message: str = ""


def _find_smartctl() -> Optional[str]:
    found = shutil.which("smartctl")
    if found:
        return found
    return next((p for p in _SMARTCTL_CANDIDATES if os.path.exists(p)), None)


def _from_smartctl(disk_number: int, exe: str) -> Optional[SmartInfo]:
    device = f"\\\\.\\PhysicalDrive{disk_number}"
    for dtype in ("sat", "auto", "scsi"):
        try:
            proc = winutil.run([exe, "-j", "-d", dtype, "-a", device], timeout=20)
        except subprocess.TimeoutExpired:
            continue
        if not proc.stdout:
            continue
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            continue
        # smartctl sets exit bits; presence of device+identity means it talked.
        if not data.get("device") and not data.get("model_name"):
            continue
        info = SmartInfo(available=True, source="smartctl")
        temp = data.get("temperature", {})
        info.temperature_c = temp.get("current")
        poh = data.get("power_on_time", {})
        info.power_on_hours = poh.get("hours")
        health = data.get("smart_status", {})
        info.health = "PASSED" if health.get("passed") else ("FAILED" if health else None)

        nvme = data.get("nvme_smart_health_information_log")
        if nvme:
            info.percent_used = nvme.get("percentage_used")
            info.temperature_c = info.temperature_c or nvme.get("temperature")
            info.power_on_hours = info.power_on_hours or nvme.get("power_on_hours")
            info.attributes = [{"name": k, "value": v} for k, v in nvme.items()
                               if isinstance(v, (int, float, str))]
        ata = data.get("ata_smart_attributes", {}).get("table")
        if ata:
            for a in ata:
                name = a.get("name", "")
                raw = a.get("raw", {}).get("value")
                info.attributes.append({"name": name, "value": raw})
                low = name.lower()
                if "reallocated_sector" in low:
                    info.reallocated_sectors = raw
                elif "current_pending" in low:
                    info.pending_sectors = raw
                elif "wear_leveling" in low or "percent_lifetime" in low or "ssd_life" in low:
                    info.percent_used = raw
        if not info.attributes:
            continue
        return info
    return None


_RC_SCRIPT = r"""
$pd = Get-PhysicalDisk | Where-Object {{ $_.DeviceId -eq '{n}' }} | Select-Object -First 1
if(-not $pd){{ '{{}}' ; exit }}
$rc = $pd | Get-StorageReliabilityCounter -ErrorAction Stop
[PSCustomObject]@{{
  temperature = $rc.Temperature
  powerOnHours = $rc.PowerOnHours
  wear = $rc.Wear
  readErrors = $rc.ReadErrorsTotal
  writeErrors = $rc.WriteErrorsTotal
  health = [string]$pd.HealthStatus
}} | ConvertTo-Json
"""


def _from_reliability_counter(disk_number: int) -> SmartInfo:
    proc = winutil.powershell(_RC_SCRIPT.format(n=disk_number))
    stderr = (proc.stderr or "")
    denied = ("PermissionDenied" in stderr or "Access to a CIM" in stderr
              or "not available to the client" in stderr)
    out = (proc.stdout or "").strip()
    if denied and not out:
        return SmartInfo(
            available=False, source="reliability-counter",
            needs_admin=not winutil.is_admin(),
            message="Windows blocked SMART access. Re-launch elevated (Run as "
                    "administrator), or install smartmontools for USB-bridge SMART.",
        )
    try:
        data = json.loads(out) if out else {}
    except json.JSONDecodeError:
        data = {}
    if not data:
        return SmartInfo(
            available=False, source="reliability-counter",
            needs_admin=not winutil.is_admin(),
            message="No SMART/reliability data exposed for this drive. USB bridges "
                    "often hide it; smartmontools with '-d sat' may still read it.",
        )
    info = SmartInfo(available=True, source="reliability-counter")
    info.temperature_c = data.get("temperature")
    info.power_on_hours = data.get("powerOnHours")
    info.percent_used = data.get("wear")
    info.read_errors = data.get("readErrors")
    info.write_errors = data.get("writeErrors")
    info.health = data.get("health")
    info.attributes = [
        {"name": "Temperature (C)", "value": info.temperature_c},
        {"name": "Power-on hours", "value": info.power_on_hours},
        {"name": "Wear (%)", "value": info.percent_used},
        {"name": "Read errors (total)", "value": info.read_errors},
        {"name": "Write errors (total)", "value": info.write_errors},
    ]
    return info


def get_smart(disk_number: Optional[int]) -> SmartInfo:
    if disk_number is None:
        return SmartInfo(message="No physical disk number for this volume.")
    exe = _find_smartctl()
    if exe:
        info = _from_smartctl(disk_number, exe)
        if info and info.available:
            return info
    return _from_reliability_counter(disk_number)
