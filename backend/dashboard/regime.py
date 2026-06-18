"""
Volatility regime — the context QBTS lives and dies by.

QBTS is a high-beta name whose single-day ±15% moves are common. The same
ATR means very different things depending on where current volatility sits in
its own distribution, so we hand the decision engine the *context*, not a raw
number:

  atr_pct            ATR(14) as a fraction of price
  atr_pct_percentile where that sits vs the trailing year (0..100)
  realized_vol_20d   20-day annualised realised volatility
  gap stats          overnight gap behaviour (mean |gap|, % of days |gap|>5%)
  regime             expansion | contraction | normal
  stop_hint          plain-language guidance on how wide stops must be

Self-contained: computes ATR/returns from raw daily OHLC, no enrich dependency.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_ATR_N      = 14
_PCTL_WIN   = 252    # trailing window for the ATR% percentile
_GAP_WIN    = 60     # overnight-gap statistics window


def _atr_pct_series(df: pd.DataFrame, n: int = _ATR_N) -> pd.Series:
    """ATR(n) / close, as a fraction, per bar."""
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.rolling(n, min_periods=max(2, n // 2)).mean()
    return (atr / c).dropna()


def analyze_regime(df_d: pd.DataFrame) -> dict:
    if df_d is None or len(df_d) < 30:
        return {"regime": "normal", "rationale": "日线数据不足，无法判定波动率 regime"}

    atr_pct_s = _atr_pct_series(df_d)
    atr_pct = float(atr_pct_s.iloc[-1])
    win = atr_pct_s.tail(_PCTL_WIN)
    pctl = float((win <= atr_pct).mean() * 100)

    rets = np.log(df_d["close"] / df_d["close"].shift(1)).dropna()
    realized_vol_20d = float(rets.tail(20).std() * np.sqrt(252))

    # overnight gaps: today's open vs yesterday's close
    gaps = (df_d["open"] / df_d["close"].shift(1) - 1).dropna().tail(_GAP_WIN)
    gap_mean = float(gaps.abs().mean())
    gap_gt5_pct = float((gaps.abs() > 0.05).mean())

    if pctl >= 70:
        regime = "expansion"
        stop_hint = "波动扩张期：止损需放宽（≥1.5×ATR），仓位降一档，避免被正常波动扫损"
    elif pctl <= 30:
        regime = "contraction"
        stop_hint = "波动收缩期：可适度收紧止损，但提防低波后的假突破/突然扩张"
    else:
        regime = "normal"
        stop_hint = "波动正常：常规 1×ATR 上下的止损即可"

    label_cn = {"expansion": "扩张", "contraction": "收缩", "normal": "正常"}[regime]
    rationale = (
        f"波动率{label_cn}（ATR%={atr_pct*100:.1f}%，处于过去一年第 {pctl:.0f} 百分位）；"
        f"20日年化波动 {realized_vol_20d*100:.0f}%；"
        f"近{_GAP_WIN}日平均隔夜跳空 {gap_mean*100:.1f}%，|跳空|>5% 占 {gap_gt5_pct*100:.0f}%。{stop_hint}"
    )

    return {
        "regime":             regime,
        "atr_pct":            round(atr_pct, 4),
        "atr_pct_percentile": round(pctl, 1),
        "realized_vol_20d":   round(realized_vol_20d, 3),
        "gap_mean_60d":       round(gap_mean, 4),
        "gap_gt5_pct":        round(gap_gt5_pct, 3),
        "stop_hint":          stop_hint,
        "rationale":          rationale,
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from data.fetcher import load_or_fetch
    import json
    _, df_d = load_or_fetch()
    print(json.dumps(analyze_regime(df_d), ensure_ascii=False, indent=2))
