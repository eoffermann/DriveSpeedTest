"""Launch DriveSpeedTest: start the FastAPI server and open the browser.

Usage:
    python run.py            # serve on 127.0.0.1:8760 and open a browser
    python run.py --admin    # relaunch elevated first (needed for SMART on some drives)
    python run.py --no-browser

Run this with the project's virtual environment Python (see run.bat, which
bootstraps the venv, installs deps, builds the frontend, then calls this).
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
import webbrowser

HOST = "127.0.0.1"
PORT = 8760
URL = f"http://{HOST}:{PORT}"


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_as_admin() -> None:
    """Re-run this script elevated, dropping the --admin flag to avoid a loop."""
    params = " ".join(a for a in sys.argv[1:] if a != "--admin")
    script = f'"{sys.argv[0]}" {params}'.strip()
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, script, None, 1)


def main() -> None:
    args = sys.argv[1:]
    if "--admin" in args and not _is_admin():
        _relaunch_as_admin()
        return

    try:
        import uvicorn
    except ImportError:
        print("Dependencies are missing. Run `run.bat` (bootstraps the venv), or:\n"
              "  python -m venv .venv && .venv\\Scripts\\pip install -r requirements.txt")
        sys.exit(1)

    if "--no-browser" not in args:
        def _open() -> None:
            time.sleep(1.3)
            webbrowser.open(URL)
        threading.Thread(target=_open, daemon=True).start()

    elevated = " (elevated — SMART available)" if _is_admin() else ""
    print(f"DriveSpeedTest running at {URL}{elevated}  —  Ctrl+C to stop")
    uvicorn.run("backend.app:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
