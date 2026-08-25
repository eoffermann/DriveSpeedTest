# DriveSpeedTest

An **honest** external-drive profiler for Windows. Point it at a drive and it
tells you not just how fast it is, but whether it lives up to its marketing —
and if it doesn't, **whether the bottleneck is the drive, the cable, or the USB
port.**

It exists because most quick "drive speed" scripts lie: they write compressible
zeros, never flush to the device, and re-read data straight from RAM. The numbers
look great and mean nothing. DriveSpeedTest measures the real device with the OS
cache bypassed, then cross-checks the result against the drive's USB link, SMART
health, and the marketing claims you paste in.

![stack: FastAPI + React](https://img.shields.io/badge/stack-FastAPI%20%2B%20React-38bdf8)

---

## What it does

- **Real throughput.** Sequential and random 4K read/write measured with
  incompressible data and unbuffered, write-through I/O (`FILE_FLAG_NO_BUFFERING`)
  — so results reflect the drive, not the cache.
- **Sustained-write / SLC-cache test.** Writes multiple GiB and charts throughput
  over time to expose the "cliff" where the fast SLC cache fills and the drive
  drops to its native TLC speed. This is the only real test of a
  *"stable write speeds without slowdown"* claim.
- **Connection diagnosis.** Reads the **negotiated USB link speed** (via the same
  `DeviceIoControl` USB tree-walk USBView uses), the host controllers, TRIM state,
  filesystem, and SMART health. A drive rated 2100 MB/s that negotiated only
  5 Gbps is being throttled by the cable/port — not the flash.
- **Marketing verdict.** Paste the vendor blurb; it grades each claim
  (read / write / sustained / TRIM / SMART / TLC) against what was measured and
  returns a **ranked diagnosis** with concrete next steps.
- **Live UI.** A React dashboard streams the benchmark over a WebSocket, draws the
  sustained curve in real time, and lets you edit the marketing text to re-grade
  instantly. Export a JSON or text report.

## Download (no install)

Grab **`DriveSpeedTest.exe`** from the
[latest release](https://github.com/eoffermann/DriveSpeedTest/releases/latest) and
double-click it. It's a single self-contained file — no Python, Node, or install
needed. It asks for administrator rights via UAC (for full SMART health); decline
and it still runs, just without SMART. It starts a local server and opens your
browser at <http://127.0.0.1:8760>.

> Windows SmartScreen may warn about an unsigned exe from a new publisher — choose
> *More info → Run anyway*, or build it yourself (below).

## Quick start (from source)

```bat
git clone https://github.com/eoffermann/DriveSpeedTest.git
cd DriveSpeedTest
run.bat
```

`run.bat` self-elevates via UAC, creates a virtual environment, installs the
Python deps, builds the React frontend, starts the server on
<http://127.0.0.1:8760>, and opens your browser. First run takes a minute (npm
build); later runs are instant.

For full SMART health (temperature, wear, error counts) over a USB bridge, either
run elevated:

```bat
run.bat --admin
```

…or install [smartmontools](https://www.smartmontools.org/) so `smartctl` is on
your PATH. Without either, everything except SMART still works, and the UI shows a
"run as administrator" banner.

## Requirements

- **Windows 10/11** (uses Windows-specific APIs for unbuffered I/O, the USB tree,
  and SMART).
- **Python 3.9+** and **Node.js 18+** on your PATH.

## Development

Two terminals, with hot reload:

```bat
:: backend
.venv\Scripts\python -m uvicorn backend.app:app --reload --port 8760

:: frontend (Vite dev server proxies /api and /ws to :8760)
cd frontend && npm run dev
```

Then open <http://localhost:5173>.

## Building the single-file exe

```bat
build.bat
```

This builds the frontend and packages everything (backend, UI, and Python) into
`dist\DriveSpeedTest.exe` with PyInstaller, using `DriveSpeedTest.spec`.

### Cutting a release

Pushing a version tag builds the exe on a Windows CI runner and attaches it to a
GitHub Release automatically (see `.github/workflows/release.yml`):

```bat
git tag v1.0.0
git push origin v1.0.0
```

You can also trigger the workflow manually from the **Actions** tab to get the exe
as a build artifact without publishing a release.

## How it works

```
frontend/ (React + Vite + TS)  ──REST /api──▶  backend/ (FastAPI)
        └───────────── WebSocket /ws/run ─────────────┘
```

| Module | Responsibility |
| --- | --- |
| `backend/ioengine.py` | Unbuffered, sector-aligned Win32 I/O (`CreateFileW` + `NO_BUFFERING`/`WRITE_THROUGH`). |
| `backend/benchmark.py` | Sequential/random/sustained tests with live progress callbacks. |
| `backend/usb.py` | Negotiated USB link speed via `DeviceIoControl` (USBView method). |
| `backend/smart.py` | SMART via `smartctl` → Windows reliability counters fallback. |
| `backend/drives.py` / `diagnostics.py` | Drive metadata, TRIM, filesystem, controller chain. |
| `backend/analysis.py` | Parses the marketing blurb and produces the ranked verdict. |
| `backend/app.py` | REST + WebSocket, and serves the built frontend. |

### Why the numbers can be *lower* than a "normal" speed test

Because they're honest. If a competing tool shows 1800 MB/s reads on a USB drive
whose link tops out near 1000 MB/s, it's reading from RAM cache. DriveSpeedTest
reports what the device actually delivered. If that's below the marketing claim,
the **Diagnosis** tab tells you why.

## Safety

Tests write temporary files (`.drivespeedtest*.tmp`) to the target drive and
always delete them. Free space is checked first and the write budget is capped.
The system drive is refused by default.

## License

See [LICENSE](LICENSE).
