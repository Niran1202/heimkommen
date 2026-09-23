"""Generate and execute the analysis notebooks (outputs are saved in the .ipynb files).

    python ml/notebooks/build_notebooks.py
"""

from pathlib import Path

import nbformat
from nbclient import NotebookClient

HERE = Path(__file__).parent

SETUP = """import sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path.cwd().resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import numpy as np, pandas as pd
pd.set_option("display.width", 140)"""

NOTEBOOKS = {
    "01_explore_delays.ipynb": [
        ("md", "# 01 · Exploring delays in Baden-Württemberg\n\nPiebro monthly data filtered to the ~1,000 "
               "BW rail stations matched to the GTFS feed (`ml/pipelines/download_data.py`)."),
        ("code", SETUP),
        ("code", """from app.engine.features import events_from_stops
stops = pd.read_parquet(ROOT / "data/processed/delays-2026-08.parquet")
events = events_from_stops(stops[~stops.is_additional_stop])
ok = events[~events.cancelled & events.delay.notna()]
print(f"{len(stops):,} stop rows, {len(events):,} arrival/departure events in August 2026")
ok.delay.describe(percentiles=[.5, .8, .9, .95, .99]).round(2)"""),
        ("md", "## Delay by product and hour\nLong-distance trains arrive with much heavier tails; "
               "the evening peak is the worst time of day for regional trains."),
        ("code", """by_product = ok.groupby("product").delay.agg(
    events="size", median="median", p90=lambda s: s.quantile(.9), share_over_5=lambda s: (s > 5).mean())
by_product.round(2)"""),
        ("code", """rb_re = ok[ok["product"].isin(["RE", "RB"]) & (ok.is_departure == 0)]
rb_re.groupby("hour").delay.agg(p50="median", p90=lambda s: s.quantile(.9)).T.round(1)"""),
        ("md", "## Cancellations by line (departures, lines with ≥ 2,000 departures)"),
        ("code", """dep = events[events.is_departure == 1]
lines = dep.groupby("line").cancelled.agg(departures="size", rate="mean")
lines[lines.departures >= 2000].sort_values("rate", ascending=False).head(12).round(3)"""),
    ],
    "02_last_connections.ipynb": [
        ("md", "# 02 · The last connections of the night\n\nWhat are the last connections from Stuttgart, "
               "Freiburg and Konstanz back to Villingen-area towns and villages on a Friday, and how likely "
               "is each one to actually get you home? (Deutschlandticket, delay model + simulator.)"),
        ("code", SETUP),
        ("code", """from datetime import date
from app.services.engine_state import get_engine
from app.engine.raptor import seconds_to_hhmm as hhmm
eng = get_engine()
planner, store = eng.planner, eng.store
day = date(2026, 9, 25)  # a Friday
print("model", eng.model.version)"""),
        ("code", """origins = ["Stuttgart Hauptbahnhof (oben)", "Freiburg Hauptbahnhof", "Konstanz Bahnhof"]
destinations = ["Villingen Bahnhof/ZOB", "Schwenningen Bahnhof", "Donaueschingen Bahnhof", "St. Georgen Bahnhof",
                "Triberg Bahnhof", "Bad Dürrheim ZOB", "Königsfeld ZOB", "Schonach Rathaus", "Vöhrenbach ZOB",
                "Bräunlingen Bahnhof"]
rows = []
for o in origins:
    origin = store.resolve_station(o)
    for d in destinations:
        dest = store.resolve_station(d)
        tail = planner.last_connections(day, origin, dest, regional_only=True)
        if not tail:
            rows.append({"from": origin.name, "to": dest.name}); continue
        last = planner.evaluate(tail[-1], dest, True, {}, origin, later_from_origin=tail)
        safe = None
        for journey in reversed(tail):
            ev = last if journey is tail[-1] else planner.evaluate(journey, dest, True, {}, origin,
                                                                  later_from_origin=tail)
            if ev.p_home >= 0.95:
                safe = ev; break
        rows.append({"from": origin.name.split(" ")[0], "to": dest.name,
                     "last departure": hhmm(last.journey.departure), "arrives": hhmm(last.journey.arrival),
                     "changes": last.journey.transfers, "P(home) last": round(last.p_home, 2),
                     "latest ≥95% safe": hhmm(safe.journey.departure) if safe else "none"})
table = pd.DataFrame(rows)
table"""),
        ("md", "**Reading the table:** the last train on the timetable is often *not* the one to plan on. "
               "When the last connection needs a tight change, its chance of getting you home is noticeably "
               "lower, and the latest departure that is at least 95% safe is often an hour earlier."),
        ("code", """print(table.to_markdown(index=False))"""),
    ],
    "03_model_diagnostics.ipynb": [
        ("md", "# 03 · Delay model diagnostics\n\nTest months only (never used for training)."),
        ("code", SETUP),
        ("code", """import json
current = json.loads((ROOT / "ml/artifacts/current.json").read_text())["version"]
meta = json.loads((ROOT / f"ml/artifacts/delay_model_{current}/meta.json").read_text(encoding="utf-8"))
print("train", meta["train_months"], "test", meta["test_months"])
pd.DataFrame({k: meta["metrics"][k] for k in ["model_plan", "model_live", "baseline_hist_quantiles",
                                              "baseline_hist_median", "coverage_plan"]}).round(3)"""),
        ("md", "Coverage below the 0.5 quantile is far above nominal because delays are whole minutes and "
               "most trains are 0–1 min late: `P(delay ≤ q)` includes a big point mass. Upper quantiles, "
               "which drive missed connections, are close to nominal."),
        ("code", """pd.Series(meta["feature_importance"]).sort_values(ascending=False).round(0)"""),
        ("code", """ev = json.loads((ROOT / "ml/artifacts/evaluation.json").read_text(encoding="utf-8"))
pd.DataFrame(ev["brier"]).T.round(3)"""),
        ("code", """pd.DataFrame(ev["by_buffer"]).round(3)"""),
        ("code", """pd.DataFrame(ev["by_pair"]).sort_values("gap", key=abs, ascending=False).head(8).round(3)"""),
    ],
}


def main() -> None:
    for name, cells in NOTEBOOKS.items():
        nb = nbformat.v4.new_notebook()
        nb.cells = [nbformat.v4.new_markdown_cell(src) if kind == "md" else nbformat.v4.new_code_cell(src)
                    for kind, src in cells]
        nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
        NotebookClient(nb, timeout=1800, kernel_name="python3", resources={"metadata": {"path": str(HERE)}}).execute()
        nbformat.write(nb, HERE / name)
        print("executed", name)


if __name__ == "__main__":
    main()
