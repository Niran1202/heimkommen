"""Accuracy dashboard data: live prediction-vs-outcome calibration + offline evaluation."""

from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.prediction import Outcome, PredictionLog


def calibration_bins(predicted: np.ndarray, observed: np.ndarray, bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        mask = (predicted >= lo) & ((predicted < hi) if hi < 1 else (predicted <= hi))
        if mask.sum() == 0:
            continue
        out.append({"bin_start": round(float(lo), 2), "bin_end": round(float(hi), 2), "count": int(mask.sum()),
                    "mean_predicted": round(float(predicted[mask].mean()), 4),
                    "observed_rate": round(float(observed[mask].mean()), 4)})
    return out


def brier(predicted: np.ndarray, observed: np.ndarray) -> float | None:
    return round(float(np.mean((predicted - observed) ** 2)), 4) if len(predicted) else None


def parse_period(period: str) -> int:
    if period.endswith("d") and period[:-1].isdigit():
        return max(1, min(int(period[:-1]), 365))
    raise ValueError("period must look like '30d'")


def live_accuracy(db: Session, period: str) -> dict:
    days = parse_period(period)
    since = date.today() - timedelta(days=days)
    rows = db.execute(
        select(PredictionLog.journey_key, PredictionLog.service_date, PredictionLog.p_connections,
               PredictionLog.p_on_time, PredictionLog.p_stranded, Outcome.connections_held, Outcome.on_time,
               Outcome.status)
        .join(Outcome, Outcome.prediction_id == PredictionLog.id)
        .where(PredictionLog.service_date >= since, Outcome.status != "unknown")
        .order_by(PredictionLog.created_at)
    ).all()
    # One prediction per journey and day (the first one), so popular searches don't dominate.
    seen, unique = set(), []
    for row in rows:
        if (row.journey_key, row.service_date) not in seen:
            seen.add((row.journey_key, row.service_date))
            unique.append(row)
    result: dict = {"period": period, "matched_predictions": len(unique)}
    if not unique:
        return result
    p_conn = np.array([r.p_connections for r in unique])
    held = np.array([bool(r.connections_held) for r in unique], dtype=float)
    p_on_time = np.array([r.p_on_time for r in unique])
    on_time = np.array([bool(r.on_time) for r in unique], dtype=float)
    p_stranded = np.array([r.p_stranded for r in unique])
    stranded = np.array([r.status == "stranded" for r in unique], dtype=float)
    result.update({
        "brier": {
            "connections": brier(p_conn, held), "on_time": brier(p_on_time, on_time),
            "stranded": brier(p_stranded, stranded),
            "timetable_only_connections": brier(np.ones_like(held), held),
            "timetable_only_on_time": brier(np.ones_like(on_time), on_time),
        },
        "observed": {"connections_held": round(float(held.mean()), 4), "on_time": round(float(on_time.mean()), 4),
                     "stranded": round(float(stranded.mean()), 4)},
        "calibration_connections": calibration_bins(p_conn, held),
        "calibration_on_time": calibration_bins(p_on_time, on_time),
    })
    return result


def offline_accuracy() -> dict:
    settings = get_settings()
    out: dict = {}
    current = settings.artifacts_dir / "current.json"
    if current.exists():
        version = json.loads(current.read_text(encoding="utf-8"))["version"]
        meta_path = settings.artifacts_dir / f"delay_model_{version}" / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            out["model"] = {k: meta.get(k) for k in ("version", "trained_at", "train_months", "test_months",
                                                      "n_train", "n_test", "mean_pinball", "cancellation")}
            out["model"]["coverage"] = meta["metrics"].get("coverage_plan")
    evaluation = settings.artifacts_dir / "evaluation.json"
    if evaluation.exists():
        out["replay"] = json.loads(evaluation.read_text(encoding="utf-8"))
    return out
