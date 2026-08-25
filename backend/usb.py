"""Read the *negotiated* USB link speed for a drive -- the single most useful
signal for telling "the drive is slow" apart from "the connection is slow".

A drive rated 2100 MB/s that negotiated only USB 3.0 (5 Gbps, ~450 MB/s real)
or fell back to USB 2.0 (480 Mbps, ~40 MB/s) is being throttled by the port,
cable, or a bad handshake -- not by the flash. So we ask Windows what speed each
USB device actually negotiated.

Method (the one USBView uses): enumerate every USB hub via SetupAPI, open each
hub, and for every downstream port issue
``IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX`` (device speed: Low/Full/High/
Super) plus ``..._EX_V2`` (SuperSpeed vs SuperSpeed+). Match the device to the
target drive by USB VID/PID, which we resolve from the disk's PnP parent.

Everything here is wrapped so that if SetupAPI/DeviceIoControl misbehaves we fall
back to reporting the host controllers and let the analysis layer infer the link
tier from measured throughput. It never raises to the caller.
"""

from __future__ import annotations

import ctypes
import re
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import winutil

# --- USB device speed enum (IOCTL_..._EX) ------------------------------------
SPEED_LOW, SPEED_FULL, SPEED_HIGH, SPEED_SUPER = 0, 1, 2, 3

# --- realistic usable throughput ceilings per link tier (decimal MB/s) -------
# Raw line rate minus 8b/10b or 128b/132b encoding and protocol/bridge overhead.
CEILING_USB2 = 42.0       # 480 Mbps High-Speed
CEILING_USB3_GEN1 = 450.0  # 5 Gbps SuperSpeed
CEILING_USB3_GEN2 = 1050.0  # 10 Gbps SuperSpeedPlus (single lane)
CEILING_USB3_GEN2X2 = 2100.0  # 20 Gbps SuperSpeedPlus (dual lane)


@dataclass
class UsbDevice:
    vid: int
    pid: int
    speed_rank: int          # SPEED_* enum from IOCTL_..._EX (unreliable for SS)
    max_packet0: int          # EP0 max packet exponent; 9 (==512B) => operating at SuperSpeed
    bcd_usb: int              # device's max USB version capability (e.g. 0x0320)
    superspeed_plus: bool     # operating at SuperSpeedPlus, per EX_V2 (if supported)
    v2_supported: bool        # whether IOCTL_..._EX_V2 answered on this hub
    hub: bool


@dataclass
class UsbLinkInfo:
    matched: bool = False
    negotiated: str = "Unknown"
    ceiling_mbps: Optional[float] = None
    operating_superspeed: bool = False   # link is 5 Gbps SuperSpeed or faster
    superspeed_plus: bool = False         # 10/20 Gbps (confirmed by API)
    inferred: bool = False                # exact tier inferred, not API-confirmed
    vid: Optional[int] = None
    pid: Optional[int] = None
    bcd_usb: Optional[int] = None
    controllers: List[str] = field(default_factory=list)
    best_controller_tier: str = "Unknown"
    note: str = ""


# --- ctypes plumbing ---------------------------------------------------------
_setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

GUID_DEVINTERFACE_USB_HUB = "{F18A0E88-C30C-11D0-8815-00A0C906BED8}"

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 1
FILE_SHARE_WRITE = 2
OPEN_EXISTING = 3

# CTL_CODE(FILE_DEVICE_USB=0x22, func, METHOD_BUFFERED=0, FILE_ANY_ACCESS=0)
def _ctl(func: int) -> int:
    return (0x22 << 16) | (func << 2)

IOCTL_USB_GET_NODE_INFORMATION = _ctl(258)
IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX = _ctl(274)
IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX_V2 = _ctl(704)


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, s: str) -> "GUID":
        s = s.strip("{}")
        p = s.split("-")
        g = cls()
        g.Data1 = int(p[0], 16)
        g.Data2 = int(p[1], 16)
        g.Data3 = int(p[2], 16)
        rest = p[3] + p[4]
        for i in range(8):
            g.Data4[i] = int(rest[i * 2:i * 2 + 2], 16)
        return g


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.POINTER(ctypes.c_ulong)),
    ]


