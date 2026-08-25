"""Enumerate mountable volumes and join them to their physical-disk metadata.

One PowerShell round-trip stitches together Get-Volume (letter, filesystem,
capacity/free), Get-Partition (volume -> disk number), Get-Disk (model, firmware,
bus type, health, serial) and Get-PhysicalDisk (media type: SSD vs HDD). The disk
number is the join key later used by usb.py and smart.py.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import List, Optional

from . import winutil

_ENUM_SCRIPT = r"""
$vols = Get-Volume | Where-Object { $_.DriveLetter }
$out = foreach ($v in $vols) {
  $part = Get-Partition -DriveLetter $v.DriveLetter -ErrorAction SilentlyContinue | Select-Object -First 1
  $disk = $null; $pd = $null
  if ($part) {
    $disk = Get-Disk -Number $part.DiskNumber -ErrorAction SilentlyContinue
    $pd = Get-PhysicalDisk | Where-Object { $_.DeviceId -eq [string]$part.DiskNumber } | Select-Object -First 1
  }
  [PSCustomObject]@{
    letter     = [string]$v.DriveLetter
    label      = $v.FileSystemLabel
    filesystem = $v.FileSystem
    total      = [int64]$v.Size
    free       = [int64]$v.SizeRemaining
    diskNumber = if ($part) { [int]$part.DiskNumber } else { $null }
    model      = if ($disk) { $disk.FriendlyName } else { $null }
    busType    = if ($disk) { [string]$disk.BusType } else { $null }
    mediaType  = if ($pd)   { [string]$pd.MediaType } else { $null }
    firmware   = if ($disk) { $disk.FirmwareVersion } else { $null }
    health     = if ($disk) { [string]$disk.HealthStatus } else { $null }
    serial     = if ($disk) { ($disk.SerialNumber -as [string]).Trim() } else { $null }
  }
}
$out | ConvertTo-Json -Depth 4
"""


@dataclass
class Drive:
    letter: str
    label: Optional[str] = None
    filesystem: Optional[str] = None
    total: int = 0
    free: int = 0
    disk_number: Optional[int] = None
    model: Optional[str] = None
    bus_type: Optional[str] = None
    media_type: Optional[str] = None
    firmware: Optional[str] = None
    health: Optional[str] = None
    serial: Optional[str] = None
    is_system: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _system_letter() -> str:
    return os.environ.get("SystemDrive", "C:").rstrip(":\\/").upper()[:1]


def list_drives() -> List[Drive]:
    data = winutil.powershell_json(_ENUM_SCRIPT)
    system = _system_letter()
    drives: List[Drive] = []
    for row in winutil.as_list(data):
        letter = (row.get("letter") or "").upper()[:1]
        if not letter:
            continue
        drives.append(Drive(
            letter=letter,
            label=row.get("label") or None,
            filesystem=row.get("filesystem"),
            total=int(row.get("total") or 0),
            free=int(row.get("free") or 0),
            disk_number=row.get("diskNumber"),
            model=(row.get("model") or "").strip() or None,
            bus_type=row.get("busType"),
            media_type=row.get("mediaType"),
            firmware=(row.get("firmware") or "").strip() or None,
            health=row.get("health"),
            serial=(row.get("serial") or "").strip() or None,
            is_system=(letter == system),
        ))
    drives.sort(key=lambda d: d.letter)
    return drives


def get_drive(letter: str) -> Optional[Drive]:
    letter = letter.upper()[:1]
    return next((d for d in list_drives() if d.letter == letter), None)
