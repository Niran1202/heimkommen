"""Load the trained delay model and predict delay distributions for journey legs."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.engine.categories import MODELLED_CATEGORIES
from app.engine.features import QUANTILES, encode, normalize_line

log = logging.getLogger(__name__)

# Used when no trained artifact is available: roughly the regional BW distribution
# (median 1 min, p90 ~10 min) so the app still behaves sensibly. Clearly flagged as "prior".
PRIOR_QUANTILES = {
    "FV": [0, 0, 1, 3, 8, 17, 26, 40],
    "RE": [0, 0, 0, 1, 4, 10, 16, 26],
    "RB": [0, 0, 0, 1, 3, 8, 13, 21],
    "S": [0, 0, 0, 1, 3, 7, 11, 18],
}
PRIOR_CANCEL = 0.03
GTFS_TO_PRODUCT = {"FV": "FV", "RE": "RE", "RB": "RB", "S": "S", "RAIL": "RB"}


@dataclass
class LegQuery:
    category: str  # GTFS category (FV/RE/RB/S/RAIL/BUS/...)
    route_name: str
    train_number: str | None
    board_eva: str | None
    alight_eva: str | None
    board_hour: int
    alight_hour: int
    weekday: int
    board_pos: int
    alight_pos: int
    stop_count: int
    prev_delay: float | None = None  # known delay (live data) at boarding


@dataclass
class LegPrediction:
    dep_q: np.ndarray  # minutes at QUANTILES
    arr_q: np.ndarray
    p_cancel: float
    modelled: bool


class DelayModel:
    def __init__(self, version: str, boosters: list | None, meta: dict, tables: dict, train_meta: dict) -> None:
        self.version = version
        self.boosters = boosters
        self.meta = meta
        self.tables = tables
        self.train_meta = train_meta
        self.categories = meta.get("categories", {})

    @property
    def is_prior(self) -> bool:
        return self.boosters is None

    @classmethod
    def load(cls, artifacts_dir: Path) -> DelayModel:
        current = artifacts_dir / "current.json"
        if not current.exists():
            log.warning("no trained delay model in %s - using prior distributions", artifacts_dir)
            return cls.prior()
        try:
            import lightgbm as lgb

            version = json.loads(current.read_text(encoding="utf-8"))["version"]
            model_dir = artifacts_dir / f"delay_model_{version}"
            meta = json.loads((model_dir / "meta.json").read_text(encoding="utf-8"))
            boosters = [lgb.Booster(model_file=str(model_dir / f"q{int(q * 100):02d}.txt")) for q in meta["quantiles"]]
            tables = json.loads((model_dir / "tables.json").read_text(encoding="utf-8"))
            train_meta = json.loads((model_dir / "train_meta.json").read_text(encoding="utf-8"))
            log.info("loaded delay model %s", version)
            return cls(version, boosters, meta, tables, train_meta)
        except Exception:  # pragma: no cover - broken artifact should not take the API down
            log.exception("failed to load delay model - using prior distributions")
            return cls.prior()

    @classmethod
    def prior(cls) -> DelayModel:
        return cls("prior-0", None, {"quantiles": QUANTILES}, {}, {})

    # ------------------------------------------------------------ predict
    def predict(self, legs: list[LegQuery]) -> list[LegPrediction]:
        zeros = np.zeros(len(QUANTILES))
        results: list[LegPrediction | None] = [None] * len(legs)
        rows: list[dict[str, Any]] = []
        for i, leg in enumerate(legs):
            if leg.category not in MODELLED_CATEGORIES:
                results[i] = LegPrediction(zeros, zeros, 0.0, modelled=False)
                continue
            product = GTFS_TO_PRODUCT.get(leg.category, "RB")
            train_type, line = self._train_identity(leg, product)
            base = {"product": product, "train_type": train_type, "line": line, "weekday": leg.weekday,
                    "position": None}
            rows.append({**base, "i": i, "eva": leg.board_eva or "", "hour": leg.board_hour,
                         "station_num": leg.board_pos + 1, "position": (leg.board_pos + 1) / leg.stop_count,
                         "is_departure": 1, "prev_delay": leg.prev_delay})
            rows.append({**base, "i": i, "eva": leg.alight_eva or "", "hour": leg.alight_hour,
                         "station_num": leg.alight_pos + 1, "position": (leg.alight_pos + 1) / leg.stop_count,
                         "is_departure": 0, "prev_delay": leg.prev_delay})
        if rows:
            frame = pd.DataFrame(rows)
            quantiles = self._quantiles(frame)
            for j in range(0, len(rows), 2):
                i = rows[j]["i"]
                results[i] = LegPrediction(
                    dep_q=np.maximum(quantiles[j], 0.0),
                    arr_q=quantiles[j + 1],
                    p_cancel=self._cancel_rate(rows[j]["line"], legs[i].board_eva, rows[j]["product"]),
                    modelled=True,
                )
        return [r for r in results if r is not None]

    def _train_identity(self, leg: LegQuery, product: str) -> tuple[str, str]:
        known = self.train_meta.get(str(leg.train_number)) if leg.train_number else None
        if known:
            return known[0], known[1]
        line = normalize_line(leg.route_name)
        if not line or line in {"RE", "RB", "S"}:
            line = product
        return "", line

    def _quantiles(self, frame: pd.DataFrame) -> np.ndarray:
        if self.boosters is None:
            return np.array([PRIOR_QUANTILES.get(p, PRIOR_QUANTILES["RB"]) for p in frame["product"]], dtype=float)
        x = encode(frame, self.categories)
        preds = np.column_stack([b.predict(x) for b in self.boosters])
        return np.sort(preds, axis=1)

    def _cancel_rate(self, line: str, eva: str | None, product: str) -> float:
        tables = self.tables.get("cancellation")
        if not tables:
            return PRIOR_CANCEL
        return float(
            tables["line_eva"].get(f"{line}|{eva}")
            or tables["line"].get(line)
            or tables["product"].get(product)
            or tables["global"]
        )
