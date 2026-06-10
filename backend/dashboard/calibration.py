"""
Calibration & self-learning weights for the meta-model.

Tier 1: log every prediction → grade against realized N-bar returns
Tier 3: use accumulated outcomes to UPDATE the per-source weights with
        Bayesian shrinkage (works even when N is small, smoothly improves)

Persistence: JSONL at data/cache/predictions.jsonl — append-only, never modified.

Self-learning principle:
  Each signal SOURCE (e.g. "Vol Regime Asymmetry" or "Short Squeeze Detector")
  contributes a log-odds term. After 5 bars we know the realized direction.
  We compute:
      hit_rate_source = P(source's call was correct | source signalled)
  The weight multiplier becomes:
      mult = 0.5 + (hit_rate - 0.5) × 2     # 0.5 hit = 0× weight; 1.0 hit = 2× weight
  With Bayesian shrinkage toward 1.0 when N is small:
      mult = (n × mult + κ × 1.0) / (n + κ)        # κ = prior strength = 10
"""

from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd


_PREDICTION_LOG = Path(__file__).parent.parent / "data" / "cache" / "predictions.jsonl"
_CALIBRATION_OUT = Path(__file__).parent.parent / "data" / "cache" / "source_weights.json"
_PREDICTION_LOG.parent.mkdir(parents=True, exist_ok=True)

_HORIZON_DAYS = 5      # grade predictions vs 5-day forward return
_GRACE_BARS   = 2      # need ≥ 2 bars elapsed AFTER prediction to grade
_SHRINKAGE_K  = 10     # Bayesian prior strength (10 = needs ~10 samples to fully trust)


def log_prediction(price: float, as_of: str, edge: dict) -> None:
    """Append one prediction record (idempotent by as_of date — only one per day)."""
    if not edge or edge.get("error"):
        return
    record = {
        "ts":           time.time(),
        "as_of":        as_of,
        "price_then":   price,
        "label":        edge.get("label"),
        "p_up":         edge.get("p_up"),
        "log_odds":     edge.get("log_odds"),
        "expected_ret": edge.get("expected_return_pct"),
        "contribs":     [
            {"source": c["source"], "kind": c["kind"],
             "signal": c["signal"], "log_odds": c["log_odds"]}
            for c in (edge.get("contributions") or [])
        ],
    }
    # Idempotency: skip if we've already logged today's as_of date
    existing_dates = _list_logged_as_of_dates()
    if as_of and as_of[:10] in existing_dates:
        return
    with _PREDICTION_LOG.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _list_logged_as_of_dates() -> set:
    if not _PREDICTION_LOG.exists():
        return set()
    dates = set()
    with _PREDICTION_LOG.open() as f:
        for line in f:
            try:
                r = json.loads(line)
                d = (r.get("as_of") or "")[:10]
                if d:
                    dates.add(d)
            except Exception:
                continue
    return dates


