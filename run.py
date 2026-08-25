"""Launch DriveSpeedTest: start the FastAPI server and open the browser.

Works both as a script (`python run.py`) and as a PyInstaller-frozen single .exe.

Usage:
    python run.py                # serve on 127.0.0.1:8760 and open a browser
    python run.py --admin        # relaunch elevated first (SMART on some drives)
    DriveSpeedTest.exe           # frozen: attempts elevation by default (UAC)
    ... --no-admin               # skip the elevation attempt
    ... --no-browser             # don't open a browser (useful for testing)
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

FROZEN = getattr(sys, "frozen", False)


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_as_admin(args: list[str]) -> bool:
    """Relaunch elevated. Returns True if an elevated process was started (so the
    caller should exit), False if the user declined or elevation failed (carry on
    without admin -- everything except full SMART still works).
    """
    passthrough = [a for a in args if a not in ("--admin",)]
    if FROZEN:
        target, params = sys.executable, " ".join(passthrough)
    else:
        target = sys.executable
        params = " ".join([f'"{sys.argv[0]}"'] + passthrough)
    # ShellExecuteW returns >32 on success; a declined UAC yields <=32.
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", target, params, None, 1)
    return int(rc) > 32


def main() -> None:
    args = sys.argv[1:]

    # Frozen builds attempt elevation by default (matches run.bat); scripts only
    # when asked with --admin. --no-admin always opts out.
    want_admin = ("--admin" in args) or (FROZEN and "--no-admin" not in args)
    if want_admin and not _is_admin():
        if _relaunch_as_admin(args):
            return  # elevated instance is taking over
        print("[DriveSpeedTest] Continuing without administrator rights "
              "(SMART health may be limited).")

    try:
        import uvicorn
        from backend.app import app as application
    except ImportError as exc:
        print(f"Dependencies are missing ({exc}). Run `run.bat` (bootstraps the venv), or:\n"
              "  python -m venv .venv && .venv\\Scripts\\pip install -r requirements.txt")
        sys.exit(1)

    if "--no-browser" not in args:
        def _open() -> None:
            time.sleep(1.3)
            webbrowser.open(URL)
        threading.Thread(target=_open, daemon=True).start()

    elevated = " (elevated — SMART available)" if _is_admin() else ""
    print(f"DriveSpeedTest running at {URL}{elevated}  —  Ctrl+C to stop")
    # Pass the app object (not an import string) so it works when frozen.
    uvicorn.run(application, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
