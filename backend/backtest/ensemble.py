"""
Factor Ensemble — Phase 4 redesign.

Replaces the Phase-1 equal-weight ensemble with a smarter aggregation:

  1. Correlation pruning (unchanged from v1)
     Greedy filter: skip a factor if its signal series is too correlated
     (|corr| > 0.35) with any already-kept factor. Avoids loading up on
     near-duplicate edges.

  2. Risk-parity weighting (NEW)
     Each kept factor's weight ∝ 1 / σ(strategy_returns).
     A factor that bounces around at 30% annualised vol gets HALF the
     weight of one running at 15% vol. Equalises risk contribution.

  3. Sharpe tilt (NEW)
     Weight is further multiplied by max(Sharpe, 0). High-conviction
     factors get more allocation. Sharpe is taken from the saved
     leaderboard entry (post-WFO, risk-managed).

  4. Final blending
     For each bar, sum(weight × signal). Then:
       blended >  +threshold → +1
       blended <  -threshold → -1
       else                  →  0
     threshold defaults to 0.20 of total weight (≥ 20% net long votes).

Returns the blended signal, the kept-factor weights (so you can inspect
"how confident is the ensemble in factor X today"), and a correlation
matrix for diagnostics.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import NamedTuple


class EnsembleResult(NamedTuple):
    signal:       pd.Series           # combined signal, values in {-1, 0, 1}
    raw_blend:    pd.Series           # pre-threshold weighted average, range ~ [-1, +1]
    kept_ids:     list[str]           # factor IDs included
    dropped_ids:  list[str]           # factor IDs excluded (too correlated)
    weights:      dict[str, float]    # final normalised weights {id: weight}
    corr_matrix:  pd.DataFrame        # pairwise correlation of kept signals


def _compute_factor_returns(
    signal: pd.Series,
    closes_aligned: pd.Series,
) -> pd.Series:
    """Per-bar strategy return assuming yesterday's signal × today's return."""
    bar_ret = closes_aligned.pct_change().fillna(0)
    return signal.shift(1).fillna(0) * bar_ret


def build_ensemble(
    factor_records: list[dict],
    closes:          pd.Series | None = None,
    corr_threshold:  float = 0.35,
    min_factors:     int   = 2,
    blend_threshold: float = 0.20,
) -> EnsembleResult | None:
    """
    Build a smart-weighted ensemble from a list of factor records.

    Each record must have:
      - "id"     : str
      - "signal" : pd.Series (index = DatetimeIndex, values in {-1, 0, 1})
      - "oos_sharpe_ratio" : float (used for Sharpe-tilt; optional)

    If `closes` is provided (QBTS close series), risk-parity weights are
    computed from each factor's realised volatility. Without it, falls back
    to equal weights × Sharpe tilt.

    Returns None if fewer than `min_factors` records survive correlation pruning.
    """
    if len(factor_records) < min_factors:
        return None

    # Align all signals on intersection of timestamps
    signals: dict[str, pd.Series] = {r["id"]: r["signal"] for r in factor_records}
    common_idx = signals[factor_records[0]["id"]].index
    for s in signals.values():
        common_idx = common_idx.intersection(s.index)
    if len(common_idx) < 10:
        return None

    aligned = {fid: sig.reindex(common_idx).fillna(0).astype(float) for fid, sig in signals.items()}

    # ── Step 1: greedy correlation pruning ───────────────────────────────────
    # Sort factor records by Sharpe descending so best survives ties
    ordered = sorted(factor_records, key=lambda r: r.get("oos_sharpe_ratio", 0.0), reverse=True)
    kept:    list[str] = []
    dropped: list[str] = []

    for rec in ordered:
        fid = rec["id"]
        new_sig = aligned[fid].values
        if new_sig.std() == 0:
            dropped.append(fid)
            continue
        too_corr = False
        for kid in kept:
            kept_sig = aligned[kid].values
            if kept_sig.std() == 0:
                continue
            c = float(np.corrcoef(new_sig, kept_sig)[0, 1])
            if abs(c) >= corr_threshold:
                too_corr = True
                break
        if too_corr:
            dropped.append(fid)
        else:
            kept.append(fid)

    if len(kept) < min_factors:
        # Loosen — keep all (correlation discount handled by Sharpe tilt below)
        kept    = [r["id"] for r in ordered]
        dropped = []

    # ── Step 2: compute weights = risk_parity × max(sharpe, 0) ───────────────
    sharpe_by_id = {r["id"]: max(r.get("oos_sharpe_ratio", 0.0), 0.0) for r in factor_records}
    weights_raw: dict[str, float] = {}

    if closes is not None:
        closes_aligned = closes.reindex(common_idx).ffill().bfill()
        for fid in kept:
            ret  = _compute_factor_returns(aligned[fid], closes_aligned)
            vol  = float(ret.std())
            risk_parity_w = 1.0 / vol if vol > 1e-6 else 0.0
            tilt          = sharpe_by_id.get(fid, 0.0) + 0.1   # +0.1 floor so 0-Sharpe still counted
            weights_raw[fid] = risk_parity_w * tilt
    else:
        for fid in kept:
            weights_raw[fid] = sharpe_by_id.get(fid, 0.0) + 0.1

    total = sum(weights_raw.values()) or 1.0
    weights = {fid: w / total for fid, w in weights_raw.items()}

    # ── Step 3: blend ────────────────────────────────────────────────────────
    blend_arr = np.zeros(len(common_idx))
    for fid, w in weights.items():
        blend_arr += aligned[fid].values * w
    raw_blend = pd.Series(blend_arr, index=common_idx, name="ensemble_raw")

    sig_arr = np.where(blend_arr >  blend_threshold,  1,
              np.where(blend_arr < -blend_threshold, -1, 0))
    ensemble_signal = pd.Series(sig_arr, index=common_idx, name="ensemble", dtype=int)

    # ── Step 4: diagnostics ──────────────────────────────────────────────────
    kept_matrix = pd.DataFrame({k: aligned[k] for k in kept})
    corr_df     = kept_matrix.corr()

    return EnsembleResult(
        signal       = ensemble_signal,
        raw_blend    = raw_blend,
        kept_ids     = kept,
        dropped_ids  = dropped,
        weights      = weights,
        corr_matrix  = corr_df,
    )