class USB_DEVICE_DESCRIPTOR(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("bLength", ctypes.c_ubyte),
        ("bDescriptorType", ctypes.c_ubyte),
        ("bcdUSB", ctypes.c_ushort),
        ("bDeviceClass", ctypes.c_ubyte),
        ("bDeviceSubClass", ctypes.c_ubyte),
        ("bDeviceProtocol", ctypes.c_ubyte),
        ("bMaxPacketSize0", ctypes.c_ubyte),
        ("idVendor", ctypes.c_ushort),
        ("idProduct", ctypes.c_ushort),
        ("bcdDevice", ctypes.c_ushort),
        ("iManufacturer", ctypes.c_ubyte),
        ("iProduct", ctypes.c_ubyte),
        ("iSerialNumber", ctypes.c_ubyte),
        ("bNumConfigurations", ctypes.c_ubyte),
    ]


class USB_NODE_CONNECTION_INFORMATION_EX(ctypes.Structure):
    # Only the fields up to DeviceIsHub are read; those offsets are identical
    # whether packed or default-aligned, so _pack_=1 is safe here.
    _pack_ = 1
    _fields_ = [
        ("ConnectionIndex", ctypes.c_ulong),
        ("DeviceDescriptor", USB_DEVICE_DESCRIPTOR),
        ("CurrentConfigurationValue", ctypes.c_ubyte),
        ("Speed", ctypes.c_ubyte),
        ("DeviceIsHub", ctypes.c_ubyte),
        ("DeviceAddress", ctypes.c_ushort),
        ("NumberOfOpenPipes", ctypes.c_ulong),
        ("ConnectionStatus", ctypes.c_ulong),
        ("_pad", ctypes.c_ubyte * 256),   # room for PipeList
    ]


class USB_NODE_CONNECTION_INFORMATION_EX_V2(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("ConnectionIndex", ctypes.c_ulong),
        ("Length", ctypes.c_ulong),
        ("SupportedUsbProtocols", ctypes.c_ulong),
        ("Flags", ctypes.c_ulong),
    ]


# Node information: we only need the hub's port count.
class USB_HUB_DESCRIPTOR(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("bDescriptorLength", ctypes.c_ubyte),
        ("bDescriptorType", ctypes.c_ubyte),
        ("bNumberOfPorts", ctypes.c_ubyte),
        ("wHubCharacteristics", ctypes.c_ushort),
        ("bPowerOnToPowerGood", ctypes.c_ubyte),
        ("bHubControlCurrent", ctypes.c_ubyte),
        ("bRemoveAndPowerMask", ctypes.c_ubyte * 64),
    ]


class USB_NODE_INFORMATION(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("NodeType", ctypes.c_ulong),
        ("HubDescriptor", USB_HUB_DESCRIPTOR),
        ("HubIsBusPowered", ctypes.c_ubyte),
    ]


_setupapi.SetupDiGetClassDevsW.argtypes = [
    ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
_setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
_setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wintypes.HANDLE, wintypes.LPVOID, ctypes.POINTER(GUID), wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
_setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
_setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), wintypes.LPVOID,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
_setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
_setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

_k32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.DeviceIoControl.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
    wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
_k32.DeviceIoControl.restype = wintypes.BOOL
_k32.CloseHandle.argtypes = [wintypes.HANDLE]


def _enum_hub_paths() -> List[str]:
    guid = GUID.from_string(GUID_DEVINTERFACE_USB_HUB)
    hdev = _setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if hdev == INVALID_HANDLE_VALUE:
        return []
    paths: List[str] = []
    try:
        i = 0
        while True:
            ifdata = SP_DEVICE_INTERFACE_DATA()
            ifdata.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not _setupapi.SetupDiEnumDeviceInterfaces(
                    hdev, None, ctypes.byref(guid), i, ctypes.byref(ifdata)):
                break
            i += 1
            req = wintypes.DWORD(0)
            _setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, ctypes.byref(ifdata), None, 0, ctypes.byref(req), None)
            if req.value == 0:
                continue
            buf = ctypes.create_string_buffer(req.value)
            # SP_DEVICE_INTERFACE_DETAIL_DATA_W.cbSize = 8 on 64-bit Windows.
            ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = 8
            if _setupapi.SetupDiGetDeviceInterfaceDetailW(
                    hdev, ctypes.byref(ifdata), buf, req.value, None, None):
                path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
                paths.append(path)
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return paths


