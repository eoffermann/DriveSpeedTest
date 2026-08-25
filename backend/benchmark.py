"""Drive benchmark orchestrator.

Runs a sequence of honest, cache-bypassing tests against a target volume and
emits progress events through a callback so the web layer can stream them live:

  * Sequential write / read  -> MB/s (large blocks, the "up to X MB/s" numbers)
  * Random 4 KiB write / read at QD1 -> IOPS, MB/s, average latency
  * Sustained write           -> throughput-over-time samples that expose the
                                 SLC-cache "cliff" (the make-or-break test for a
                                 "stable write speeds without slowdown" claim)

All throughput is reported in decimal MB/s (1 MB = 1,000,000 bytes) to match how
drive vendors and CrystalDiskMark quote numbers. Sizes are handled in bytes and
described to users in binary GiB.

The engine writes into temp files on the target volume and always cleans them up.
It refuses the system drive unless explicitly allowed, and scales its footprint
down to fit available free space.
"""

from __future__ import annotations

import os
import random
import shutil
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import ioengine
from .ioengine import ALIGN, AlignedBuffer, BufferedFallbackFile, RawFile

MiB = 1024 * 1024
GiB = 1024 * 1024 * 1024
MB = 1_000_000  # decimal, for throughput reporting

ProgressCb = Callable[[dict], None]

# Cap the reusable random source buffer. Big enough for block variety, small
# enough to allocate instantly and stay resident.
_SRC_CAP = 256 * MiB
# Safety margin of free space we never consume.
_FREE_MARGIN = 512 * MiB


def _mbps(nbytes: int, seconds: float) -> float:
    if seconds <= 0:
        return 0.0
    return nbytes / seconds / MB


def _align_down(n: int) -> int:
    return n - (n % ALIGN)


@dataclass
class BenchmarkConfig:
    """Knobs for one benchmark run. `depth` presets map onto these in app.py."""

    seq_block: int = 1 * MiB          # sequential block size
    seq_size: int = 1 * GiB           # sequential file size
    rand_block: int = 4 * 1024        # random I/O block size (4 KiB)
    rand_duration: float = 3.0        # seconds per random test
    run_sustained: bool = True
    sustained_size: int = 4 * GiB     # total bytes for the sustained write test
    sustained_chunk: int = 64 * MiB   # sample granularity
    allow_system_drive: bool = False
    label: str = "custom"

    def scaled_to_free(self, free_bytes: int) -> "BenchmarkConfig":
        """Return a copy shrunk so the largest single file fits free space."""
        budget = max(0, free_bytes - _FREE_MARGIN)
        cfg = BenchmarkConfig(**self.__dict__)
        cfg.seq_size = max(ALIGN, _align_down(min(self.seq_size, budget)))
        if cfg.run_sustained:
            cfg.sustained_size = max(cfg.sustained_chunk, _align_down(min(self.sustained_size, budget)))
        return cfg


@dataclass
class RandomResult:
    iops: float
    mbps: float
    latency_us: float
    ops: int


@dataclass
class SustainedResult:
    points: list = field(default_factory=list)   # [{elapsed, written_bytes, mbps}]
    peak_mbps: float = 0.0
    avg_mbps: float = 0.0


@dataclass
class BenchmarkResult:
    method: str = "unbuffered"        # or "buffered+fsync" (lower confidence)
    seq_write_mbps: float = 0.0
    seq_read_mbps: float = 0.0
    rand_write: Optional[RandomResult] = None
    rand_read: Optional[RandomResult] = None
    sustained: Optional[SustainedResult] = None
    bytes_written: int = 0
    config_label: str = "custom"


