"""
Vectorized Backtest Engine — Phase 1 redesign
=============================================
Evaluates factor signals on QBTS OHLCV data with proper risk management.

Walk-Forward Optimization (WFO):
  - Window sizes in TRADING BARS (not calendar days) — fixes prior off-by-30%
    bug where '6 months' = 180 calendar days only contained ~120 trading bars.
  - Factor code is applied to the full df once (valid because factor code only
    uses past data via shift()), then sliced per OOS window.
  - All OOS windows are stitched together for final metrics.

Risk Management (applied per OOS window before computing PnL):
  - Vol-target sizing scales exposure inversely with realised ATR.
  - Per-trade hard stop-loss zeroes positions after intra-trade loss > 5%.
  Both controls cap catastrophic factor failures (the -90% OOS factors that
  shorted into the 2024-2025 bull run).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field

from backtest.risk import apply_risk_management, worst_single_period_loss


# ─── Bar-count defaults (≈ trading bars per period) ──────────────────────────
BARS_PER_MONTH_DAILY  = 21        # ~21 trading days / month
BARS_PER_MONTH_HOURLY = 21 * 7    # ~7 trading hours/day × 21 days
PERIODS_PER_YEAR      = {"1d": 252, "1h": 252 * 7}


def bars_per_month(freq: str) -> int:
    return BARS_PER_MONTH_HOURLY if freq == "1h" else BARS_PER_MONTH_DAILY


# ─── Core data classes ───────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    win_rate:        float           # fraction of profitable trades
    max_drawdown:    float           # peak-to-trough as a negative fraction
    risk_reward:     float           # avg win / avg loss (absolute)
    sharpe_ratio:    float           # annualised Sharpe (risk-free = 0)
    total_return:    float           # cumulative return fraction
    n_trades:        int             # number of round-trip trades
    equity_curve:    pd.Series       # indexed by datetime
    # Phase-1 risk-managed additions ----------------------------------------
    n_stops:         int   = 0       # how many times the stop-loss fired
    worst_bar_loss:  float = 0.0     # worst single-bar loss after risk mgmt
    # Phase-4 trust signals -------------------------------------------------
    sharpe_ci_low:   float = 0.0     # 5th-percentile bootstrap Sharpe
    sharpe_ci_high:  float = 0.0     # 95th-percentile bootstrap Sharpe

    def to_dict(self) -> dict:
        return {
            "win_rate":        round(self.win_rate, 4),
            "max_drawdown":    round(self.max_drawdown, 4),
            "risk_reward":     round(self.risk_reward, 4),
            "sharpe_ratio":    round(self.sharpe_ratio, 4),
            "total_return":    round(self.total_return, 4),
            "n_trades":        self.n_trades,
            "n_stops":         self.n_stops,
            "worst_bar_loss":  round(self.worst_bar_loss, 4),
            "sharpe_ci_low":   round(self.sharpe_ci_low,  4),
            "sharpe_ci_high":  round(self.sharpe_ci_high, 4),
        }


# ─── Metric helpers ──────────────────────────────────────────────────────────

def _compute_drawdown(equity: pd.Series) -> float:
    rolling_max = equity.cummax()
    return float(((equity - rolling_max) / rolling_max).min())


def _annualised_sharpe(returns: pd.Series, periods_per_year: int) -> float:
    if returns.std() == 0 or len(returns) < 2:
        return 0.0
    return float((returns.mean() / returns.std()) * np.sqrt(periods_per_year))


def _bootstrap_sharpe_ci(
    returns: pd.Series,
    periods_per_year: int,
    n_bootstrap: int = 500,
    block_size: int = 5,
    confidence: float = 0.90,
    seed: int = 42,
) -> tuple[float, float]:
    """
    Block-bootstrap a 90% confidence interval on the annualised Sharpe.
    Returns (lower_5pct, upper_95pct). Tighter band = more trustworthy edge.
    """
    arr = returns.values
    n   = len(arr)
    if n < 20:
        return (0.0, 0.0)

    rng = np.random.default_rng(seed)
    sharpes = []
    n_blocks = max(1, n // block_size)
    for _ in range(n_bootstrap):
        starts = rng.integers(0, max(1, n - block_size + 1), n_blocks)
        sample = np.concatenate([arr[s:s + block_size] for s in starts])[:n]
        if sample.std() > 1e-12:
            sharpes.append((sample.mean() / sample.std()) * np.sqrt(periods_per_year))

    if len(sharpes) < 10:
        return (0.0, 0.0)
    sharpes = np.array(sharpes)
    alpha   = (1 - confidence) / 2
    return (float(np.quantile(sharpes, alpha)), float(np.quantile(sharpes, 1 - alpha)))


def _trade_level_stats(
    positions: np.ndarray,        # effective (risk-managed) position per bar
    closes:    np.ndarray,        # close prices
    cost_per_side: float,
) -> tuple[int, float, float, float]:
    """
    Walk the effective position series and extract round-trip trades.
    A 'trade' begins when position changes from 0 / opposite to a new side,
    and ends when it returns to 0 or flips. Stop-losses appear naturally as
    sudden transitions to 0 (locked-out flat).

    Returns (n_trades, win_rate, risk_reward, avg_pnl).
    """
    trade_returns: list[float] = []
    in_trade   = False
    entry_px   = 0.0
    entry_side = 0   # +1 / -1 — sign of position when trade opened

    for i in range(1, len(positions)):
        sign_i = 1 if positions[i] > 0 else (-1 if positions[i] < 0 else 0)

        if not in_trade and sign_i != 0:
            in_trade   = True
            entry_px   = float(closes[i])
            entry_side = sign_i
        elif in_trade and sign_i != entry_side:
            pnl = entry_side * (float(closes[i]) - entry_px) / entry_px - 2 * cost_per_side
            trade_returns.append(pnl)
            if sign_i != 0:
                entry_px   = float(closes[i])
                entry_side = sign_i
            else:
                in_trade   = False
                entry_side = 0

    n_trades = len(trade_returns)
    if n_trades == 0:
        return 0, 0.0, 0.0, 0.0

    arr      = np.array(trade_returns)
    wins     = arr[arr > 0]
    losses   = arr[arr <= 0]
    win_rate = len(wins) / n_trades
    avg_win  = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(abs(losses.mean())) if len(losses) > 0 else 1e-9
    rr       = avg_win / avg_loss
    return n_trades, win_rate, rr, float(arr.mean())


def _build_result(
    eff_positions:   pd.Series,   # risk-managed positions (continuous in [-1, 1])
    strat_returns:   pd.Series,   # per-bar strategy returns after costs + risk
    closes:          np.ndarray,
    cost_per_side:   float,
    n_stops:         int,
    periods_per_year: int,
    initial_capital: float = 10_000.0,
) -> BacktestResult:
    equity = initial_capital * (1 + strat_returns).cumprod()
    n_trades, win_rate, rr, _ = _trade_level_stats(eff_positions.values, closes, cost_per_side)
    ci_low, ci_high = _bootstrap_sharpe_ci(strat_returns, periods_per_year)
    return BacktestResult(
        win_rate       = round(win_rate, 4),
        max_drawdown   = round(_compute_drawdown(equity), 4),
        risk_reward    = round(rr, 4),
        sharpe_ratio   = round(_annualised_sharpe(strat_returns, periods_per_year), 4),
        total_return   = round(float(equity.iloc[-1] / initial_capital - 1), 4),
        n_trades       = n_trades,
        equity_curve   = equity,
        n_stops        = n_stops,
        worst_bar_loss = round(worst_single_period_loss(strat_returns), 4),
        sharpe_ci_low  = round(ci_low,  4),
        sharpe_ci_high = round(ci_high, 4),
    )


def _strategy_returns(
    eff_positions: pd.Series,    # already vol-sized + stop-managed
    bar_returns:   pd.Series,
    cost_per_side: float,
) -> pd.Series:
    """
    Strategy return = previous-bar position × this-bar's underlying return
                      − transaction cost on position change.
    """
    strat = eff_positions.shift(1).fillna(0) * bar_returns
    strat -= eff_positions.diff().abs().fillna(0) * cost_per_side
    return strat


# ─── Splits (BAR-COUNT — fixes calendar-day bug) ─────────────────────────────

def walk_forward_splits(
    df: pd.DataFrame,
    is_bars:    int,
    oos_bars:   int,
    step_bars:  int,
) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """
    Generate (df_is, df_oos) pairs by sliding a window over the bar index.
    Window sizes are in TRADING BARS, not calendar days — this avoids the
    previous bug where '6 months × 30 days' captured only ~120 trading bars.
    """
    n = len(df)
    splits: list[tuple[pd.DataFrame, pd.DataFrame]] = []
    oos_start = is_bars
    while oos_start + oos_bars <= n:
        is_start = max(0, oos_start - is_bars)
        df_is   = df.iloc[is_start:oos_start].copy()
        df_oos  = df.iloc[oos_start:oos_start + oos_bars].copy()
        if len(df_is) >= 10 and len(df_oos) >= 3:
            splits.append((df_is, df_oos))
        oos_start += step_bars
    return splits


def split_data(
    df: pd.DataFrame,
    is_bars:  int,
    oos_bars: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Final IS/OOS slice for ad-hoc reporting (most recent OOS at end).
    Falls back to 70/30 if df is too short.
    """
    if len(df) < is_bars + oos_bars:
        cutoff = int(len(df) * 0.70)
        return df.iloc[:cutoff].copy(), df.iloc[cutoff:].copy()
    return (
        df.iloc[-(is_bars + oos_bars):-oos_bars].copy(),
        df.iloc[-oos_bars:].copy(),
    )