def _open(path: str) -> Optional[int]:
    h = _k32.CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                         None, OPEN_EXISTING, 0, None)
    if h == INVALID_HANDLE_VALUE or h is None:
        return None
    return h


def _hub_port_count(handle: int) -> int:
    info = USB_NODE_INFORMATION()
    ret = wintypes.DWORD(0)
    ok = _k32.DeviceIoControl(
        handle, IOCTL_USB_GET_NODE_INFORMATION,
        ctypes.byref(info), ctypes.sizeof(info),
        ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(ret), None)
    if not ok:
        return 0
    return info.HubDescriptor.bNumberOfPorts


def _port_device(handle: int, port: int) -> Optional[UsbDevice]:
    ci = USB_NODE_CONNECTION_INFORMATION_EX()
    ci.ConnectionIndex = port
    ret = wintypes.DWORD(0)
    ok = _k32.DeviceIoControl(
        handle, IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX,
        ctypes.byref(ci), ctypes.sizeof(ci),
        ctypes.byref(ci), ctypes.sizeof(ci), ctypes.byref(ret), None)
    if not ok:
        return None
    # ConnectionStatus 1 == DeviceConnected
    if ci.ConnectionStatus != 1:
        return None
    dev = UsbDevice(
        vid=ci.DeviceDescriptor.idVendor,
        pid=ci.DeviceDescriptor.idProduct,
        speed_rank=ci.Speed,
        max_packet0=ci.DeviceDescriptor.bMaxPacketSize0,
        bcd_usb=ci.DeviceDescriptor.bcdUSB,
        superspeed_plus=False,
        v2_supported=False,
        hub=bool(ci.DeviceIsHub),
    )
    # EX.Speed misreports SuperSpeed as High on some xHCI stacks, so always try
    # EX_V2, which -- when supported -- authoritatively reports SuperSpeed(+).
    v2 = USB_NODE_CONNECTION_INFORMATION_EX_V2()
    v2.ConnectionIndex = port
    v2.Length = ctypes.sizeof(v2)
    v2.SupportedUsbProtocols = 0
    r2 = wintypes.DWORD(0)
    if _k32.DeviceIoControl(
            handle, IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX_V2,
            ctypes.byref(v2), ctypes.sizeof(v2),
            ctypes.byref(v2), ctypes.sizeof(v2), ctypes.byref(r2), None):
        dev.v2_supported = True
        # bit 2 (0x04) = DeviceIsOperatingAtSuperSpeedPlusOrHigher
        dev.superspeed_plus = bool(v2.Flags & 0x04)
    return dev


def _enumerate_devices() -> List[UsbDevice]:
    devices: List[UsbDevice] = []
    for path in _enum_hub_paths():
        h = _open(path)
        if h is None:
            continue
        try:
            for port in range(1, _hub_port_count(h) + 1):
                d = _port_device(h, port)
                if d and not (d.vid == 0 and d.pid == 0):
                    devices.append(d)
        finally:
            _k32.CloseHandle(h)
    return devices


def _target_vid_pid(disk_number: int) -> Optional[Tuple[int, int]]:
    """Resolve the USB VID/PID for a physical disk via its PnP parent chain."""
    script = (
        f"$d = Get-CimInstance Win32_DiskDrive | Where-Object {{ $_.Index -eq {disk_number} }};"
        "if(-not $d){return};"
        "$id = $d.PNPDeviceID;"
        "$p = (Get-PnpDeviceProperty -InstanceId $id -KeyName 'DEVPKEY_Device_Parent' -ErrorAction SilentlyContinue).Data;"
        "[PSCustomObject]@{ self=$id; parent=$p } | ConvertTo-Json"
    )
    data = winutil.powershell_json(script)
    if not data:
        return None
    for field_val in (data.get("parent"), data.get("self")):
        if not field_val:
            continue
        m = re.search(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})", str(field_val))
        if m:
            return int(m.group(1), 16), int(m.group(2), 16)
    return None