def _load_predictions() -> list[dict]:
    if not _PREDICTION_LOG.exists():
        return []
    out = []
    with _PREDICTION_LOG.open() as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def grade_predictions(price_df: pd.DataFrame, horizon: int = _HORIZON_DAYS) -> dict:
    """
    Grade all logged predictions against realized N-bar forward returns.
    price_df: DataFrame with DatetimeIndex and 'close' column.

    Returns:
        {
          "n_total": total predictions logged,
          "n_graded": predictions with N-bar data available,
          "overall_hit_rate": fraction directionally correct,
          "calibration":   list of (predicted_p_up_bucket, realized_hit_rate),
          "by_source":    {source: {n: int, hits: int, hit_rate: float, weight_mult: float}},
        }
    """
    preds = _load_predictions()
    if not preds:
        return {"n_total": 0, "n_graded": 0, "overall_hit_rate": 0.5,
                "calibration": [], "by_source": {}}

    closes = price_df["close"]
    closes_index = pd.DatetimeIndex(closes.index).normalize()
    close_map = pd.Series(closes.values, index=closes_index)

    overall_n = 0
    overall_hits = 0
    bucket_hits  = defaultdict(lambda: [0, 0])   # bucket → [hits, count]
    by_source    = defaultdict(lambda: [0, 0])   # source → [hits, count]
    n_graded = 0

    for r in preds:
        as_of = r.get("as_of", "")[:10]
        if not as_of:
            continue
        try:
            d0 = pd.Timestamp(as_of).normalize()
        except Exception:
            continue

        # Need at least horizon bars AFTER d0
        future = closes_index[closes_index > d0]
        if len(future) < _GRACE_BARS:
            continue

        # Use the bar at d0 (or nearest past) as anchor, horizon-th future bar as target
        anchor_candidates = closes_index[closes_index <= d0]
        if len(anchor_candidates) == 0:
            continue
        anchor = anchor_candidates[-1]
        target_idx = min(horizon - 1, len(future) - 1)
        target = future[target_idx]

        p0 = float(close_map.loc[anchor])
        p1 = float(close_map.loc[target])
        if not (p0 > 0 and p1 > 0):
            continue
        realized_ret = (p1 - p0) / p0
        realized_up = realized_ret > 0
        n_graded += 1

        # Overall label hit
        label_signal = {"BUY": 1, "SELL": -1, "HOLD": 0}.get(r.get("label", ""), 0)
        if label_signal != 0:
            overall_n += 1
            if (label_signal > 0) == realized_up:
                overall_hits += 1

        # Calibration buckets (P(up) → realized hit_rate)
        p_up = r.get("p_up", 0.5)
        bucket = round(p_up * 10) / 10   # 0.0, 0.1, ..., 1.0
        bucket_hits[bucket][1] += 1
        if realized_up:
            bucket_hits[bucket][0] += 1

        # Per-source grading
        for c in r.get("contribs", []):
            src = c.get("source", "?")
            sig = c.get("signal", 0)
            if sig == 0:
                continue
            by_source[src][1] += 1
            if (sig > 0) == realized_up:
                by_source[src][0] += 1

    overall_hit_rate = (overall_hits / overall_n) if overall_n > 0 else 0.5

    calibration = []
    for bucket in sorted(bucket_hits.keys()):
        hits, n = bucket_hits[bucket]
        if n >= 2:
            calibration.append({
                "predicted_p_up": bucket,
                "realized_hit_rate": round(hits / n, 3),
                "n": n,
            })

    # Compute self-learning weight multiplier per source (Bayesian shrinkage)
    src_summary = {}
    for src, (hits, n) in by_source.items():
        raw_hit = hits / n if n > 0 else 0.5
        raw_mult = max(0.0, 0.5 + (raw_hit - 0.5) * 2.0)    # 0..2
        # Shrink toward 1.0 (neutral) when small N
        mult = (n * raw_mult + _SHRINKAGE_K * 1.0) / (n + _SHRINKAGE_K)
        src_summary[src] = {
            "n": n, "hits": hits,
            "hit_rate": round(raw_hit, 3),
            "weight_mult": round(mult, 3),
        }

    return {
        "n_total":          len(preds),
        "n_graded":         n_graded,
        "overall_hit_rate": round(overall_hit_rate, 3),
        "calibration":      calibration,
        "by_source":        src_summary,
    }


# ── Persisted learned weights (consumed by edge.py) ─────────────────────────

def save_learned_weights(grade_result: dict) -> None:
    """Persist the per-source weight multipliers for edge.py to consume."""
    weights = {src: info["weight_mult"]
               for src, info in grade_result.get("by_source", {}).items()
               if info["n"] >= 3}    # need ≥3 samples to publish a weight
    payload = {
        "ts":      time.time(),
        "weights": weights,
        "n_total": grade_result.get("n_total", 0),
        "overall_hit_rate": grade_result.get("overall_hit_rate", 0.5),
    }
    _CALIBRATION_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def load_learned_weights() -> dict[str, float]:
    """Return per-source weight multipliers (or empty dict if not yet calibrated)."""
    if not _CALIBRATION_OUT.exists():
        return {}
    try:
        payload = json.loads(_CALIBRATION_OUT.read_text())
        return payload.get("weights", {})
    except Exception:
        return {}
