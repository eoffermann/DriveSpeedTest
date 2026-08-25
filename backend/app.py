"""FastAPI application: REST for metadata/diagnostics/analysis, a WebSocket that
streams a live benchmark, and (in production) the built React bundle.

The benchmark is blocking CPU/IO work, so it runs in a thread-pool executor while
its progress callback feeds an asyncio queue that the WebSocket drains -- giving
the browser a live throughput feed and sustained-write curve without blocking the
event loop.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import asdict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, analysis, diagnostics, drives, smart, winutil
from .benchmark import GiB, MiB, BenchmarkConfig, DriveBenchmark, preset
from .models import AnalyzeRequest, RunRequest

app = FastAPI(title="DriveSpeedTest", version=__version__)

# Dev convenience: the Vite dev server (5173) calls the API cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"],
)

# Only one benchmark may touch a drive at a time.
_run_lock = asyncio.Lock()

def _frontend_dir() -> str:
    """Locate the built React bundle in both source and PyInstaller-frozen runs.

    When frozen, the spec adds frontend/dist under the onefile unpack dir
    (``sys._MEIPASS``); otherwise it sits next to the repo root.
    """
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "frontend", "dist")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")


_DIST = _frontend_dir()


# --- REST --------------------------------------------------------------------
@app.get("/api/status")
def status() -> dict:
    return {
        "version": __version__,
        "is_admin": winutil.is_admin(),
        "smartctl_present": smart._find_smartctl() is not None,
        "default_blurb": analysis.DEFAULT_BLURB,
        "busy": _run_lock.locked(),
    }


@app.get("/api/drives")
def api_drives() -> dict:
    return {"drives": [d.to_dict() for d in drives.list_drives()]}


@app.get("/api/diagnostics/{letter}")
def api_diagnostics(letter: str) -> dict:
    return asdict(diagnostics.collect(letter))


@app.post("/api/analyze")
def api_analyze(req: AnalyzeRequest) -> dict:
    verdict = analysis.analyze(req.blurb or analysis.DEFAULT_BLURB, req.benchmark, req.diagnostics)
    return analysis.to_dict(verdict)


def _build_config(req: RunRequest) -> BenchmarkConfig:
    cfg = preset(req.depth)
    cfg.allow_system_drive = req.allow_system
    if req.seq_size_mb:
        cfg.seq_size = max(MiB, req.seq_size_mb * MiB)
    if req.sustained_size_mb:
        cfg.run_sustained = True
        cfg.sustained_size = max(cfg.sustained_chunk, req.sustained_size_mb * MiB)
    return cfg


def _bench_to_dict(res) -> dict:
    return {
        "method": res.method,
        "seq_write_mbps": res.seq_write_mbps,
        "seq_read_mbps": res.seq_read_mbps,
        "rand_write": asdict(res.rand_write) if res.rand_write else None,
        "rand_read": asdict(res.rand_read) if res.rand_read else None,
        "sustained": asdict(res.sustained) if res.sustained else None,
        "bytes_written": res.bytes_written,
        "config_label": res.config_label,
    }


# --- WebSocket: live benchmark ----------------------------------------------
@app.websocket("/ws/run")
async def ws_run(ws: WebSocket) -> None:
    await ws.accept()
    try:
        req = RunRequest.model_validate_json(await ws.receive_text())
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await ws.send_json({"type": "error", "message": f"Invalid request: {exc}"})
        await ws.close()
        return

    if _run_lock.locked():
        await ws.send_json({"type": "error", "message": "Another benchmark is already running."})
        await ws.close()
        return

    async with _run_lock:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def on_progress(ev: dict) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, ev)

        try:
            # 1) Diagnostics first, so the UI can render drive/link/SMART immediately.
            await ws.send_json({"type": "phase", "phase": "diagnostics", "label": "Collecting diagnostics"})
            report = await loop.run_in_executor(None, diagnostics.collect, req.letter)
            diag_dict = asdict(report)
            await ws.send_json({"type": "diagnostics", "data": diag_dict})

            # 2) Benchmark in a worker thread; stream progress from the queue.
            cfg = _build_config(req)

            def run_bench():
                return DriveBenchmark(req.letter + ":\\", cfg, on_progress=on_progress).run()

            fut = loop.run_in_executor(None, run_bench)
            while not (fut.done() and queue.empty()):
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=0.1)
                    await ws.send_json(ev)
                except asyncio.TimeoutError:
                    continue
            res = fut.result()  # re-raises benchmark errors here

            # 3) Grade and diagnose.
            bench_dict = _bench_to_dict(res)
            verdict = analysis.analyze(req.blurb or analysis.DEFAULT_BLURB, bench_dict, diag_dict)
            await ws.send_json({
                "type": "complete",
                "benchmark": bench_dict,
                "diagnostics": diag_dict,
                "verdict": analysis.to_dict(verdict),
            })
        except WebSocketDisconnect:
            return
        except Exception as exc:  # surfaced to the UI, not swallowed
            try:
                await ws.send_json({"type": "error", "message": str(exc)})
            except Exception:
                pass
        finally:
            try:
                await ws.close()
            except Exception:
                pass


# --- Static frontend (production) -------------------------------------------
if os.path.isdir(_DIST):
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
else:
    @app.get("/")
    def _no_frontend() -> JSONResponse:
        return JSONResponse(
            {"message": "Frontend not built. Run `npm install && npm run build` in "
                        "frontend/, or use the Vite dev server on :5173."},
            status_code=200)
