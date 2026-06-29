"""
Nadaraya-Watson Envelope — a kernel-regression mean-reversion band.

Popularised by LuxAlgo on TradingView: a Gaussian-kernel weighted moving
average (the "smoother") with an envelope drawn at ±(mean abs error × mult).
This is a faithful Python port of the user's Pine v5 strategy "NWE Mean
Reversion [魔改 v4]" — same endpoint algorithm, same band math, same trigger
lines — so the dashboard's read matches what they backtest on TradingView.

The user's strategy:
  buyLine  = upper − rng × level/100   (level=90 → bottom 10% zone, the yellow line)
  sellLine = lower + rng × level/100   (top 10% zone, the orange line)
  · close crosses DOWN buyLine   → buy
  · close crosses UP   sellLine  → sell half
  · close crosses UP   upper     → sell all

⚠️ NON-REPAINTING on purpose (matches their "endpoint" algo). LuxAlgo's *default*
indicator uses a two-sided kernel, so the smoother's endpoint keeps getting
re-fitted as new bars arrive — the pretty "touched the band then bounced"
signals you see on the historical chart never actually existed at that bar's
close. That is exactly why a repainting NWE backtests so high: it peeks at the
future. The endpoint algorithm here (and in their Pine) uses a **one-sided
causal kernel** — weights only on the current + past bars — so the line printed
at bar t is fixed forever and was tradeable at that close. Win rate will be lower
than a repainting chart suggests; that is the honest number. Like every other
mechanical signal in this repo it feeds the transparent scan score and is graded
by the paper-trade ledger, so its real edge (if any) is measured, not assumed.

Self-contained: needs only a daily OHLC df with a lowercase 'close' column.

Output (key fields):
  nw          endpoint of the causal smoother (the regression "fair value")
  upper/lower outer envelope bands
  buy_line    bottom-zone trigger (their yellow line) — buy at/below this
  sell_line   top-zone trigger (their orange line) — take profit at/above this
  position    where close sits in [lower→0, upper→1]; <0 below band, >1 above
  stance      near_lower | inside | near_upper
  signal      +1 (in/below buy zone → buy) | 0 | -1 (in/above sell zone → fade)
  crossed_in  True only on the bar price first crosses DOWN into the buy zone
  crossed_out True only on the bar price first crosses UP into the sell zone
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Defaults match the user's Pine v5 inputs exactly.
_H        = 8.0    # bandwidth: ~25 most-recent bars carry the kernel weight
_MULT     = 3.0    # envelope half-width = mult × mean|residual|
_LEVEL    = 90.0   # zone depth: 90 → buy in bottom 10%, fade in top 10% (symmetric)
_LOOKBACK = 499    # kernel reach / MAE window, same as their `0 to 499` + sma(…,499)
_MIN_BARS = 60     # below this the smoother is noise (matches scan thin-data guard)
_BANDS_N  = 60     # how many trailing bars of the band to emit for the chart overlay


def _causal_nw(close: np.ndarray, h: float, lookback: int) -> np.ndarray:
    """Causal (non-repainting) Nadaraya-Watson endpoint smoother — the Pine
    `out = Σ src[i]·gauss(i,h) / Σ gauss(i,h)` evaluated at every bar.

    nw[t] = Σ_i w_i · close[t-i] / Σ_i w_i ,  w_i = exp(-i² / 2h²),  i = 0..L-1
    Only current + past bars enter, so nw[t] never changes once bar t closes.
    Early bars renormalise over the fewer samples available.
    """
    n = len(close)
    out = np.full(n, np.nan)
    w_full = np.exp(-(np.arange(lookback) ** 2) / (2.0 * h * h))
    for t in range(n):
        L = min(t + 1, lookback)
        w = w_full[:L]
        seg = close[t - L + 1 : t + 1][::-1]   # [close[t], close[t-1], …] aligns i=0,1,…
        out[t] = float(np.dot(w, seg) / w.sum())
    return out


def analyze_nw_envelope(
    df_d: pd.DataFrame,
    h: float = _H,
    mult: float = _MULT,
    level: float = _LEVEL,
    lookback: int = _LOOKBACK,
) -> dict:
    """Compute the non-repainting NW envelope on daily closes → a signal dict.

    Never raises on bad/short input — returns {'active': False, ...} instead, so
    callers can treat it like any other optional signal module.
    """
    if df_d is None or "close" not in df_d or len(df_d) < _MIN_BARS:
        return {"active": False, "signal": 0,
                "rationale": "日线数据不足，NW 包络无法计算"}

    close = df_d["close"].astype(float)          # keep the DatetimeIndex for the chart series
    nw = pd.Series(_causal_nw(close.to_numpy(), h, lookback), index=close.index)

    # Envelope half-width = mult × SMA(|close − nw|, lookback) — same as the
    # Pine `ta.sma(math.abs(src - out), 499) * mult`, computed as a series so the
    # bands (and trigger lines) at t-1 are available for the cross detection.
    mae = (close - nw).abs().rolling(lookback, min_periods=_MIN_BARS).mean() * mult
    upper = nw + mae
    lower = nw - mae
    rng = upper - lower
    buy_line = upper - rng * level / 100.0    # bottom-zone trigger (yellow)
    sell_line = lower + rng * level / 100.0   # top-zone trigger (orange)

    if not np.isfinite(mae.iloc[-1]) or mae.iloc[-1] <= 0:
        return {"active": False, "signal": 0, "rationale": "NW 残差异常，跳过"}

    price = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    mid = float(nw.iloc[-1])
    up, lo = float(upper.iloc[-1]), float(lower.iloc[-1])
    bl, sl = float(buy_line.iloc[-1]), float(sell_line.iloc[-1])
    width = up - lo
    pos = (price - lo) / width if width > 0 else 0.5   # 0=下轨, 1=上轨

    # Fresh-cross detection = the exact Pine entry/exit events (ta.crossunder /
    # ta.crossover), using each bar's own non-repainting trigger line.
    crossed_in = bool(price <= bl and prev > float(buy_line.iloc[-2]))
    crossed_out = bool(price >= sl and prev < float(sell_line.iloc[-2]))

    # Smoother slope over the last ~3 bars → trend context for the band touch.
    look = min(3, len(nw) - 1)
    slope_raw = mid - float(nw.iloc[-1 - look]) if look > 0 else 0.0
    eps = float(mae.iloc[-1]) * 0.05
    slope = "up" if slope_raw > eps else "down" if slope_raw < -eps else "flat"

    # stance = currently inside a zone (price at/beyond the trigger line). The
    # scan is a daily snapshot, so "sitting in the buy zone today" is the useful
    # stateless read; `crossed_in/out` additionally flags the exact trigger bar.
    if price <= bl:
        stance, signal = "near_lower", 1
    elif price >= sl:
        stance, signal = "near_upper", -1
    else:
        stance, signal = "inside", 0

    pct = round(pos * 100)
    slope_cn = {"up": "回归线上行", "down": "回归线下行", "flat": "回归线走平"}[slope]
    if stance == "near_lower":
        fresh = "（今日刚跌入，触发买点）" if crossed_in else "（已在区内）"
        note = f"NW 包络：跌进底部买入区 ≤${bl:.2f}{fresh} —— 均值回归式抄底位（下轨 ${lo:.2f}）"
    elif stance == "near_upper":
        fresh = "（今日刚涨入，触发止盈）" if crossed_out else "（已在区内）"
        zone = "并已突破上轨，按策略清仓" if price >= up else "可分批止盈/卖一半"
        note = f"NW 包络：涨进顶部卖出区 ≥${sl:.2f}{fresh} —— {zone}（上轨 ${up:.2f}）"
    else:
        note = f"NW 包络：处于区间中部（{pct}%），无极值信号"
    rationale = (
        f"非重绘 Nadaraya-Watson 包络（核宽 {h:.0f}/倍数 {mult:.0f}/区域 {level:.0f}）：回归中枢 ${mid:.2f}，"
        f"下轨 ${lo:.2f} / 上轨 ${up:.2f}；买入线 ${bl:.2f}（底部{100-level:.0f}%区）、"
        f"卖出线 ${sl:.2f}（顶部{100-level:.0f}%区）。现价 ${price:.2f} 落在包络 {pct}% 处"
        f"（0%=下轨,100%=上轨），{slope_cn}。"
        + ("现价已进入底部买入区。" if stance == "near_lower"
           else "现价已进入顶部卖出区。" if stance == "near_upper"
           else "现价在区间内，无极值信号。")
        + "（用因果单边端点核,信号当根收盘即定、不重绘——真实胜率低于 TradingView 重绘版回测,这是可交易的数。）"
    )

    # Per-bar band series (last N bars) for the decision-page chart overlay.
    # Times are int epoch seconds — the SAME format api.py uses for the candles,
    # so lightweight-charts aligns the envelope to the K-line bars.
    bands = []
    for ts in close.index[-_BANDS_N:]:
        u, l = float(upper.loc[ts]), float(lower.loc[ts])
        if not (np.isfinite(u) and np.isfinite(l)):
            continue
        bands.append({
            "time": int(pd.Timestamp(ts).timestamp()),
            "upper": round(u, 2), "lower": round(l, 2),
            "buy_line": round(float(buy_line.loc[ts]), 2),
            "sell_line": round(float(sell_line.loc[ts]), 2),
            "nw": round(float(nw.loc[ts]), 2),
        })

    return {
        "active": True,
        "signal": signal,
        "stance": stance,
        "nw": round(mid, 2),
        "upper": round(up, 2),
        "lower": round(lo, 2),
        "buy_line": round(bl, 2),
        "sell_line": round(sl, 2),
        "position": round(pos, 3),
        "position_pct": pct,
        "slope": slope,
        "crossed_in": crossed_in,
        "crossed_out": crossed_out,
        "broke_upper": bool(price >= up),
        "h": h, "mult": mult, "level": level, "bars": len(close),
        "bands": bands,
        "note": note,
        "rationale": rationale,
    }


if __name__ == "__main__":
    import sys, json
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from data.fetcher import load_or_fetch
    _, df_d = load_or_fetch()
    print(json.dumps(analyze_nw_envelope(df_d), ensure_ascii=False, indent=2))
