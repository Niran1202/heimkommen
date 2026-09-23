# Heimkommen for Windows

A self-contained desktop version of Heimkommen: one installer, no Python, Node, Docker or database to set up.
The timetable (NVBW, valid 3 May – 12 December 2026) and the trained delay model are included.

## For users

1. Run **`Heimkommen-Setup-1.0.0.exe`** (about 86 MB). No administrator rights are needed; it installs to
   `%LOCALAPPDATA%\Programs\Heimkommen` and adds a Start-menu entry (desktop icon optional).
2. Start **Heimkommen**. The app opens in its own window after a few seconds.

- Windows 10 (1809+) or 11, 64-bit. The window uses Microsoft Edge WebView2, which is built into Windows 11;
  without it the app opens in your default browser instead.
- The desktop app is single-user: **no account and no login**. Nothing leaves your computer except map tiles
  (OpenStreetMap, only when you open a map) and live status requests (only when you press "Live status").
- Your data (a working copy of the timetable, the prediction history, logs) lives in `%LOCALAPPDATA%\Heimkommen`.
  The uninstaller asks whether to delete it.
- Optional live status: put a `.env` file with `DB_API_CLIENT_ID=...` and `DB_API_KEY=...` (free DB API Marketplace
  keys) into `%LOCALAPPDATA%\Heimkommen`.
- The installer is not code-signed, so Windows SmartScreen may show "Windows protected your PC". Choose
  *More info → Run anyway*.
- Problems: see `%LOCALAPPDATA%\Heimkommen\logs\heimkommen.log` (and `crash.log` if it did not start).

## For developers: building it

Prerequisites: the imported timetable (`data/heimkommen.db`, `data/timetable_cache.pkl`), a trained model in
`ml/artifacts/`, Node 20+, Python 3.12+ and:

```bash
pip install pyinstaller pywebview pillow
winget install JRSoftware.InnoSetup --scope user     # for the installer
python desktop/build.py
```

| Step | Output |
|---|---|
| `npm run build` | `frontend/dist` |
| `prepare_resources.py` | `desktop/build/resources`: web app, model, **clean** timetable database (accounts, predictions and delay history removed), icon |
| PyInstaller (`heimkommen.spec`) | `desktop/release/Heimkommen/Heimkommen.exe`, a portable folder (~460 MB) |
| Inno Setup (`installer.iss`) | `desktop/Output/Heimkommen-Setup-1.0.0.exe` |

`python desktop/build.py --skip-frontend --skip-installer` rebuilds only the exe.

How it works: `launcher.py` copies the bundled database to the user folder on first start (and after updates,
keeping the prediction history), starts the FastAPI backend on `127.0.0.1` with `ACCOUNTS_ENABLED=false` and
`STATIC_DIR` pointing at the bundled React app, then opens it in a pywebview window. Starting it a second time
opens another window on the running instance.
