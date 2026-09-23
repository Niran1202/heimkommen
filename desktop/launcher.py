"""Heimkommen desktop launcher (the entry point of Heimkommen.exe).

Starts the FastAPI backend on 127.0.0.1, which also serves the React app, and shows it
in a native window (Edge WebView2, built into Windows 10/11). Everything the app needs
(Python, timetable, delay model) is bundled; per-user data lives in
%LOCALAPPDATA%\\Heimkommen.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

APP_NAME = "Heimkommen"
PREFERRED_PORT = 8765
SEED_FILES = ("heimkommen.db", "timetable_cache.pkl")


def resource_dir() -> Path:
    """Bundled read-only resources (PyInstaller) or desktop/build/resources in development."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "resources"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / "build" / "resources"


def user_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def install_seed_data(resources: Path, data: Path) -> None:
    """Copy the bundled timetable database on first start or after an update of the app.

    The desktop app has no accounts; the prediction log is carried over into the new
    timetable database so the local accuracy history survives updates.
    """
    seed = resources / "seed"
    bundled_version = (seed / "VERSION").read_text(encoding="utf-8").strip()
    marker = data / "seed_version.txt"
    installed = marker.read_text(encoding="utf-8").strip() if marker.exists() else None
    if installed == bundled_version and (data / "heimkommen.db").exists():
        return
    old_db = data / "heimkommen.db"
    backup = data / "heimkommen.previous.db"
    if old_db.exists():
        shutil.move(old_db, backup)
    for name in SEED_FILES:
        shutil.copy2(seed / name, data / name)
    if backup.exists():
        _carry_over_user_data(backup, data / "heimkommen.db")
        backup.unlink()
    marker.write_text(bundled_version, encoding="utf-8")


def _carry_over_user_data(old: Path, new: Path) -> None:
    import sqlite3

    with sqlite3.connect(new) as conn:
        conn.execute("ATTACH DATABASE ? AS old", (str(old),))
        for table in ("predictions", "outcomes"):
            # If the schema changed between versions, that table simply starts fresh.
            with contextlib.suppress(sqlite3.DatabaseError):
                conn.execute(f"INSERT OR IGNORE INTO {table} SELECT * FROM old.{table}")  # noqa: S608 - fixed names
        conn.commit()
        conn.execute("DETACH DATABASE old")


def is_heimkommen(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:  # noqa: S310
            return "timetable_loaded" in json.loads(response.read())
    except (OSError, ValueError):
        return False


def free_port() -> int:
    # A fixed port lets a second launch find the running instance; 0 = any free port.
    for port in (PREFERRED_PORT, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("no free port")


def configure_environment(resources: Path, data: Path) -> None:
    os.environ.update({
        "APP_ENV": "desktop",
        "DATABASE_URL": f"sqlite:///{(data / 'heimkommen.db').as_posix()}",
        "DATA_DIR": str(data),
        "ARTIFACTS_DIR": str(resources / "artifacts"),
        "STATIC_DIR": str(resources / "web"),
        "CORS_ORIGINS": "http://127.0.0.1",
        "ACCOUNTS_ENABLED": "false",
    })
    # A .env in the data folder can add DB API keys for live status (DB_API_CLIENT_ID, DB_API_KEY).
    os.chdir(data)


def start_server(port: int):
    import uvicorn

    from app.main import app

    # log_config=None: uvicorn logs go to the root logger, i.e. the log file.
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info", log_config=None, access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="heimkommen-api", daemon=True)
    thread.start()
    return server, thread


def wait_until_up(port: int, timeout: float = 60) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_heimkommen(port):
            return True
        time.sleep(0.2)
    return False


def show_window(url: str) -> None:
    try:
        import webview

        webview.create_window(APP_NAME, url, width=1120, height=860, min_size=(380, 600),
                              text_select=True, background_color="#f9f9f7")
        webview.start(private_mode=False, storage_path=str(user_dir() / "webview"))
    except Exception:  # no WebView2 runtime: fall back to the default browser
        import webbrowser

        webbrowser.open(url)
        _keep_alive_window(url)


def _keep_alive_window(url: str) -> None:
    """Small control window so the server keeps running while the browser is open."""
    import tkinter as tk

    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("360x130")
    tk.Label(root, text="Heimkommen is running in your browser.", pady=12).pack()
    tk.Button(root, text="Open again", command=lambda: __import__("webbrowser").open(url)).pack(pady=2)
    tk.Button(root, text="Quit Heimkommen", command=root.destroy).pack(pady=2)
    root.mainloop()


def setup_logging(data: Path) -> None:
    import logging

    logs = data / "logs"
    logs.mkdir(exist_ok=True)
    handler = logging.FileHandler(logs / "heimkommen.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    root._heimkommen_configured = True  # type: ignore[attr-defined]  # keep app logging from replacing it
    if sys.stdout is None:  # windowed exe: no console
        sys.stdout = open(logs / "stdout.log", "a", encoding="utf-8")  # noqa: SIM115
        sys.stderr = sys.stdout


def main() -> None:
    data = user_dir()
    setup_logging(data)
    try:
        if is_heimkommen(PREFERRED_PORT):  # already running: just open another window
            show_window(f"http://127.0.0.1:{PREFERRED_PORT}/")
            return
        resources = resource_dir()
        install_seed_data(resources, data)
        configure_environment(resources, data)
        if not getattr(sys, "frozen", False):
            sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        port = free_port()
        server, thread = start_server(port)
        if not wait_until_up(port):
            raise RuntimeError("the Heimkommen server did not start; see logs\\heimkommen.log")
        show_window(f"http://127.0.0.1:{port}/")
        server.should_exit = True
        thread.join(timeout=5)
    except Exception:
        (data / "logs" / "crash.log").write_text(traceback.format_exc(), encoding="utf-8")
        _error_box(f"Heimkommen could not start.\n\nDetails were written to:\n{data / 'logs' / 'crash.log'}")
        raise


def _error_box(message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x10)
    except Exception:  # noqa: S110 - best effort
        pass


if __name__ == "__main__":
    main()
