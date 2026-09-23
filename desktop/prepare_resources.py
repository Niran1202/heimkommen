"""Collect everything the desktop app bundles into desktop/build/resources/.

    resources/web/          built React app (frontend/dist)
    resources/artifacts/    active delay model + evaluation.json
    resources/seed/         clean timetable database + timetable cache + VERSION
    resources/heimkommen.ico
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "build" / "resources"

# Personal or operational data that must never ship inside the product.
PRIVATE_TABLES = ("users", "saved_trips", "predictions", "outcomes", "train_stop_history")


def copy_web() -> None:
    dist = ROOT / "frontend" / "dist"
    if not (dist / "index.html").exists():
        sys.exit("frontend/dist is missing: run `npm run build` in frontend/ first")
    shutil.copytree(dist, OUT / "web")


def copy_artifacts() -> str:
    source = ROOT / "ml" / "artifacts"
    current = source / "current.json"
    target = OUT / "artifacts"
    target.mkdir(parents=True)
    if not current.exists():
        print("warning: no trained model; the app will use prior delay distributions")
        return "prior"
    version = json.loads(current.read_text(encoding="utf-8"))["version"]
    shutil.copytree(source / f"delay_model_{version}", target / f"delay_model_{version}")
    shutil.copy2(current, target / "current.json")
    if (source / "evaluation.json").exists():
        shutil.copy2(source / "evaluation.json", target / "evaluation.json")
    return version


def build_seed_db() -> str:
    source = ROOT / "data" / "heimkommen.db"
    if not source.exists():
        sys.exit("data/heimkommen.db is missing: import the GTFS feed first (make gtfs, make stations)")
    seed = OUT / "seed"
    seed.mkdir(parents=True)
    target = seed / "heimkommen.db"
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    with sqlite3.connect(target) as conn:
        for table in PRIVATE_TABLES:
            conn.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.commit()
        stops = conn.execute("SELECT COUNT(*) FROM stop_times").fetchone()[0]
        matched = conn.execute("SELECT COUNT(*) FROM station_map").fetchone()[0]
    with sqlite3.connect(target) as conn:
        conn.execute("VACUUM")
    print(f"seed database: {stops:,} stop times, {matched:,} matched stations, "
          f"{target.stat().st_size / 1e6:.0f} MB")

    cache = ROOT / "data" / "timetable_cache.pkl"
    if not cache.exists():
        sys.exit("data/timetable_cache.pkl is missing: start the API once so it builds the cache")
    shutil.copy2(cache, seed / "timetable_cache.pkl")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()[:12]
    (seed / "VERSION").write_text(digest, encoding="utf-8")
    return digest


def make_icon() -> None:
    """A simple app icon: a house with a lit window on the blue accent color."""
    from PIL import Image, ImageDraw

    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, size - 8, size - 8), radius=56, fill="#2a78d6")
    white = "#fcfcfb"
    draw.polygon([(128, 46), (216, 122), (196, 122), (196, 206), (60, 206), (60, 122), (40, 122)], fill=white)
    draw.rectangle((112, 146, 144, 206), fill="#2a78d6")  # door
    draw.rectangle((150, 132, 178, 158), fill="#fab219")  # lit window
    image.save(OUT / "heimkommen.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128),
                                              (256, 256)])
    image.save(OUT / "heimkommen.png")


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    copy_web()
    model = copy_artifacts()
    seed = build_seed_db()
    make_icon()
    print(f"resources ready in {OUT} (model {model}, seed {seed})")


if __name__ == "__main__":
    main()
