"""
WaveTrend oscillator — the engine behind VuManChu Cipher B's buy/sell circles.

VMC ("VuManChu Cipher") is a proprietary TradingView script, but its "green dot"
(buy circle) is just LazyBear's WaveTrend crossing up out of oversold, confirmed
on bar close. We replicate that here so the 15m SMC trigger ("VMC 收盘绿点") is a
real, reproducible signal rather than a black box.

LazyBear WaveTrend (default params):
    ap   = hlc3
    esa  = ema(ap, n1)                 # n1 = channel length (10)
    d    = ema(|ap - esa|, n1)
    ci   = (ap - esa) / (0.015 * d)
    tci  = ema(ci, n2)                 # n2 = average length (21)
    wt1  = tci
    wt2  = sma(wt1, 4)

Green dot  = wt1 crosses ABOVE wt2 while oversold (wt2 <= os level)  → close-confirmed buy
Red dot    = wt1 crosses BELOW wt2 while overbought (wt2 >= ob level) → close-confirmed sell

All causal: the dot is read off the LAST COMPLETED bar only (no repaint).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def wavetrend(df: pd.DataFrame, n1: int = 10, n2: int = 21,
              ob: float = 53.0, os: float = -53.0) -> pd.DataFrame:
    """Return df with wt1, wt2 columns + cross/oversold/overbought flags."""
    ap = (df["high"] + df["low"] + df["close"]) / 3.0
    esa = _ema(ap, n1)
    d = _ema((ap - esa).abs(), n1)
    # guard against zero-volatility division (keep float dtype — no object downcast)
    denom = 0.015 * d
    ci = (ap - esa) / denom.where(denom != 0, np.nan)
    ci = ci.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    wt1 = _ema(ci, n2)
    wt2 = wt1.rolling(4).mean()

    out = pd.DataFrame({"wt1": wt1, "wt2": wt2}, index=df.index)
    prev1, prev2 = wt1.shift(1), wt2.shift(1)
    out["cross_up"] = (prev1 <= prev2) & (wt1 > wt2)
    out["cross_dn"] = (prev1 >= prev2) & (wt1 < wt2)
    out["oversold"] = wt2 <= os
    out["overbought"] = wt2 >= ob
    # the canonical Cipher-B dots
    out["green_dot"] = out["cross_up"] & out["oversold"]
    out["red_dot"] = out["cross_dn"] & out["overbought"]
    return out


def analyze_wavetrend(df: pd.DataFrame, n1: int = 10, n2: int = 21,
                      ob: float = 53.0, os: float = -53.0) -> dict | None:
    """
    Read the WaveTrend state off the last COMPLETED bar.

    Returns:
      wt1, wt2            latest oscillator values
      green_dot/red_dot   True if the canonical Cipher-B dot printed on the last bar
      cross_up/cross_dn   raw crosses (a weaker confirmation than the dot)
      zone                'oversold' | 'overbought' | 'neutral'
      bars_since_green    bars since the most recent green dot (None if none in window)
    """
    if df is None or len(df) < n1 + n2 + 5:
        return None
    wt = wavetrend(df, n1, n2, ob, os)
    last = wt.iloc[-1]

    green_idx = wt.index[wt["green_dot"]]
    bars_since_green = (len(wt) - 1 - wt.index.get_loc(green_idx[-1])) if len(green_idx) else None
    red_idx = wt.index[wt["red_dot"]]
    bars_since_red = (len(wt) - 1 - wt.index.get_loc(red_idx[-1])) if len(red_idx) else None

    zone = ("oversold" if bool(last["oversold"])
            else "overbought" if bool(last["overbought"]) else "neutral")
    return {
        "wt1": round(float(last["wt1"]), 1),
        "wt2": round(float(last["wt2"]), 1),
        "green_dot": bool(last["green_dot"]),
        "red_dot": bool(last["red_dot"]),
        "cross_up": bool(last["cross_up"]),
        "cross_dn": bool(last["cross_dn"]),
        "zone": zone,
        "bars_since_green": bars_since_green,
        "bars_since_red": bars_since_red,
    }


if __name__ == "__main__":
    import sys, json
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from data.fetcher import load_15m
    df = load_15m()
    print(json.dumps(analyze_wavetrend(df), ensure_ascii=False, indent=2, default=str))
