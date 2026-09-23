"""Historical replay: plan journeys on past evenings, predict, compare with what happened.

    python ml/pipelines/evaluate_replay.py --months 2026-07 2026-08

The delay model used must be trained only on months *before* the replayed ones
(train.py's default split: Mar-Jun train, Jul-Aug test). For every sampled evening
and origin/destination pair we plan the next journey with RAPTOR (timetable only),
then compare three predictors:

* timetable-only  - every connection works, arrival on time, never stranded
* historical median - each leg gets its historical median delay (0/1 prediction)
* simulator       - Heimkommen's Monte Carlo simulator with the quantile model

against the actual train times from the piebro data. Outputs
ml/artifacts/evaluation.json and the charts in docs/img/.
"""

from __future__ import annotations

import argparse
import json
import sys
import time as clock
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.engine.categories import MODELLED_CATEGORIES, allowed_with_deutschlandticket  # noqa: E402
from app.engine.delay_model import GTFS_TO_PRODUCT, DelayModel  # noqa: E402
from app.engine.features import QUANTILES, normalize_line  # noqa: E402
from app.engine.planners import Planner  # noqa: E402
from app.engine.timetable import TimetableStore  # noqa: E402
from app.services.engine_state import _load_station_eva  # noqa: E402

PROCESSED = ROOT / "data" / "processed"
OUT_JSON = ROOT / "ml" / "artifacts" / "evaluation.json"
IMG = ROOT / "docs" / "img"
TOLERANCE = 5 * 60

# Trips people from the Villingen area make home in the evening (and a few reverse trips).
PAIRS = [
    ("Stuttgart Hauptbahnhof (oben)", "Villingen Bahnhof/ZOB"),
    ("Freiburg Hauptbahnhof", "Villingen Bahnhof/ZOB"),
    ("Konstanz Bahnhof", "Villingen Bahnhof/ZOB"),
    ("Karlsruhe Hauptbahnhof", "Villingen Bahnhof/ZOB"),
    ("Offenburg Bahnhof", "St. Georgen Bahnhof"),
    ("Singen (Htw) Bahnhof", "Rottweil Bahnhof"),
    ("Stuttgart Hauptbahnhof (oben)", "Donaueschingen Bahnhof"),
    ("Freiburg Hauptbahnhof", "Tuttlingen Bahnhof"),
    ("Konstanz Bahnhof", "Rottweil Bahnhof"),
    ("Tübingen Hauptbahnhof", "Villingen Bahnhof/ZOB"),
    ("Karlsruhe Hauptbahnhof", "Tuttlingen Bahnhof"),
    ("Stuttgart Hauptbahnhof (oben)", "Triberg Bahnhof"),
]
DEPARTURES = ["17:30", "19:30", "21:00", "22:00"]


def actual_lookup(months: list[str], trains: set[str], evas: set[str]) -> dict:
    """(train_number, eva, 'dep'|'arr', planned datetime) -> (actual datetime, cancelled)."""
    lookup = {}
    for month in months:
        table = pq.read_table(PROCESSED / f"delays-{month}.parquet", columns=[
            "train_number", "eva", "arrival_planned_time", "arrival_change_time", "departure_planned_time",
            "departure_change_time", "arrival_is_canceled", "departure_is_canceled"])
        table = table.filter(pc.and_(pc.is_in(table["train_number"], value_set=pa.array(sorted(trains))),
                                     pc.is_in(table["eva"], value_set=pa.array(sorted(evas)))))
        df = table.to_pandas()
        for r in df.itertuples(index=False):
            if pd.notna(r.departure_planned_time):
                lookup[(r.train_number, r.eva, "dep", r.departure_planned_time.to_pydatetime())] = (
                    r.departure_change_time.to_pydatetime(), bool(r.departure_is_canceled))
            if pd.notna(r.arrival_planned_time):
                lookup[(r.train_number, r.eva, "arr", r.arrival_planned_time.to_pydatetime())] = (
                    r.arrival_change_time.to_pydatetime(), bool(r.arrival_is_canceled))
    return lookup