class DriveBenchmark:
    def __init__(self, root: str, config: BenchmarkConfig, on_progress: Optional[ProgressCb] = None):
        # Normalize "E" / "E:" / "E:\" -> "E:\"
        letter = root.rstrip(":\\/")[:1].upper()
        self.root = f"{letter}:\\"
        self.cfg = config
        self._cb = on_progress or (lambda ev: None)
        self._data_file = os.path.join(self.root, ".drivespeedtest.tmp")
        self._sustained_file = os.path.join(self.root, ".drivespeedtest.sustained.tmp")
        self._unbuffered = True

    # -- helpers --------------------------------------------------------------
    def _emit(self, **ev) -> None:
        self._cb(ev)

    def _open(self, path: str, mode: str):
        if self._unbuffered:
            return RawFile(path, mode)
        return BufferedFallbackFile(path, mode)

    def _guard(self) -> BenchmarkConfig:
        system_drive = os.environ.get("SystemDrive", "C:").rstrip(":\\").upper()
        if self.root[0].upper() == system_drive and not self.cfg.allow_system_drive:
            raise PermissionError(
                f"Refusing to benchmark the system drive {self.root}. "
                f"Pass allow_system_drive=True to override."
            )
        if not os.path.isdir(self.root):
            raise FileNotFoundError(f"Drive {self.root} is not available.")
        free = shutil.disk_usage(self.root).free
        cfg = self.cfg.scaled_to_free(free)
        self._unbuffered = ioengine.supports_unbuffered(self.root)
        return cfg

    # -- individual tests -----------------------------------------------------
    def _seq_write(self, src: AlignedBuffer, size: int, block: int) -> float:
        slots = max(1, src.size // block)
        written = 0
        next_report = 0
        start = time.perf_counter()
        with self._open(self._data_file, "w") as f:
            i = 0
            while written < size:
                n = min(block, size - written)
                f.write(src, (i % slots) * block, n)
                written += n
                i += 1
                if written >= next_report:
                    self._emit(type="progress", phase="seq_write",
                               pct=written / size, mbps=_mbps(written, time.perf_counter() - start))
                    next_report = written + size // 20
            f.flush()
        elapsed = time.perf_counter() - start
        return _mbps(size, elapsed)

    def _seq_read(self, size: int, block: int) -> float:
        read_total = 0
        next_report = 0
        with AlignedBuffer(block, randomize=False) as scratch:
            start = time.perf_counter()
            with self._open(self._data_file, "r") as f:
                while read_total < size:
                    n = min(block, size - read_total)
                    got = f.read(scratch, 0, n)
                    if got <= 0:
                        break
                    read_total += got
                    if read_total >= next_report:
                        self._emit(type="progress", phase="seq_read",
                                   pct=read_total / size, mbps=_mbps(read_total, time.perf_counter() - start))
                        next_report = read_total + size // 20
            elapsed = time.perf_counter() - start
        return _mbps(read_total, elapsed)

    def _random(self, phase: str, size: int, block: int, duration: float) -> RandomResult:
        writing = phase == "rand_write"
        max_offset = _align_down(max(ALIGN, size - block))
        n_slots = max(1, max_offset // block)
        rng = random.Random(0xC0FFEE)  # deterministic offsets => repeatable runs
        src = None
        try:
            if writing:
                src = AlignedBuffer(block, randomize=True)
            else:
                src = AlignedBuffer(block, randomize=False)
            ops = 0
            start = time.perf_counter()
            deadline = start + duration
            f = self._open(self._data_file, "rw" if writing else "r")
            try:
                while True:
                    now = time.perf_counter()
                    if now >= deadline:
                        break
                    off = (rng.randrange(n_slots)) * block
                    f.seek(off)
                    if writing:
                        f.write(src, 0, block)
                    else:
                        f.read(src, 0, block)
                    ops += 1
                    if ops % 512 == 0:
                        elapsed = now - start
                        self._emit(type="progress", phase=phase,
                                   pct=min(1.0, elapsed / duration),
                                   mbps=_mbps(ops * block, elapsed))
                if writing:
                    f.flush()
            finally:
                f.close()
            elapsed = time.perf_counter() - start
        finally:
            if src:
                src.free()
        iops = ops / elapsed if elapsed else 0.0
        return RandomResult(
            iops=iops,
            mbps=_mbps(ops * block, elapsed),
            latency_us=(elapsed / ops * 1e6) if ops else 0.0,
            ops=ops,
        )

    def _sustained(self, src: AlignedBuffer, size: int, chunk: int) -> SustainedResult:
        chunk = min(chunk, size)
        slots = max(1, src.size // chunk)
        res = SustainedResult()
        written = 0
        start = time.perf_counter()
        with self._open(self._sustained_file, "w") as f:
            i = 0
            while written < size:
                n = min(chunk, size - written)
                t0 = time.perf_counter()
                f.write(src, (i % slots) * chunk, n)
                # WRITE_THROUGH means the data is on its way to the device, but
                # flush per chunk so each sample reflects real committed speed and
                # the SLC cliff isn't hidden by a late buffer drain.
                f.flush()
                dt = time.perf_counter() - t0
                written += n
                i += 1
                inst = _mbps(n, dt)
                res.peak_mbps = max(res.peak_mbps, inst)
                point = {
                    "elapsed": round(time.perf_counter() - start, 3),
                    "written_bytes": written,
                    "mbps": round(inst, 1),
                }
                res.points.append(point)
                self._emit(type="sustained_point", **point)
        total_elapsed = time.perf_counter() - start
        res.avg_mbps = _mbps(written, total_elapsed)
        return res

    # -- orchestration --------------------------------------------------------
    def run(self) -> BenchmarkResult:
        cfg = self._guard()
        result = BenchmarkResult(config_label=cfg.label)
        result.method = "unbuffered" if self._unbuffered else "buffered+fsync"

        src_size = min(_SRC_CAP, max(cfg.seq_block, cfg.sustained_chunk, 64 * MiB))
        src_size = max(_align_down(src_size), cfg.seq_block, cfg.sustained_chunk)
        src = AlignedBuffer(src_size, randomize=True)
        try:
            self._emit(type="phase", phase="seq_write", label="Sequential write")
            result.seq_write_mbps = self._seq_write(src, cfg.seq_size, cfg.seq_block)
            self._emit(type="result", metric="seq_write", mbps=round(result.seq_write_mbps, 1))

            self._emit(type="phase", phase="seq_read", label="Sequential read")
            result.seq_read_mbps = self._seq_read(cfg.seq_size, cfg.seq_block)
            self._emit(type="result", metric="seq_read", mbps=round(result.seq_read_mbps, 1))

            self._emit(type="phase", phase="rand_write", label="Random 4K write (QD1)")
            result.rand_write = self._random("rand_write", cfg.seq_size, cfg.rand_block, cfg.rand_duration)
            self._emit(type="result", metric="rand_write", iops=round(result.rand_write.iops),
                       mbps=round(result.rand_write.mbps, 1))

            self._emit(type="phase", phase="rand_read", label="Random 4K read (QD1)")
            result.rand_read = self._random("rand_read", cfg.seq_size, cfg.rand_block, cfg.rand_duration)
            self._emit(type="result", metric="rand_read", iops=round(result.rand_read.iops),
                       mbps=round(result.rand_read.mbps, 1))

            result.bytes_written = cfg.seq_size

            if cfg.run_sustained:
                self._emit(type="phase", phase="sustained", label="Sustained write (SLC cache)")
                result.sustained = self._sustained(src, cfg.sustained_size, cfg.sustained_chunk)
                result.bytes_written += cfg.sustained_size
                self._emit(type="result", metric="sustained",
                           peak_mbps=round(result.sustained.peak_mbps, 1),
                           avg_mbps=round(result.sustained.avg_mbps, 1))

            self._emit(type="done")
            return result
        finally:
            src.free()
            self._cleanup()

    def _cleanup(self) -> None:
        for path in (self._data_file, self._sustained_file):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


# Depth presets used by the API layer.
def preset(depth: str) -> BenchmarkConfig:
    depth = (depth or "quick").lower()
    if depth == "quick":
        return BenchmarkConfig(seq_size=1 * GiB, rand_duration=3.0,
                               run_sustained=False, label="quick")
    if depth == "full":
        return BenchmarkConfig(seq_size=2 * GiB, rand_duration=4.0,
                               run_sustained=True, sustained_size=4 * GiB, label="full")
    if depth == "sustained":
        return BenchmarkConfig(seq_size=1 * GiB, rand_duration=3.0,
                               run_sustained=True, sustained_size=16 * GiB, label="sustained")
    return BenchmarkConfig(label="quick", run_sustained=False)
