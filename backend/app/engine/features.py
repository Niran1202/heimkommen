"""Feature definitions shared by offline training (ml/) and online prediction (engine/).

One row is one *event*: a train arriving at or departing from a station.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

QUANTILES = [0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.98]
CATEGORICAL = ["product", "train_type", "line", "eva"]
NUMERIC = ["hour", "weekday", "station_num", "position", "is_departure", "prev_delay"]
FEATURES = CATEGORICAL + NUMERIC
DELAY_CLIP = (-5.0, 120.0)
LONG_DISTANCE = {"ICE", "IC", "EC", "ECE", "EN", "NJ", "FLX", "TGV", "RJ", "RJX", "D"}


def normalize_line(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", "", str(value)).upper()


def product_of(line: str | None, train_type: str | None) -> str:
    """RE / RB / S / FV / OTHER, from the line name (preferred) or the train type."""
    tt = (train_type or "").upper()
    if tt in LONG_DISTANCE:
        return "FV"
    line = normalize_line(line)
    match = re.match(r"[A-Z]+", line)
    prefix = match.group(0) if match else ""
    if prefix in {"RE", "IRE", "MEX"}:
        return "RE"
    if prefix in {"RB", "R", "RS"}:
        return "RB"
    if prefix == "S":
        return "S"
    if tt in {"RE", "IRE", "MEX"}:
        return "RE"
    if tt in {"RB"}:
        return "RB"
    if tt == "S":
        return "S"
    return "OTHER" if not line else "RB"


def events_from_stops(df: pd.DataFrame) -> pd.DataFrame:
    """Turn piebro stop rows into arrival/departure events with features and targets."""
    df = df.copy()
    df["line"] = df["line_number"].map(normalize_line)
    df.loc[df["line"] == "", "line"] = df["train_type"].fillna("").str.upper()
    df["product"] = [product_of(line, tt) for line, tt in zip(df["line_number"], df["train_type"], strict=True)]
    df["train_type"] = df["train_type"].fillna("").str.upper()
    df["arr_delay"] = (df["arrival_change_time"] - df["arrival_planned_time"]).dt.total_seconds() / 60
    df["dep_delay"] = (df["departure_change_time"] - df["departure_planned_time"]).dt.total_seconds() / 60
    df = df.sort_values(["train_line_ride_id", "train_line_station_num"])
    df["prev_delay"] = df.groupby("train_line_ride_id", sort=False)["dep_delay"].shift(1)
    df["ride_len"] = df.groupby("train_line_ride_id", sort=False)["train_line_station_num"].transform("max")
    df["station_num"] = df["train_line_station_num"].astype(float)
    df["position"] = df["station_num"] / df["ride_len"].clip(lower=1)

    parts = []
    for kind, planned, delay, cancelled in (
        (0, "arrival_planned_time", "arr_delay", "arrival_is_canceled"),
        (1, "departure_planned_time", "dep_delay", "departure_is_canceled"),
    ):
        part = df[df[planned].notna()]
        parts.append(pd.DataFrame({
            "ride_id": part["train_line_ride_id"],
            "train_number": part["train_number"],
            "eva": part["eva"],
            "product": part["product"],
            "train_type": part["train_type"],
            "line": part["line"],
            "planned": part[planned],
            "hour": part[planned].dt.hour,
            "weekday": part[planned].dt.weekday,
            "station_num": part["station_num"],
            "position": part["position"],
            "is_departure": kind,
            "prev_delay": part["prev_delay"],
            "delay": part[delay],
            "cancelled": part[cancelled].astype(bool),
        }))
    events = pd.concat(parts, ignore_index=True)
    events["month"] = events["planned"].dt.strftime("%Y-%m")
    return events


def encode(frame: pd.DataFrame, categories: dict[str, list[str]]) -> pd.DataFrame:
    """Apply the training category vocabularies (unknown values become missing)."""
    out = pd.DataFrame(index=frame.index)
    for col in CATEGORICAL:
        values = frame[col].astype("string").fillna("")
        out[col] = pd.Categorical(values, categories=categories[col])
    for col in NUMERIC:
        out[col] = pd.to_numeric(frame[col], errors="coerce").astype(float)
    return out[FEATURES]


def sample_from_quantiles(quantile_values: np.ndarray, u: np.ndarray) -> np.ndarray:
    """Inverse-CDF sampling from predicted quantiles (piecewise linear, extrapolated tails).

    ``quantile_values`` has shape (n, len(QUANTILES)), ``u`` has shape (n, runs).
    """
    q = np.sort(np.asarray(quantile_values, dtype=float), axis=1)
    levels = np.asarray(QUANTILES)
    low = q[:, :1] - (q[:, 1:2] - q[:, :1])  # linear extrapolation to the 0th percentile
    high = q[:, -1:] + 2.0 * (q[:, -1:] - q[:, -3:-2])  # heavier right tail up to the 100th
    grid_levels = np.concatenate([[0.0], levels, [1.0]])
    grid_values = np.concatenate([low, q, high], axis=1)
    out = np.empty_like(u, dtype=float)
    for i in range(q.shape[0]):
        out[i] = np.interp(u[i], grid_levels, grid_values[i])
    return np.clip(out, DELAY_CLIP[0], DELAY_CLIP[1] * 2)