# ─── Walk-forward backtest with risk management ──────────────────────────────

def run_walk_forward(
    df: pd.DataFrame,
    factor_code: str,
    freq: str = "1d",
    is_bars:   int | None = None,
    oos_bars:  int | None = None,
    step_bars: int | None = None,
    initial_capital: float = 10_000.0,
    commission: float = 0.001,
    slippage:   float = 0.001,
    stop_pct:   float = 0.05,
    target_vol: float = 0.02,
) -> tuple[BacktestResult, pd.Series]:
    """
    Walk-forward backtest with risk management.

    Default windows (per freq):
      1d : IS=126 bars (~6m)   OOS=21 bars (~1m)   step=21 bars (~1m, no overlap on OOS)
      1h : IS=882 bars (~6m)   OOS=147 bars (~1m)  step=147 bars

    Per OOS window:
      1. Slice the pre-computed factor signal.
      2. Apply vol-target sizing + per-trade stop-loss.
      3. Compute strategy returns including costs.
      4. Accumulate.

    Returns (stitched-OOS BacktestResult, stitched RAW signal series).
    The raw signal is returned (not risk-managed) so IC remains a clean measure
    of factor quality independent of execution.
    """
    bpm = bars_per_month(freq)
    if is_bars   is None: is_bars   = 6 * bpm
    if oos_bars  is None: oos_bars  = 1 * bpm
    if step_bars is None: step_bars = 1 * bpm

    # Step 1 — full-df signal (no look-ahead)
    ns: dict = {"pd": pd, "np": np}
    exec(compile(factor_code, "<factor>", "exec"), ns)
    full_signal: pd.Series = ns["compute_factor"](df.copy())

    splits = walk_forward_splits(df, is_bars=is_bars, oos_bars=oos_bars, step_bars=step_bars)
    if not splits:
        raise ValueError(
            f"Not enough data for WFO (need ≥ {is_bars + oos_bars} bars, "
            f"got {len(df)} bars at freq={freq})"
        )

    periods_per_year = PERIODS_PER_YEAR.get(freq, 252)
    cost_per_side    = commission + slippage

    raw_signal_parts: list[pd.Series] = []
    eff_pos_parts:    list[pd.Series] = []
    strat_ret_parts:  list[pd.Series] = []
    total_stops = 0

    for _, df_oos in splits:
        raw_sig = full_signal.reindex(df_oos.index).fillna(0).astype(int)
        atr     = df_oos.get("atr_14", pd.Series(0.03, index=df_oos.index))
        eff_pos, n_stops = apply_risk_management(
            raw_positions = raw_sig,
            closes        = df_oos["close"],
            atr_norm      = atr,
            stop_pct      = stop_pct,
            target_vol    = target_vol,
        )
        bar_ret   = df_oos["close"].pct_change().fillna(0)
        strat_ret = _strategy_returns(eff_pos, bar_ret, cost_per_side)

        raw_signal_parts.append(raw_sig)
        eff_pos_parts.append(eff_pos)
        strat_ret_parts.append(strat_ret)
        total_stops += n_stops

    combined_raw_sig = pd.concat(raw_signal_parts).sort_index()
    combined_eff_pos = pd.concat(eff_pos_parts).sort_index()
    combined_returns = pd.concat(strat_ret_parts).sort_index()
    # Deduplicate (defensive — shouldn't happen with step_bars >= oos_bars)
    combined_raw_sig = combined_raw_sig[~combined_raw_sig.index.duplicated(keep="last")]
    combined_eff_pos = combined_eff_pos[~combined_eff_pos.index.duplicated(keep="last")]
    combined_returns = combined_returns[~combined_returns.index.duplicated(keep="last")]

    closes_arr = df.reindex(combined_eff_pos.index)["close"].values
    result = _build_result(
        eff_positions    = combined_eff_pos,
        strat_returns    = combined_returns,
        closes           = closes_arr,
        cost_per_side    = cost_per_side,
        n_stops          = total_stops,
        periods_per_year = periods_per_year,
        initial_capital  = initial_capital,
    )
    return result, combined_raw_sig


