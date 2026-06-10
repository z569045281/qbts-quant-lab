"""
Risk Management Layer — Phase 1 of system redesign.

Two orthogonal controls applied to every backtest:

  1. Volatility-targeted position sizing
     scale_factor = clip(target_vol / atr_normalized, 0.10, 1.00)
     A high-vol bar reduces position; a low-vol bar uses full size.
     Purpose: target ~constant daily-vol exposure across regimes.

  2. Per-trade hard stop-loss
     If unrealized loss within a trade exceeds stop_pct, force position to 0.
     Remain flat until the signal goes to 0 or flips to the opposite side.
     Purpose: cap single-trade catastrophic losses (the -90% OOS factors).

The two pass through cleanly: vol-target first (continuous sizing),
then stop-loss on the sign of the sized positions.

Returns a sized position series in [-1.0, +1.0] suitable for direct
multiplication with bar returns in the existing backtest math.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# Sensible defaults — calibrated for QBTS daily volatility (~5% typical ATR/close)
DEFAULT_TARGET_VOL = 0.02     # 2% target daily portfolio vol
DEFAULT_STOP_PCT   = 0.05     # 5% per-trade hard stop
DEFAULT_MAX_LEVERAGE = 1.0    # cap nominal exposure at 100% (no leverage)
DEFAULT_MIN_SIZE     = 0.10   # never go below 10% size (avoids whipsaw exit)
DEFAULT_ATR_FLOOR    = 0.005  # treat ATR < 0.5% as 0.5% to avoid div-by-zero


def vol_target_size(
    positions: pd.Series,
    atr_norm:  pd.Series,
    target_vol:   float = DEFAULT_TARGET_VOL,
    max_leverage: float = DEFAULT_MAX_LEVERAGE,
    min_size:     float = DEFAULT_MIN_SIZE,
    atr_floor:    float = DEFAULT_ATR_FLOOR,
) -> pd.Series:
    """
    Vol-target position sizing.
    atr_norm is the pre-computed atr_14 / close column.
    """
    safe_atr   = atr_norm.clip(lower=atr_floor)
    multiplier = (target_vol / safe_atr).clip(min_size, max_leverage)
    return (positions.astype(float) * multiplier).round(4)


def apply_stop_loss(
    positions: pd.Series,
    closes:    pd.Series,
    stop_pct:  float = DEFAULT_STOP_PCT,
) -> tuple[pd.Series, int]:
    """
    Walk through trades; force positions to 0 once intra-trade loss
    exceeds stop_pct. Re-entry is allowed when the signal goes flat
    or flips to the opposite side.

    Returns:
        (effective_positions, n_stops_hit)
    """
    pos = positions.values.astype(float).copy()
    c   = closes.values.astype(float)
    new_pos = pos.copy()

    in_stop      = False   # currently locked-out after a stop hit
    entry_price  = 0.0
    entry_sign   = 0       # +1 / -1 / 0 — direction of active (or just-stopped) trade
    n_stops      = 0

    for i in range(len(pos)):
        sign_i = 1 if pos[i] > 0 else (-1 if pos[i] < 0 else 0)

        if in_stop:
            if sign_i == 0:
                # Signal cleared → release the lockout, stay flat
                in_stop    = False
                entry_sign = 0
                new_pos[i] = 0.0
            elif sign_i != entry_sign:
                # Signal flipped to opposite side → release, take new trade
                in_stop     = False
                entry_price = c[i]
                entry_sign  = sign_i
                new_pos[i]  = pos[i]
            else:
                # Same direction still signalled → remain flat
                new_pos[i] = 0.0
            continue

        if sign_i == 0:
            entry_sign = 0
            continue

        if entry_sign == 0 or sign_i != entry_sign:
            # New entry or side flip — start fresh trade
            entry_price = c[i]
            entry_sign  = sign_i
            continue

        # Continuing existing trade → check stop
        unrealized = entry_sign * (c[i] - entry_price) / entry_price
        if unrealized < -stop_pct:
            new_pos[i] = 0.0
            in_stop    = True
            n_stops   += 1

    return pd.Series(new_pos, index=positions.index, dtype=float), n_stops


def apply_risk_management(
    raw_positions: pd.Series,
    closes:        pd.Series,
    atr_norm:      pd.Series,
    stop_pct:      float = DEFAULT_STOP_PCT,
    target_vol:    float = DEFAULT_TARGET_VOL,
) -> tuple[pd.Series, int]:
    """
    Full pipeline: vol-target sizing → stop-loss.
    Returns (sized_and_stopped_positions, n_stops_hit).
    """
    sized = vol_target_size(raw_positions, atr_norm, target_vol=target_vol)
    final, n_stops = apply_stop_loss(sized, closes, stop_pct=stop_pct)
    return final, n_stops


def worst_single_period_loss(strategy_returns: pd.Series) -> float:
    """
    Largest single-period loss as a negative fraction (e.g. -0.043 = -4.3% bar).
    Used as a sanity gate — vol-targeting + stops should keep this bounded.
    """
    if len(strategy_returns) == 0:
        return 0.0
    return float(strategy_returns.min())
