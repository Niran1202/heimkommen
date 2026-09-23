"""Build the Windows product: desktop/release/Heimkommen/Heimkommen.exe and the installer
desktop/Output/Heimkommen-Setup-<version>.exe.

    python desktop/build.py [--skip-frontend] [--skip-installer]

Needs: Node (frontend build), `pip install pyinstaller pywebview pillow` and Inno Setup 6
(`winget install JRSoftware.InnoSetup --scope user`) for the installer.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def run(cmd: list[str], cwd: Path) -> None:
    print("\n>", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True, shell=os.name == "nt" and cmd[0] == "npm")  # noqa: S603


def find_iscc() -> str | None:
    candidates = [
        shutil.which("ISCC"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--skip-installer", action="store_true")
    args = parser.parse_args()

    if not args.skip_frontend:
        if not (ROOT / "frontend" / "node_modules" / ".package-lock.json").exists():
            run(["npm", "ci"], ROOT / "frontend")
        run(["npm", "run", "build"], ROOT / "frontend")
    run([sys.executable, str(HERE / "prepare_resources.py")], ROOT)
    run([sys.executable, "-m", "PyInstaller", str(HERE / "heimkommen.spec"), "--noconfirm", "--clean",
         "--distpath", str(HERE / "release"), "--workpath", str(HERE / "build" / "pyinstaller")], ROOT)
    exe = HERE / "release" / "Heimkommen" / "Heimkommen.exe"
    print(f"\nportable app: {exe}")

    if args.skip_installer:
        return
    iscc = find_iscc()
    if iscc is None:
        print("Inno Setup not found; skipping the installer (winget install JRSoftware.InnoSetup --scope user)")
        return
    run([iscc, "/Q", str(HERE / "installer.iss")], HERE)
    for setup in (HERE / "Output").glob("Heimkommen-Setup-*.exe"):
        print(f"installer: {setup} ({setup.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