def is_overfit(is_result: BacktestResult, oos_result: BacktestResult) -> bool:
    """
    True only if there is strong evidence of overfitting.

    A factor is *overfit* if it was great on IS but failed on OOS — the
    classic pattern-matched-noise signature. We do NOT call it overfit just
    because OOS Sharpe < IS Sharpe; that's natural since IS = last 12 months
    (single regime) while WFO OOS spans the full 2-year history (multi-regime).

    Definition:
      Overfit = (IS Sharpe ≥ 1.5  AND  OOS Sharpe < 0.3)
                OR (IS Sharpe > 0  AND  OOS Sharpe < -0.5)
    Anything else (OOS positive, or both mediocre) is NOT overfit — it's
    either genuinely good or genuinely bad, but the IS→OOS gap isn't the tell.
    """
    is_s  = is_result.sharpe_ratio
    oos_s = oos_result.sharpe_ratio
    if oos_s >= 0.3:
        return False
    if is_s >= 1.5 and oos_s < 0.3:
        return True
    if is_s > 0   and oos_s < -0.5:
        return True
    return False


def run_backtest(
    df: pd.DataFrame,
    signal: pd.Series,
    freq: str = "1d",
    initial_capital: float = 10_000.0,
    commission: float = 0.001,
    slippage:   float = 0.001,
    stop_pct:   float = 0.05,
    target_vol: float = 0.02,
) -> BacktestResult:
    """
    Single-shot backtest of a signal (no walk-forward), with the same risk
    management pipeline. Used mainly for IS reporting and ensemble evaluation.
    """
    periods_per_year = PERIODS_PER_YEAR.get(freq, 252)
    cost_per_side    = commission + slippage

    sig = signal.reindex(df.index).fillna(0).astype(int)
    atr = df.get("atr_14", pd.Series(0.03, index=df.index))
    eff_pos, n_stops = apply_risk_management(
        raw_positions = sig,
        closes        = df["close"],
        atr_norm      = atr,
        stop_pct      = stop_pct,
        target_vol    = target_vol,
    )
    bar_ret   = df["close"].pct_change().fillna(0)
    strat_ret = _strategy_returns(eff_pos, bar_ret, cost_per_side)

    return _build_result(
        eff_positions    = eff_pos,
        strat_returns    = strat_ret,
        closes           = df["close"].values,
        cost_per_side    = cost_per_side,
        n_stops          = n_stops,
        periods_per_year = periods_per_year,
        initial_capital  = initial_capital,
    )


def score_factor(result: BacktestResult, quality: dict | None = None) -> float:
    """
    Composite score for leaderboard ranking, post risk-management.

    Weights:
      40% — risk-adjusted Sharpe (the only number that pays the bills)
      30% — directional accuracy (hit_rate from quality dict, if available)
      15% — drawdown protection (less DD = better risk)
      10% — IC magnitude (rewards persistent edge)
       5% — risk/reward profile

    Penalties:
      - negative OOS return : −0.5 × loss
      - whipsaw (stops > 25% of trades) : up to −0.3
    """
    if result.n_trades == 0:
        return 0.0

    # Use the LOWER 5% CI of bootstrap Sharpe — punishes high-variance results.
    # A factor with point-Sharpe 1.5 but CI=[-0.5, 3.5] should not score above
    # one with point-Sharpe 1.0 and CI=[0.5, 1.5].
    sharpe_for_score = result.sharpe_ci_low if result.sharpe_ci_low != 0.0 else result.sharpe_ratio
    sharpe_norm      = max(sharpe_for_score, 0) / 2.0           # 2.0 Sharpe → full marks
    hit_excess   = 0.0
    ic_norm      = 0.0
    if quality:
        # Hit rate over the 0.50 random baseline, normalised by realistic 0.60 ceiling
        hit_excess = max(0.0, (quality.get("hit_rate", 0.5) - 0.50)) / 0.10
        # IC normalised to 0.10 = full marks
        ic_norm    = max(0.0, quality.get("ic_mean", 0.0)) / 0.10

    base = (
        0.40 * min(sharpe_norm, 1.0)
        + 0.30 * min(hit_excess, 1.0)
        + 0.15 * max(0, 1 + result.max_drawdown)
        + 0.10 * min(ic_norm, 1.0)
        + 0.05 * min(result.risk_reward, 3) / 3
    )

    return_penalty  = min(result.total_return, 0) * 0.5
    stop_ratio      = result.n_stops / max(result.n_trades, 1)
    whipsaw_penalty = min(max(0.0, stop_ratio - 0.25) * 1.5, 0.30)

    return round(max(base + return_penalty - whipsaw_penalty, 0.0), 4)


if __name__ == "__main__":
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from data.fetcher  import load_or_fetch
    from data.enricher import enrich

    _, df_daily = load_or_fetch()
    df_daily = enrich(df_daily, freq="1d")

    sma    = df_daily["close"].rolling(20).mean()
    signal = pd.Series(np.where(df_daily["close"] > sma, 1, -1), index=df_daily.index).fillna(0).astype(int)

    result = run_backtest(df_daily, signal)
    print("\n--- Risk-managed Backtest (SMA20) ---")
    for k, v in result.to_dict().items():
        print(f"  {k:18s}: {v}")
    print(f"  {'score':18s}: {score_factor(result)}")
