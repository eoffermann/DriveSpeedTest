"""Unbuffered, sector-aligned disk I/O for Windows.

Why this exists
---------------
The original tool measured the *OS write cache* and *RAM page cache*, not the
drive. Any benchmark that uses ordinary buffered ``open()`` and skips ``fsync``
reports fantasy numbers -- often several GB/s -- because the data never touched
the device during timing.

This module opens files with ``CreateFileW`` and the flags
``FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH`` so every read and write goes
straight to the physical device, bypassing the cache in *both* directions. That
is the only way to get numbers you can honestly compare to a marketing claim.

Constraints imposed by FILE_FLAG_NO_BUFFERING (all handled here):
  * I/O offsets and lengths must be a multiple of the volume sector size.
  * The user-space buffer address must be sector-aligned.

We use a fixed 4096-byte granularity for buffers and I/O sizes. 4096 is a
multiple of every common sector size (512 and 4K "Advanced Format"), and
``VirtualAlloc`` returns page-aligned (4096) memory, so both constraints are
satisfied universally without probing the physical sector size.

If the unbuffered path cannot be used (exotic/network filesystem), callers can
fall back to :class:`BufferedFallbackFile`, which still calls ``fsync`` so writes
are at least durable -- but it cannot defeat the read cache, so results are
flagged lower-confidence by the benchmark layer.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

# --- 4096-byte alignment satisfies both 512B and 4K-sector drives ------------
ALIGN = 4096

# --- Win32 constants ---------------------------------------------------------
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
CREATE_ALWAYS = 2
OPEN_EXISTING = 3
FILE_FLAG_NO_BUFFERING = 0x20000000
FILE_FLAG_WRITE_THROUGH = 0x80000000
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_BEGIN = 0
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

MEM_COMMIT = 0x00001000
MEM_RESERVE = 0x00002000
MEM_RELEASE = 0x00008000
PAGE_READWRITE = 0x04

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

_k32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
_k32.CreateFileW.restype = wintypes.HANDLE

_k32.WriteFile.argtypes = [
    wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
]
_k32.WriteFile.restype = wintypes.BOOL

_k32.ReadFile.argtypes = [
    wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
]
_k32.ReadFile.restype = wintypes.BOOL

_k32.SetFilePointerEx.argtypes = [
    wintypes.HANDLE, wintypes.LARGE_INTEGER,
    ctypes.POINTER(wintypes.LARGE_INTEGER), wintypes.DWORD,
]
_k32.SetFilePointerEx.restype = wintypes.BOOL

_k32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
_k32.FlushFileBuffers.restype = wintypes.BOOL

_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.CloseHandle.restype = wintypes.BOOL

_k32.VirtualAlloc.argtypes = [wintypes.LPVOID, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
_k32.VirtualAlloc.restype = wintypes.LPVOID

_k32.VirtualFree.argtypes = [wintypes.LPVOID, ctypes.c_size_t, wintypes.DWORD]
_k32.VirtualFree.restype = wintypes.BOOL


def _raise_last_error(context: str) -> None:
    err = ctypes.get_last_error()
    raise OSError(err, f"{context}: {ctypes.FormatError(err)}")


class AlignedBuffer:
    """A page-aligned (sector-aligned) memory block filled with incompressible data.

    Filling with random bytes defeats any controller-side compression or
    zero-detection that would otherwise inflate write throughput. We fill once
    and reuse the region, writing rotating slices of it so successive blocks
    differ (defeating naive dedup) without paying to regenerate randomness.
    """

    def __init__(self, size: int, randomize: bool = True):
        if size % ALIGN != 0:
            raise ValueError(f"buffer size {size} not a multiple of {ALIGN}")
        self.size = size
        addr = _k32.VirtualAlloc(None, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not addr:
            _raise_last_error("VirtualAlloc")
        self.addr = addr
        if randomize:
            # Fill in chunks so we don't build one giant Python bytes object.
            chunk = min(size, 8 * 1024 * 1024)
            filled = 0
            while filled < size:
                n = min(chunk, size - filled)
                ctypes.memmove(self.addr + filled, os.urandom(n), n)
                filled += n

    def ptr(self, offset: int = 0) -> ctypes.c_void_p:
        return ctypes.c_void_p(self.addr + offset)

    def free(self) -> None:
        if self.addr:
            _k32.VirtualFree(ctypes.c_void_p(self.addr), 0, MEM_RELEASE)
            self.addr = 0

    def __enter__(self) -> "AlignedBuffer":
        return self

    def __exit__(self, *exc) -> None:
        self.free()


class RawFile:
    """A file opened for true unbuffered, write-through I/O.

    All ``length`` and ``offset`` arguments must be multiples of :data:`ALIGN`.
    """

    def __init__(self, path: str, mode: str):
        # 'w'  create/truncate for sequential write
        # 'r'  open existing for read
        # 'rw' open existing for read+write WITHOUT truncating (random write in place)
        if mode not in ("w", "r", "rw"):
            raise ValueError("mode must be 'w', 'r', or 'rw'")
        self.path = path
        self.mode = mode
        write = mode in ("w", "rw")
        flags = FILE_FLAG_NO_BUFFERING | (FILE_FLAG_WRITE_THROUGH if write else 0)
        access = GENERIC_READ if mode == "r" else (
            GENERIC_READ | GENERIC_WRITE if mode == "rw" else GENERIC_WRITE
        )
        creation = CREATE_ALWAYS if mode == "w" else OPEN_EXISTING
        handle = _k32.CreateFileW(
            path, access,
            FILE_SHARE_READ | FILE_SHARE_WRITE, None,
            creation, FILE_ATTRIBUTE_NORMAL | flags, None,
        )
        if handle == INVALID_HANDLE_VALUE or handle is None:
            _raise_last_error(f"CreateFileW({path})")
        self.handle = handle
        self._closed = False

    def write(self, buf: AlignedBuffer, offset: int, length: int) -> int:
        written = wintypes.DWORD(0)
        ok = _k32.WriteFile(self.handle, buf.ptr(offset), length, ctypes.byref(written), None)
        if not ok:
            _raise_last_error("WriteFile")
        return written.value

    def read(self, buf: AlignedBuffer, offset: int, length: int) -> int:
        read = wintypes.DWORD(0)
        ok = _k32.ReadFile(self.handle, buf.ptr(offset), length, ctypes.byref(read), None)
        if not ok:
            _raise_last_error("ReadFile")
        return read.value

    def seek(self, position: int) -> None:
        new_pos = wintypes.LARGE_INTEGER(0)
        ok = _k32.SetFilePointerEx(
            self.handle, wintypes.LARGE_INTEGER(position), ctypes.byref(new_pos), FILE_BEGIN
        )
        if not ok:
            _raise_last_error("SetFilePointerEx")

    def flush(self) -> None:
        if not _k32.FlushFileBuffers(self.handle):
            _raise_last_error("FlushFileBuffers")

    def close(self) -> None:
        if not self._closed and self.handle:
            _k32.CloseHandle(self.handle)
            self._closed = True

    def __enter__(self) -> "RawFile":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class BufferedFallbackFile:
    """Fallback used only when unbuffered I/O cannot be opened on a volume.

    Uses ordinary buffered I/O but calls ``os.fsync`` on flush so writes are
    durable. It cannot defeat the OS read cache, so the benchmark marks results
    obtained through this path as lower confidence.
    """

    def __init__(self, path: str, mode: str):
        self.path = path
        self.mode = mode
        self._f = open(path, "wb" if mode == "w" else "rb", buffering=0)

    def write(self, buf: AlignedBuffer, offset: int, length: int) -> int:
        data = (ctypes.c_char * length).from_address(buf.addr + offset)
        return self._f.write(bytes(data))

    def read(self, buf: AlignedBuffer, offset: int, length: int) -> int:
        data = self._f.read(length)
        ctypes.memmove(buf.addr + offset, data, len(data))
        return len(data)

    def seek(self, position: int) -> None:
        self._f.seek(position)

    def flush(self) -> None:
        self._f.flush()
        os.fsync(self._f.fileno())

    def close(self) -> None:
        if not self._f.closed:
            self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def supports_unbuffered(path: str) -> bool:
    """Probe whether a small unbuffered write/delete round-trips on this volume."""
    probe = os.path.join(path, ".dst_probe.tmp")
    try:
        with AlignedBuffer(ALIGN) as buf, RawFile(probe, "w") as f:
            f.write(buf, 0, ALIGN)
            f.flush()
        return True
    except OSError:
        return False
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass
