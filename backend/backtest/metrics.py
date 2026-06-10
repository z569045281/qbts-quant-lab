"""
Factor Quality Metrics — Phase 2 redesign.

PROBLEM WITH PRIOR APPROACH:
  The previous compute_ic_series used a 20-bar rolling window and converted
  NaN correlations to 0. For sparse signals (factor fires <10% of bars),
  most 20-bar windows contained only a single non-zero signal → spearmanr
  returned NaN → padded with 0 → mean IC pulled to 0 regardless of true alpha.
  Phase-1 regime guards made signals even sparser, exposing this bug.

NEW APPROACH:
  Compute IC on ACTIVE BARS ONLY (signal != 0). This is what we actually
  care about: "when the factor says +1, does the stock go up?" rather than
  "correlation across all bars including the irrelevant zeros."

NEW PRIMARY METRIC: hit_rate
  Of the bars where signal != 0, what fraction had a forward return in
  the predicted direction? Random = 0.50; meaningful alpha starts at 0.52
  with statistical significance from 30+ signals.

ICIR via BLOCK BOOTSTRAP:
  Instead of a fragile rolling-window mean/std, resample blocks of (signal,
  return) pairs and compute the IC distribution. ICIR = mean / std of
  bootstrap IC distribution. Robust to sparsity AND autocorrelation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def compute_ic_decay(
    signal: pd.Series,
    df: pd.DataFrame,
    max_periods: int = 10,
) -> dict[int, float]:
    """
    IC at forward periods 1..max_periods, computed on ACTIVE bars only.
    Fast alpha decays quickly; stable alpha stays elevated.
    """
    closes = df["close"].values
    s = signal.values.astype(float)
    decay: dict[int, float] = {}

    for lag in range(1, max_periods + 1):
        fwd_ret = np.full(len(closes), np.nan)
        fwd_ret[:-lag] = (closes[lag:] - closes[:-lag]) / closes[:-lag]
        mask = (~np.isnan(fwd_ret)) & (s != 0)
        if mask.sum() < 5:
            decay[lag] = 0.0
            continue
        rho, _ = stats.spearmanr(s[mask], fwd_ret[mask])
        decay[lag] = round(float(rho) if not np.isnan(rho) else 0.0, 4)
    return decay


def factor_quality_summary(
    signal: pd.Series,
    df: pd.DataFrame,
    forward_period: int = 1,
    n_bootstrap: int = 200,
    seed: int = 42,
) -> dict:
    """
    Sparse-signal-aware factor quality report.

    Returns:
        ic_mean         : Spearman corr on active bars (signal != 0)
        ic_pvalue       : two-sided p-value for the IC
        icir            : bootstrap IC / std (robust stability measure)
        hit_rate        : fraction of active bars where sign(signal) == sign(forward return)
        n_signals       : count of active bars
        long_avg_return : average forward return when signal > 0
        short_edge      : average forward return when signal < 0, sign-flipped (positive = good short)
        ic_decay        : dict {lag: IC} at forward periods 1..N
    """
    fwd_ret = df["close"].pct_change(forward_period).shift(-forward_period)

    valid = ~fwd_ret.isna()
    s_all = signal[valid].astype(float).values
    r_all = fwd_ret[valid].values

    active = s_all != 0
    n_signals = int(active.sum())

    # Default empty report
    empty = {
        "ic_mean":         0.0,
        "ic_pvalue":       1.0,
        "icir":            0.0,
        "hit_rate":        0.0,
        "n_signals":       n_signals,
        "long_avg_return": 0.0,
        "short_edge":      0.0,
        "ic_decay":        {},
    }
    if n_signals < 5:
        return empty

    s = s_all[active]
    r = r_all[active]

    # ── Full-period IC on active bars ──────────────────────────────────────
    rho, p_val = stats.spearmanr(s, r)
    ic_mean = 0.0 if np.isnan(rho) else float(rho)
    ic_pval = 1.0 if np.isnan(p_val) else float(p_val)

    # ── Hit rate (directional accuracy) ────────────────────────────────────
    hits = (np.sign(s) == np.sign(r))
    hit_rate = float(hits.mean())

    # ── Per-side average forward returns ───────────────────────────────────
    long_mask  = s > 0
    short_mask = s < 0
    long_avg   = float(r[long_mask].mean())  if long_mask.sum()  > 0 else 0.0
    short_edge = float(-r[short_mask].mean()) if short_mask.sum() > 0 else 0.0  # positive = good short

    # ── ICIR via block bootstrap (handles autocorrelation) ─────────────────
    rng        = np.random.default_rng(seed)
    block_size = max(3, n_signals // 20)
    n_blocks   = max(1, n_signals // block_size)
    boot_ics   = []
    for _ in range(n_bootstrap):
        starts = rng.integers(0, max(1, n_signals - block_size + 1), n_blocks)
        idx = np.concatenate([np.arange(st, min(st + block_size, n_signals)) for st in starts])[:n_signals]
        b_rho, _ = stats.spearmanr(s[idx], r[idx])
        if not np.isnan(b_rho):
            boot_ics.append(b_rho)

    if len(boot_ics) > 1:
        arr  = np.array(boot_ics)
        std  = float(arr.std())
        icir = float(arr.mean() / std) if std > 1e-9 else 0.0
    else:
        icir = 0.0

    return {
        "ic_mean":         round(ic_mean, 4),
        "ic_pvalue":       round(ic_pval, 4),
        "icir":            round(icir, 4),
        "hit_rate":        round(hit_rate, 4),
        "n_signals":       n_signals,
        "long_avg_return": round(long_avg, 4),
        "short_edge":      round(short_edge, 4),
        "ic_decay":        compute_ic_decay(signal, df, max_periods=min(10, len(df) // 20)),
    }