def historical_median(model: DelayModel, leg, eva: str | None, kind: int, hour: int) -> float:
    tables = model.tables.get("quantiles", {})
    product = GTFS_TO_PRODUCT.get(leg.category, "RB")
    known = model.train_meta.get(str(leg.train_number)) if leg.train_number else None
    line = known[1] if known else normalize_line(leg.route)
    row = (tables.get("line_eva_kind", {}).get(f"{line}|{eva}|{kind}")
           or tables.get("product_kind_hour", {}).get(f"{product}|{kind}|{hour // 3}")
           or tables.get("kind", {}).get(str(kind)))
    return float(row[QUANTILES.index(0.5)]) if row else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", nargs="+", default=["2026-07", "2026-08"])
    parser.add_argument("--every", type=int, default=2, help="Use every n-th day")
    parser.add_argument("--runs", type=int, default=1000)
    args = parser.parse_args()
    settings = get_settings()
    store = TimetableStore.load(engine, settings.data_dir / "timetable_cache.pkl")
    model = DelayModel.load(settings.artifacts_dir)
    if model.is_prior:
        raise SystemExit("train a model first (ml/pipelines/train.py)")
    overlap = set(model.meta["train_months"]) & set(args.months)
    if overlap:
        raise SystemExit(f"model was trained on replay months {overlap}; that would leak")
    station_eva = _load_station_eva()
    planner = Planner(store, model, station_eva, runs=args.runs, seed=7)

    first = date.fromisoformat(args.months[0] + "-01")
    last_month = date.fromisoformat(args.months[-1] + "-01")
    last = (last_month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    days = [first + timedelta(days=i) for i in range(0, (last - first).days + 1, args.every)]
    days = [d for d in days if store.feed_start <= d <= store.feed_end]

    # 1) Plan and predict.
    records = []
    started = clock.perf_counter()
    for day in days:
        for origin_name, dest_name in PAIRS:
            origin, dest = store.resolve_station(origin_name), store.resolve_station(dest_name)
            if origin is None or dest is None:
                continue
            for dep in DEPARTURES:
                after = int(dep[:2]) * 3600 + int(dep[3:]) * 60
                options = planner.options(day, origin, dest, after, 1, regional_only=True)
                if not options:
                    continue
                journey = options[0]
                if not any(leg.category in MODELLED_CATEGORIES for leg in journey.legs):
                    continue
                ev = planner.evaluate(journey, dest, True, {}, origin)
                records.append({"day": day, "origin": origin, "dest": dest, "journey": journey, "ev": ev})
        print(f"{day}: {len(records)} journeys so far ({clock.perf_counter() - started:.0f}s)")

    trains = {leg.train_number for r in records for leg in r["journey"].legs if leg.train_number}
    evas = {e for e in station_eva.values()}
    lookup = actual_lookup(args.months, trains, evas)
    print(f"actual-times lookup: {len(lookup):,} entries")

    # 2) Outcomes and the three predictors.
    rows = []
    for r in records:
        journey, ev, day = r["journey"], r["ev"], r["day"]
        midnight = datetime.combine(day, time())
        actual, median = [], []
        unknown = False
        for leg in journey.legs:
            planned_dep = midnight + timedelta(seconds=leg.departure)
            planned_arr = midnight + timedelta(seconds=leg.arrival)
            if leg.category not in MODELLED_CATEGORIES:
                actual.append((planned_dep, planned_arr, False))
                median.append((leg.departure, leg.arrival))
                continue
            from_eva = station_eva.get(store.station_of_stop(leg.from_stop).id)
            to_eva = station_eva.get(store.station_of_stop(leg.to_stop).id)
            dep = lookup.get((leg.train_number, from_eva, "dep", planned_dep))
            arr = lookup.get((leg.train_number, to_eva, "arr", planned_arr))
            if dep is None or arr is None:
                unknown = True
                break
            actual.append((dep[0], arr[0], dep[1] or arr[1]))
            md = historical_median(model, leg, from_eva, 1, (leg.departure // 3600) % 24)
            ma = historical_median(model, leg, to_eva, 0, (leg.arrival // 3600) % 24)
            median.append((leg.departure + max(md, 0) * 60, leg.arrival + ma * 60))
        if unknown:
            continue

        held, failed_index = True, None
        for i, (dep_t, _arr_t, cancelled) in enumerate(actual):
            change = planner.change_time(journey.legs[i - 1], journey.legs[i]) if i else 0
            if cancelled or (i and actual[i - 1][1] + timedelta(seconds=change) > dep_t):
                held, failed_index = False, i
                break
        planned_arrival = midnight + timedelta(seconds=journey.arrival)
        on_time = held and actual[-1][1] <= planned_arrival + timedelta(seconds=TOLERANCE)
        stranded = False
        if not held:
            ready = actual[failed_index - 1][1] if failed_index else midnight + timedelta(seconds=journey.departure)
            station = store.station_of_stop(journey.legs[failed_index].from_stop)
            onward = planner.router.journey_options(day, station.stops, r["dest"].stops,
                                                    int((ready - midnight).total_seconds()), count=1,
                                                    category_filter=allowed_with_deutschlandticket)
            stranded = not onward

        med_held = all(
            median[i - 1][1] + planner.change_time(journey.legs[i - 1], journey.legs[i]) <= median[i][0]
            for i in range(1, len(median)))
        med_on_time = med_held and median[-1][1] <= journey.arrival + TOLERANCE
        buffers = [(journey.legs[i].departure - journey.legs[i - 1].arrival) // 60 for i in range(1, len(journey.legs))]
        rows.append({
            "day": day.isoformat(), "pair": f"{r['origin'].name} -> {r['dest'].name}",
            "departure_hour": journey.departure // 3600, "transfers": journey.transfers,
            "min_buffer": min(buffers) if buffers else None,
            "held": held, "on_time": on_time, "stranded": stranded,
            "sim_held": ev.result.p_connections, "sim_on_time": ev.p_on_time(), "sim_stranded": ev.result.p_stranded,
            "med_held": float(med_held), "med_on_time": float(med_on_time),
            "med_stranded": 0.0,  # a median-delay plan never predicts being stranded
        })
    df = pd.DataFrame(rows)
    print(f"{len(df)} journeys with complete actual data (of {len(records)} planned)")
    summarize(df, model.version, args.months)


def brier(p: pd.Series, y: pd.Series) -> float:
    return float(np.mean((p.astype(float) - y.astype(float)) ** 2))


def calibration(p: pd.Series, y: pd.Series, bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    out = []
    for b in range(bins):
        mask = idx == b
        if mask.sum():
            out.append({"bin": b, "count": int(mask.sum()), "mean_predicted": float(p[mask].mean()),
                        "observed": float(y[mask].astype(float).mean())})
    return out


def summarize(df: pd.DataFrame, version: str, months: list[str]) -> None:
    targets = {"held": "all connections work", "on_time": "arrive ≤ 5 min late", "stranded": "stranded"}
    table = {}
    for target in targets:
        y = df[target]
        table[target] = {
            "observed_rate": float(y.mean()),
            "timetable_only": brier(pd.Series(0.0 if target == "stranded" else 1.0, index=df.index), y),
            "historical_median": brier(df[f"med_{target}"], y),
            "simulator": brier(df[f"sim_{target}"], y),
        }
    transfer = df[df["transfers"] > 0]
    by_buffer = []
    for label, mask in (("≤ 5 min", transfer["min_buffer"] <= 5), ("6-10 min", transfer["min_buffer"].between(6, 10)),
                        ("> 10 min", transfer["min_buffer"] > 10)):
        part = transfer[mask]
        if len(part):
            by_buffer.append({"buffer": label, "journeys": int(len(part)), "observed_held": float(part["held"].mean()),
                              "predicted_held": float(part["sim_held"].mean()),
                              "brier_simulator": brier(part["sim_held"], part["held"]),
                              "brier_timetable": brier(pd.Series(1.0, index=part.index), part["held"])})
    by_pair = (df.groupby("pair").agg(journeys=("held", "size"), observed_on_time=("on_time", "mean"),
                                      predicted_on_time=("sim_on_time", "mean"))
               .reset_index().sort_values("journeys", ascending=False))
    by_pair["gap"] = by_pair["predicted_on_time"] - by_pair["observed_on_time"]
    result = {
        "model_version": version, "months": months, "journeys": int(len(df)),
        "journeys_with_transfer": int(len(transfer)), "brier": table,
        "calibration": {"on_time": calibration(df["sim_on_time"], df["on_time"]),
                        "held": calibration(transfer["sim_held"], transfer["held"]) if len(transfer) else []},
        "by_buffer": by_buffer,
        "by_pair": by_pair.round(4).to_dict(orient="records"),
    }
    OUT_JSON.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"journeys": result["journeys"], "brier": table, "by_buffer": by_buffer}, indent=2,
                     ensure_ascii=False))
    plot(result)


def plot(result: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    IMG.mkdir(parents=True, exist_ok=True)
    surface, ink, ink2, grid = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
    blue, orange = "#2a78d6", "#eb6834"
    plt.rcParams.update({"font.size": 11, "axes.edgecolor": grid, "axes.labelcolor": ink2, "xtick.color": ink2,
                         "ytick.color": ink2, "text.color": ink, "axes.titlecolor": ink})

    # Calibration (reliability) plot
    fig, ax = plt.subplots(figsize=(6.4, 5.6), facecolor=surface)
    ax.set_facecolor(surface)
    ax.plot([0, 1], [0, 1], color=ink2, lw=1, ls=(0, (4, 4)), label="Perfect calibration")
    for key, color, label in (("on_time", blue, "Arrive ≤ 5 min late"), ("held", orange, "All connections work")):
        pts = result["calibration"][key]
        if not pts:
            continue
        x = [p["mean_predicted"] for p in pts]
        y = [p["observed"] for p in pts]
        sizes = [max(30, min(300, p["count"] * 3)) for p in pts]
        ax.plot(x, y, color=color, lw=2)
        ax.scatter(x, y, s=sizes, color=color, edgecolor=surface, linewidth=2, zorder=3, label=label)
    ax.set_xlim(0, 1.02)
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("Predicted probability")
    ax.set_ylabel("Observed frequency")
    ax.set_title(f"Simulator calibration, replay of {', '.join(result['months'])}", loc="left", fontsize=12)
    ax.grid(color=grid, lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper left")
    ax.text(1.0, 0.02, "marker area ∝ journeys in bin", ha="right", color=ink2, fontsize=9)
    fig.tight_layout()
    fig.savefig(IMG / "calibration.png", dpi=150)
    plt.close(fig)

    # Brier score comparison (lower is better)
    targets = ["held", "on_time", "stranded"]
    labels = ["All connections\nwork", "Arrive ≤ 5 min\nlate", "Stranded"]
    methods = [("timetable_only", "Timetable only", ink2), ("historical_median", "Historical median", orange),
               ("simulator", "Heimkommen simulator", blue)]
    fig, ax = plt.subplots(figsize=(7.2, 4.4), facecolor=surface)
    ax.set_facecolor(surface)
    width = 0.26
    for i, (key, label, color) in enumerate(methods):
        values = [result["brier"][t][key] for t in targets]
        xs = np.arange(len(targets)) + (i - 1) * (width + 0.02)
        ax.bar(xs, values, width=width, color=color, label=label, edgecolor=surface, linewidth=2)
        for x, v in zip(xs, values, strict=True):
            ax.text(x, v + 0.004, f"{v:.3f}", ha="center", va="bottom", fontsize=8.5, color=ink2)
    ax.set_xticks(np.arange(len(targets)), labels)
    ax.set_ylabel("Brier score (lower is better)")
    ax.set_title("Probability forecasts vs. what happened", loc="left", fontsize=12)
    ax.grid(axis="y", color=grid, lw=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.legend(frameon=False, ncols=3, loc="upper center", bbox_to_anchor=(0.5, -0.14))
    fig.tight_layout()
    fig.savefig(IMG / "brier.png", dpi=150)
    plt.close(fig)
    print(f"charts written to {IMG.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