def _controllers() -> List[str]:
    data = winutil.powershell_json(
        "Get-PnpDevice -Class USB -PresentOnly -ErrorAction SilentlyContinue | "
        "Where-Object { $_.FriendlyName -match 'Host Controller' } | "
        "Select-Object -ExpandProperty FriendlyName | ConvertTo-Json")
    return [str(x) for x in winutil.as_list(data)]


def _controller_tier(controllers: List[str]) -> str:
    text = " ".join(controllers).lower()
    if "usb4" in text or "20g" in text:
        return "USB4 / 20 Gbps"
    if "3.2" in text or "3.1" in text or "3.10" in text:
        return "USB 3.1/3.2 (10-20 Gbps)"
    if "3.0" in text or "xhci" in text or "extensible" in text:
        return "USB 3.0 (5 Gbps)"
    if "2.0" in text or "enhanced" in text:
        return "USB 2.0 (480 Mbps)"
    return "Unknown"


def _describe(dev: UsbDevice) -> Tuple[str, float, bool, bool]:
    """Return (label, ceiling_mbps, operating_superspeed, inferred).

    An EP0 max-packet exponent of 9 (512-byte packets) is only used when a device
    is *actually operating* at SuperSpeed -- a USB 3 device that falls back to
    USB 2.0 re-enumerates with 64-byte EP0. So max_packet0 == 9 is a reliable
    "this link is SuperSpeed" signal even when EX.Speed lies and EX_V2 is absent.
    """
    operating_ss = dev.max_packet0 == 9 or dev.speed_rank == SPEED_SUPER
    if operating_ss:
        if dev.v2_supported:
            if dev.superspeed_plus:
                return "USB 3.2 Gen2/2x2 SuperSpeed+ (10-20 Gbps)", CEILING_USB3_GEN2, True, False
            return "USB 3.0/3.1 Gen1 SuperSpeed (5 Gbps)", CEILING_USB3_GEN1, True, False
        # EX_V2 not supported by this hub driver: infer the tier from capability.
        if dev.bcd_usb >= 0x0310:
            return "SuperSpeed, Gen2-class device (link 5-10+ Gbps)", CEILING_USB3_GEN2, True, True
        return "SuperSpeed (5 Gbps)", CEILING_USB3_GEN1, True, True
    if dev.speed_rank == SPEED_HIGH:
        return "USB 2.0 High-Speed (480 Mbps)", CEILING_USB2, False, False
    if dev.speed_rank == SPEED_FULL:
        return "USB 1.1 Full-Speed (12 Mbps)", 1.2, False, False
    return "USB 1.0 Low-Speed (1.5 Mbps)", 0.15, False, False


def analyze_usb_link(disk_number: Optional[int]) -> UsbLinkInfo:
    """Best-effort negotiated USB link report for the given physical disk."""
    info = UsbLinkInfo()
    try:
        info.controllers = _controllers()
        info.best_controller_tier = _controller_tier(info.controllers)
    except Exception:
        pass

    if disk_number is None:
        info.note = "No physical disk number; cannot match a USB device."
        return info

    try:
        target = _target_vid_pid(disk_number)
    except Exception:
        target = None
    if not target:
        info.note = "Drive is not on a USB bus, or its USB VID/PID could not be resolved."
        return info

    info.vid, info.pid = target
    try:
        devices = _enumerate_devices()
    except Exception as exc:  # pragma: no cover - defensive
        info.note = f"USB tree walk unavailable ({exc}); link tier inferred elsewhere."
        return info

    match = next((d for d in devices if d.vid == target[0] and d.pid == target[1]), None)
    if not match:
        info.note = ("Target USB device enumerated but no matching port record; "
                     "link tier inferred from throughput and controllers.")
        return info

    info.matched = True
    info.bcd_usb = match.bcd_usb
    info.superspeed_plus = match.superspeed_plus and match.v2_supported
    info.negotiated, info.ceiling_mbps, info.operating_superspeed, info.inferred = _describe(match)
    if info.inferred:
        info.note = ("Exact USB generation inferred (hub driver lacks the EX_V2 "
                     "query); measured throughput refines the true link tier.")
    return info
