"""
Volume Profile / POC — volume-at-price structure on QBTS hourly bars.

The one dimension SMC (structural) is blind to: WHERE did real trading happen.
For a gap-and-trap name like QBTS this separates accepted value (high-volume
nodes) from rejected price (low-volume air pockets), which is exactly what the
trade plan needs for targets/stops:

  POC          point of control — highest-volume price = value magnet
  VAH / VAL    value area high/low — the 70%-of-volume band (fair-value range)
  HVN          high-volume nodes — support/resistance shelves
  LVN          low-volume nodes — thin price, moves fast, poor place for a stop
  naked POC    a prior day's POC never traded back through = unfilled magnet

Approximation note: built from 1h bars (no tick/minute data), so the profile is
coarse — each bar's volume is spread uniformly across the price bins its
high-low range spans. Good enough for POC / value-area levels.

All computation is causal (completed bars only).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_LOOKBACK_DAYS = 60      # naked-POC / daily-POC scan window (long → magnet coverage)
_VA_LOOKBACK   = 20      # value-area window (short → 现价 vs 价值区 判断灵敏、可被突破)
_N_BINS        = 50      # price resolution
_VALUE_AREA    = 0.70    # fraction of volume defining the value area


def _window(df_h: pd.DataFrame, lookback_days: int) -> pd.DataFrame:
    """Last `lookback_days` trading days of hourly bars."""
    dates = pd.DatetimeIndex(df_h.index).normalize()
    keep = pd.Index(dates.unique()).sort_values()[-lookback_days:]
    return df_h[dates.isin(set(keep))]


def _profile(w: pd.DataFrame, n_bins: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Volume-at-price histogram: spread each bar's volume across spanned bins."""
    lo, hi = float(w["low"].min()), float(w["high"].max())
    if hi <= lo:
        hi = lo + 1e-6
    edges   = np.linspace(lo, hi, n_bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    vol_at  = np.zeros(n_bins)
    span = hi - lo
    for low, high, vol in zip(w["low"].values, w["high"].values, w["volume"].values):
        lo_idx = int(np.clip((low  - lo) / span * n_bins, 0, n_bins - 1))
        hi_idx = int(np.clip((high - lo) / span * n_bins, 0, n_bins - 1))
        n = hi_idx - lo_idx + 1
        vol_at[lo_idx:hi_idx + 1] += float(vol) / n
    return edges, centers, vol_at


def _value_area(vol_at: np.ndarray, edges: np.ndarray) -> tuple[int, float, float]:
    """Expand from POC bin, greedily adding the heavier neighbour, until 70% vol."""
    poc_idx = int(np.argmax(vol_at))
    total = vol_at.sum()
    lo_i = hi_i = poc_idx
    acc = vol_at[poc_idx]
    while acc < _VALUE_AREA * total and (lo_i > 0 or hi_i < len(vol_at) - 1):
        left  = vol_at[lo_i - 1] if lo_i > 0 else -1.0
        right = vol_at[hi_i + 1] if hi_i < len(vol_at) - 1 else -1.0
        if right >= left:
            hi_i += 1; acc += vol_at[hi_i]
        else:
            lo_i -= 1; acc += vol_at[lo_i]
    val = float(edges[lo_i])
    vah = float(edges[hi_i + 1])
    return poc_idx, vah, val


def _daily_pocs(df_h: pd.DataFrame, w: pd.DataFrame) -> list[tuple[pd.Timestamp, float]]:
    """Per-day POC ≈ midpoint of that day's highest-volume hourly bar (cheap proxy)."""
    out = []
    dates = pd.DatetimeIndex(w.index).normalize()
    for d in pd.Index(dates.unique()).sort_values():
        day = w[dates == d]
        if day.empty:
            continue
        bar = day.loc[day["volume"].idxmax()]
        out.append((d, round((float(bar["high"]) + float(bar["low"])) / 2, 2)))
    return out


def _naked_pocs(df_h: pd.DataFrame, daily: list[tuple[pd.Timestamp, float]],
                price: float) -> tuple[list[float], list[float]]:
    """Daily POCs never traded back through by any LATER bar = unfilled magnets."""
    h, l = df_h["high"].values, df_h["low"].values
    idx = pd.DatetimeIndex(df_h.index).normalize()
    above, below = [], []
    for d, poc in daily[:-1]:                       # exclude today's still-forming POC
        later = idx > d
        if later.any() and not ((l[later] <= poc) & (h[later] >= poc)).any():
            (above if poc > price else below).append(poc)
    above = sorted(set(above))[:3]
    below = sorted(set(below), reverse=True)[:3]
    return above, below


def _hvn_lvn(centers: np.ndarray, vol_at: np.ndarray) -> tuple[list[float], list[float]]:
    """Local volume peaks (shelves) and troughs (air pockets)."""
    hvn, lvn = [], []
    for i in range(1, len(vol_at) - 1):
        if vol_at[i] >= vol_at[i - 1] and vol_at[i] >= vol_at[i + 1]:
            hvn.append((vol_at[i], round(float(centers[i]), 2)))
        if vol_at[i] <= vol_at[i - 1] and vol_at[i] <= vol_at[i + 1]:
            lvn.append((vol_at[i], round(float(centers[i]), 2)))
    hvn = [p for _, p in sorted(hvn, reverse=True)[:4]]
    lvn = [p for _, p in sorted(lvn)[:4]]
    return hvn, lvn


def _action_hint(where: str, val: float, vah: float,
                 mag_up: float | None, mag_down: float | None,
                 naked_above: list[float], naked_below: list[float],
                 lvn: list[float]) -> tuple[str, str]:
    """Translate the levels into an explicit breakout/breakdown playbook.

    Single source of truth shared by the dashboard card and the decision prompt,
    so the user and the model read the same plain-language plan.
    """
    up_targets   = [p for p in naked_above if mag_up   and p > mag_up][:2]
    down_targets = [p for p in naked_below if mag_down and p < mag_down][:2]
    up_t = " → ".join(f"${p}" for p in up_targets)   or f"${vah}(VAH)"
    dn_t = " → ".join(f"${p}" for p in down_targets) or f"${val}(VAL)"

    parts: list[str] = []
    if mag_up:
        parts.append(f"站上 ${mag_up} 上看 {up_t}")
    if mag_down:
        parts.append(f"跌破 ${mag_down} 下看 {dn_t}")
    if where == "inside":
        stance = "观望"
        if mag_up and mag_down:
            parts.append(f"${mag_down}–${mag_up} 区间内观望（价值区均衡，无 edge）")
    elif where == "above":
        stance = "偏多"
        parts.append(f"现价已破价值区上沿，偏多；跌回 ${vah}(VAH) 下方转弱")
    else:
        stance = "偏空"
        parts.append(f"现价已破价值区下沿，偏空；收复 ${val}(VAL) 上方转强")

    hint = "；".join(parts)
    if lvn:
        hint += f"。止损勿放 LVN（{'、'.join(f'${x}' for x in lvn[:3])}）"
    return hint, stance


def analyze_volume_profile(df_h: pd.DataFrame, live_price: float | None = None,
                           lookback_days: int = _LOOKBACK_DAYS,
                           va_lookback_days: int = _VA_LOOKBACK,
                           n_bins: int = _N_BINS) -> dict:
    """Composite volume profile on hourly bars.

    Two decoupled windows: the value area (POC/VAH/VAL + HVN/LVN) is built on a
    SHORT window (`va_lookback_days`) so "现价 vs 价值区" tracks CURRENT accepted
    value and is actually breakable — a long window drags VAH up with weeks-old
    volume from a different price regime, leaving price permanently "inside".
    Naked/daily POC magnets keep the LONG window (`lookback_days`) so an old but
    unfilled gap is still surfaced as a target.
    """
    if df_h is None or len(df_h) < 10:
        return {"signal": 0, "label": "HOLD", "rationale": "1h 数据不足，无法构建成交量画像"}

    w_va    = _window(df_h, va_lookback_days)     # value area (short, responsive)
    w_daily = _window(df_h, lookback_days)        # daily POCs for naked magnets (long)
    price = float(live_price if live_price else df_h["close"].iloc[-1])

    edges, centers, vol_at = _profile(w_va, n_bins)
    poc_idx, vah, val = _value_area(vol_at, edges)
    poc = round(float(centers[poc_idx]), 2)

    hvn, lvn = _hvn_lvn(centers, vol_at)
    naked_above, naked_below = _naked_pocs(df_h, _daily_pocs(df_h, w_daily), price)

    where = "above" if price > vah else ("below" if price < val else "inside")

    # nearest magnet = nearest naked POC, else nearest HVN, on each side
    ups   = sorted([p for p in (naked_above + hvn) if p > price])
    downs = sorted([p for p in (naked_below + hvn) if p < price], reverse=True)
    nearest_up   = ups[0]   if ups   else None
    nearest_down = downs[0] if downs else None

    # signal: acceptance outside value is a directional tell; inside = balance
    score = 0
    notes = [f"POC ${poc}，价值区 ${round(val,2)}–${round(vah,2)}"]
    if where == "above":
        score = 1
        notes.append(f"现价 ${round(price,2)} 在价值区上方（接受更高价，偏多但防回归 VAH）")
    elif where == "below":
        score = -1
        notes.append(f"现价 ${round(price,2)} 在价值区下方（价值下移，偏空）")
    else:
        notes.append(f"现价 ${round(price,2)} 处于价值区内（均衡，等突破）")
    if nearest_up:
        notes.append(f"上方磁吸 ${nearest_up}" + ("（naked POC）" if nearest_up in naked_above else "（HVN）"))
    if nearest_down:
        notes.append(f"下方磁吸 ${nearest_down}" + ("（naked POC）" if nearest_down in naked_below else "（HVN）"))

    signal = score
    action_hint, stance = _action_hint(
        where, round(val, 2), round(vah, 2), nearest_up, nearest_down,
        naked_above, naked_below, lvn)
    return {
        "signal":          signal,
        "label":           {1: "BUY", -1: "SELL", 0: "HOLD"}[signal],
        "poc":             poc,
        "vah":             round(vah, 2),
        "val":             round(val, 2),
        "price":           round(price, 2),
        "price_vs_value":  where,
        "hvn":             hvn,
        "lvn":             lvn,
        "naked_pocs_above": naked_above,
        "naked_pocs_below": naked_below,
        "nearest_magnet_up":   nearest_up,
        "nearest_magnet_down": nearest_down,
        "lookback_days":   va_lookback_days,
        "stance":          stance,
        "action_hint":     action_hint,
        "rationale":       "；".join(notes),
        "note":            f"价值区取近 {va_lookback_days} 日(灵敏)、磁吸 naked POC 取近 {lookback_days} 日；1h bar 近似，无 tick 数据",
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from data.fetcher import load_or_fetch
    import json
    df_h, _ = load_or_fetch()
    print(json.dumps(analyze_volume_profile(df_h), ensure_ascii=False, indent=2, default=str))
