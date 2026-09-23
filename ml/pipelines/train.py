"""Train the LightGBM quantile delay model.

    python ml/pipelines/train.py --test-months 2026-07 2026-08

* Time split: every month before the first test month is training data. Never random.
* One LightGBM model per quantile (arrival and departure events share a model via
  ``is_departure``).
* ``prev_delay`` (delay at the previous stop) is masked for half of the training rows so the
  model works both at planning time (unknown) and with live data (known).
* Baseline: historical quantiles per (line, station, arrival/departure), which is what
  "use the historical median" generalises to for a distribution.
* The new version is activated only if it is at least as good as the current one
  (mean pinball loss on the test months), unless --force.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.engine.features import (  # noqa: E402
    CATEGORICAL,
    DELAY_CLIP,
    QUANTILES,
    encode,
    events_from_stops,
)

PROCESSED = ROOT / "data" / "processed"
ARTIFACTS = ROOT / "ml" / "artifacts"
RNG = np.random.default_rng(42)


def load_events(months: list[str], per_month: int) -> pd.DataFrame:
    frames = []
    for month in months:
        path = PROCESSED / f"delays-{month}.parquet"
        stops = pd.read_parquet(path)
        stops = stops[~stops["is_additional_stop"]]
        events = events_from_stops(stops)
        if per_month and len(events) > per_month:
            events = events.sample(per_month, random_state=int(RNG.integers(1 << 30)))
        frames.append(events)
        print(f"  {month}: {len(events):,} events")
    return pd.concat(frames, ignore_index=True)


def pinball(y: np.ndarray, pred: np.ndarray, q: float) -> float:
    diff = y - pred
    return float(np.mean(np.maximum(q * diff, (q - 1) * diff)))


def cancellation_tables(events: pd.DataFrame) -> dict:
    """Historical cancellation rates with hierarchical fallback (shrunk towards the parent)."""
    dep = events[events["is_departure"] == 1]
    tables: dict[str, dict] = {}
    prior_count = 50.0
    product_rate = dep.groupby("product")["cancelled"].mean()
    tables["product"] = product_rate.round(5).to_dict()
    line = dep.groupby(["product", "line"])["cancelled"].agg(["sum", "count"]).reset_index()
    line["rate"] = (line["sum"] + prior_count * line["product"].map(product_rate)) / (line["count"] + prior_count)
    tables["line"] = {r.line: round(float(r.rate), 5) for r in line.itertuples()}
    line_rate = pd.Series(tables["line"])
    le = dep.groupby(["line", "eva"])["cancelled"].agg(["sum", "count"]).reset_index()
    le["parent"] = le["line"].map(line_rate).fillna(float(dep["cancelled"].mean()))
    le["rate"] = (le["sum"] + prior_count * le["parent"]) / (le["count"] + prior_count)
    tables["line_eva"] = {f"{r.line}|{r.eva}": round(float(r.rate), 5) for r in le.itertuples() if r.count >= 20}
    tables["global"] = round(float(dep["cancelled"].mean()), 5)
    return tables


def empirical_quantiles(events: pd.DataFrame, keys: list[str], min_count: int) -> dict[str, list[float]]:
    grouped = events.groupby(keys)["delay"]
    counts = grouped.size()
    qs = grouped.quantile(QUANTILES).unstack()
    qs = qs[counts.reindex(qs.index) >= min_count]
    return {"|".join(str(k) for k in (idx if isinstance(idx, tuple) else (idx,))): [round(float(v), 2) for v in row]
            for idx, row in qs.iterrows()}


def baseline_predict(frame: pd.DataFrame, tables: dict) -> np.ndarray:
    """Historical quantiles: (line, eva, kind) -> (product, kind, hour band) -> (kind)."""
    out = np.zeros((len(frame), len(QUANTILES)))
    fine, coarse, top = tables["line_eva_kind"], tables["product_kind_hour"], tables["kind"]
    for i, (line, eva, kind, product, hour) in enumerate(zip(
            frame["line"], frame["eva"], frame["is_departure"], frame["product"], frame["hour"], strict=True)):
        row = fine.get(f"{line}|{eva}|{kind}") or coarse.get(f"{product}|{kind}|{hour // 3}") or top[str(kind)]
        out[i] = row
    return out


def next_version() -> str:
    existing = [int(p.name.split("_v")[-1]) for p in ARTIFACTS.glob("delay_model_v*") if p.is_dir()]
    return f"v{max(existing, default=0) + 1}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-months", nargs="+", default=["2026-07", "2026-08"])
    parser.add_argument("--train-per-month", type=int, default=700_000)
    parser.add_argument("--test-per-month", type=int, default=300_000)
    parser.add_argument("--rounds", type=int, default=300)
    parser.add_argument("--force", action="store_true", help="Activate even if worse than the current model")
    args = parser.parse_args()

    months = sorted(p.stem.replace("delays-", "") for p in PROCESSED.glob("delays-*.parquet"))
    test_months = [m for m in months if m in args.test_months]
    train_months = [m for m in months if m < min(test_months)]
    if not train_months or not test_months:
        raise SystemExit(f"need training and test months, found {months}")
    print(f"train months {train_months}, test months {test_months}")

    print("loading training events")
    train = load_events(train_months, args.train_per_month)
    print("loading test events")
    test = load_events(test_months, args.test_per_month)

    train_ok = train[~train["cancelled"] & train["delay"].notna()].copy()
    test_ok = test[~test["cancelled"] & test["delay"].notna()].copy()
    train_ok["delay"] = train_ok["delay"].clip(*DELAY_CLIP)
    test_ok["delay"] = test_ok["delay"].clip(*DELAY_CLIP)
    # Planning-time rows do not know the previous delay: mask half of the training rows.
    mask = RNG.random(len(train_ok)) < 0.5
    train_ok.loc[mask, "prev_delay"] = np.nan

    categories = {c: sorted(train_ok[c].astype(str).unique().tolist()) for c in CATEGORICAL}
    x_train = encode(train_ok, categories)
    y_train = train_ok["delay"].to_numpy()
    test_plan = test_ok.assign(prev_delay=np.nan)
    x_test_plan = encode(test_plan, categories)
    x_test_live = encode(test_ok, categories)
    y_test = test_ok["delay"].to_numpy()

    version = next_version()
    out_dir = ARTIFACTS / f"delay_model_{version}"
    out_dir.mkdir(parents=True, exist_ok=True)

    tables = {
        "line_eva_kind": empirical_quantiles(train_ok, ["line", "eva", "is_departure"], 30),
        "product_kind_hour": empirical_quantiles(train_ok.assign(hb=train_ok["hour"] // 3),
                                                 ["product", "is_departure", "hb"], 30),
        "kind": empirical_quantiles(train_ok, ["is_departure"], 1),
    }
    baseline = baseline_predict(test_ok, tables)
    median_only = np.repeat(baseline[:, [QUANTILES.index(0.5)]], len(QUANTILES), axis=1)

    metrics: dict[str, dict] = {"model_plan": {}, "model_live": {}, "baseline_hist_quantiles": {},
                                "baseline_hist_median": {}, "coverage_plan": {}, "coverage_baseline": {}}
    params = {
        "objective": "quantile", "learning_rate": 0.08, "num_leaves": 63, "min_data_in_leaf": 200,
        "feature_fraction": 0.9, "bagging_fraction": 0.8, "bagging_freq": 1, "cat_smooth": 20,
        "max_cat_to_onehot": 8, "verbose": -1, "seed": 42,
    }
    dataset = lgb.Dataset(x_train, y_train, categorical_feature=CATEGORICAL, free_raw_data=False)
    for i, q in enumerate(QUANTILES):
        booster = lgb.train({**params, "alpha": q}, dataset, num_boost_round=args.rounds)
        booster.save_model(str(out_dir / f"q{int(q * 100):02d}.txt"))
        pred_plan = booster.predict(x_test_plan)
        pred_live = booster.predict(x_test_live)
        key = f"{q:.2f}"
        metrics["model_plan"][key] = pinball(y_test, pred_plan, q)
        metrics["model_live"][key] = pinball(y_test, pred_live, q)
        metrics["baseline_hist_quantiles"][key] = pinball(y_test, baseline[:, i], q)
        metrics["baseline_hist_median"][key] = pinball(y_test, median_only[:, i], q)
        metrics["coverage_plan"][key] = float(np.mean(y_test <= pred_plan))
        metrics["coverage_baseline"][key] = float(np.mean(y_test <= baseline[:, i]))
        print(f"  q={q:.2f}  pinball model(plan)={metrics['model_plan'][key]:.3f} "
              f"live={metrics['model_live'][key]:.3f} hist-q={metrics['baseline_hist_quantiles'][key]:.3f} "
              f"hist-median={metrics['baseline_hist_median'][key]:.3f}  coverage={metrics['coverage_plan'][key]:.3f}")
    summary = {name: float(np.mean(list(vals.values()))) for name, vals in metrics.items()
               if not name.startswith("coverage")}
    print("mean pinball:", {k: round(v, 4) for k, v in summary.items()})

    # Cancellation: historical rates, evaluated with the Brier score on the test months.
    cancel = cancellation_tables(train)
    test_dep = test[test["is_departure"] == 1]
    p_cancel = np.array([cancel["line_eva"].get(f"{line}|{eva}", cancel["line"].get(line, cancel["global"]))
                         for line, eva in zip(test_dep["line"], test_dep["eva"], strict=True)])
    y_cancel = test_dep["cancelled"].to_numpy().astype(float)
    cancel_metrics = {
        "brier_rates": float(np.mean((p_cancel - y_cancel) ** 2)),
        "brier_global_rate": float(np.mean((cancel["global"] - y_cancel) ** 2)),
        "observed_rate": float(y_cancel.mean()),
    }
    print("cancellation:", cancel_metrics)

    # Train number -> operator/line, so GTFS trips can be mapped onto the model's categories.
    recent = train.sort_values("planned").drop_duplicates("train_number", keep="last")
    train_meta = {str(r.train_number): [r.train_type, r.line] for r in recent.itertuples() if r.train_number}

    meta = {
        "version": version,
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "quantiles": QUANTILES,
        "categories": categories,
        "train_months": train_months,
        "test_months": test_months,
        "n_train": int(len(train_ok)),
        "n_test": int(len(test_ok)),
        "metrics": metrics,
        "mean_pinball": summary,
        "cancellation": cancel_metrics,
        "feature_importance": dict(zip(x_train.columns, booster.feature_importance("gain").round(1).tolist(),
                                       strict=True)),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (out_dir / "tables.json").write_text(json.dumps({"cancellation": cancel, "quantiles": tables}),
                                         encoding="utf-8")
    (out_dir / "train_meta.json").write_text(json.dumps(train_meta), encoding="utf-8")

    current_file = ARTIFACTS / "current.json"
    current = json.loads(current_file.read_text(encoding="utf-8")) if current_file.exists() else None
    activate = args.force or current is None
    if current and not activate:
        old_meta_path = ARTIFACTS / f"delay_model_{current['version']}" / "meta.json"
        old_meta = json.loads(old_meta_path.read_text(encoding="utf-8"))
        activate = summary["model_plan"] <= old_meta["mean_pinball"]["model_plan"] + 1e-9
    if activate:
        current_file.write_text(json.dumps({"version": version}), encoding="utf-8")
        print(f"activated delay model {version} -> {out_dir.relative_to(ROOT)}")
    else:
        print(f"model {version} is worse than the active one; kept {current['version']}")


if __name__ == "__main__":
    main()
