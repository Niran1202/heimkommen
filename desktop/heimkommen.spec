# PyInstaller spec for Heimkommen.exe (one-folder build, no console window).
# Build with: python desktop/build.py

from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

HERE = Path(SPECPATH)
ROOT = HERE.parent
RESOURCES = HERE / "build" / "resources"

# The API only; ETL, workers and the offline ML pipeline are not part of the desktop app.
app_modules = [m for m in collect_submodules("app", filter=lambda name: not name.startswith(
    ("app.workers", "app.etl.delays_loader")))]

hiddenimports = app_modules + [
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.loops.asyncio", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
    "sqlalchemy.dialects.sqlite", "email_validator", "bcrypt", "jose", "defusedxml", "lightgbm",
    "webview", "webview.platforms.edgechromium", "tzdata",
]

# scipy stays: lightgbm imports it unconditionally.
excludes = [
    "pyarrow", "celery", "kombu", "billiard", "matplotlib", "sklearn", "testcontainers", "pytest",
    "IPython", "ipykernel", "jupyter_client", "notebook", "nbformat", "nbclient", "playwright", "psycopg",
    "psycopg_binary", "redis", "alembic", "mypy", "ruff", "PIL",
]

a = Analysis(
    [str(HERE / "launcher.py")],
    pathex=[str(ROOT / "backend")],
    binaries=collect_dynamic_libs("lightgbm"),
    datas=[(str(RESOURCES), "resources")],
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Heimkommen",
    icon=str(RESOURCES / "heimkommen.ico"),
    version=str(HERE / "version_info.txt"),
    console=False,
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Heimkommen")
