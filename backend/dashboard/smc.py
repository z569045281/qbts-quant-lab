"""
Smart Money Concepts (SMC) structural analysis on QBTS daily bars.

Quantifies the ICT/SMC playbook into deterministic, explainable components:

  swings            fractal swing highs/lows (k bars each side)
  structure         trend from HH/HL vs LH/LL + last BOS / CHoCH event
  FVG               fair value gaps (3-candle imbalance), unmitigated only
  order blocks      last opposite candle before a structure-breaking impulse
  liquidity sweep   wick through a prior swing extreme that closes back inside
  premium/discount  position of price within the dominant swing range

Output is a signal (-1/0/+1) + key levels + a Chinese rationale, consumed by
both the decision engine (prompt section) and the dashboard (SMC card).

All computations are causal (only completed daily bars).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ── swings ───────────────────────────────────────────────────────────────────

def find_swings(df: pd.DataFrame, k: int = 2) -> tuple[list[dict], list[dict]]:
    """Fractal swings: bar whose high(low) exceeds k bars on each side."""
    highs, lows = [], []
    h, l = df["high"].values, df["low"].values
    idx = df.index
    for i in range(k, len(df) - k):
        if h[i] == max(h[i - k:i + k + 1]):
            highs.append({"i": i, "date": idx[i].strftime("%m-%d"), "price": float(h[i])})
        if l[i] == min(l[i - k:i + k + 1]):
            lows.append({"i": i, "date": idx[i].strftime("%m-%d"), "price": float(l[i])})
    return highs, lows


# ── market structure (BOS / CHoCH) ───────────────────────────────────────────

def analyze_structure(df: pd.DataFrame, swing_highs: list[dict], swing_lows: list[dict]) -> dict:
    """
    Walk closes against swing levels to find the latest structure event.
      BOS   = break in the direction of the prevailing trend (continuation)
      CHoCH = first break against the prevailing trend (potential reversal)
    """
    closes = df["close"].values
    n = len(df)
    trend = 0                  # +1 bullish / -1 bearish / 0 unknown
    last_event = None

    events: list[dict] = []
    hi_q = [s for s in swing_highs]
    lo_q = [s for s in swing_lows]

    broken_high_i = set()
    broken_low_i  = set()
    for i in range(n):
        c = closes[i]
        for s in hi_q:
            if s["i"] < i and s["i"] not in broken_high_i and c > s["price"]:
                broken_high_i.add(s["i"])
                kind = "BOS" if trend >= 0 else "CHoCH"
                trend = 1
                events.append({"i": i, "date": df.index[i].strftime("%m-%d"),
                               "kind": kind, "dir": "bullish", "level": s["price"]})
        for s in lo_q:
            if s["i"] < i and s["i"] not in broken_low_i and c < s["price"]:
                broken_low_i.add(s["i"])
                kind = "BOS" if trend <= 0 else "CHoCH"
                trend = -1
                events.append({"i": i, "date": df.index[i].strftime("%m-%d"),
                               "kind": kind, "dir": "bearish", "level": s["price"]})

    last_event = events[-1] if events else None
    return {
        "trend": "bullish" if trend > 0 else ("bearish" if trend < 0 else "neutral"),
        "last_event": last_event,
        "recent_events": events[-3:],
    }


# ── fair value gaps ──────────────────────────────────────────────────────────

def find_fvgs(df: pd.DataFrame, lookback: int = 90) -> list[dict]:
    """3-candle imbalances, kept only while unmitigated (price hasn't filled)."""
    out = []
    h, l = df["high"].values, df["low"].values
    n = len(df)
    start = max(2, n - lookback)
    for i in range(start, n):
        # bullish FVG: candle i-2 high < candle i low → gap [h[i-2], l[i]]
        if h[i - 2] < l[i]:
            zone_lo, zone_hi = float(h[i - 2]), float(l[i])
            # mitigated if any later low traded into the zone
            if not any(l[j] <= zone_hi for j in range(i + 1, n)):
                out.append({"type": "bullish", "low": round(zone_lo, 2),
                            "high": round(zone_hi, 2),
                            "date": df.index[i].strftime("%m-%d")})
        # bearish FVG: candle i-2 low > candle i high → gap [h[i], l[i-2]]
        if l[i - 2] > h[i]:
            zone_lo, zone_hi = float(h[i]), float(l[i - 2])
            if not any(h[j] >= zone_lo for j in range(i + 1, n)):
                out.append({"type": "bearish", "low": round(zone_lo, 2),
                            "high": round(zone_hi, 2),
                            "date": df.index[i].strftime("%m-%d")})
    return out


# ── order blocks (simplified) ────────────────────────────────────────────────

def find_order_blocks(df: pd.DataFrame, structure_events: list[dict]) -> list[dict]:
    """
    For each recent structure break, the last opposite-direction candle before
    the breaking move = order block. Unmitigated = price hasn't closed through it.
    """
    out = []
    o, c, h, l = df["open"].values, df["close"].values, df["high"].values, df["low"].values
    n = len(df)
    for ev in structure_events[-4:]:
        i = ev["i"]
        if ev["dir"] == "bullish":
            # last bearish candle before i
            for j in range(i - 1, max(0, i - 10), -1):
                if c[j] < o[j]:
                    zone_lo, zone_hi = float(l[j]), float(max(o[j], c[j]))
                    if not any(c[k2] < zone_lo for k2 in range(i, n)):
                        out.append({"type": "demand", "low": round(zone_lo, 2),
                                    "high": round(zone_hi, 2),
                                    "date": df.index[j].strftime("%m-%d")})
                    break
        else:
            for j in range(i - 1, max(0, i - 10), -1):
                if c[j] > o[j]:
                    zone_lo, zone_hi = float(min(o[j], c[j])), float(h[j])
                    if not any(c[k2] > zone_hi for k2 in range(i, n)):
                        out.append({"type": "supply", "low": round(zone_lo, 2),
                                    "high": round(zone_hi, 2),
                                    "date": df.index[j].strftime("%m-%d")})
                    break
    return out


# ── liquidity sweeps ─────────────────────────────────────────────────────────

def find_sweeps(df: pd.DataFrame, swing_highs: list[dict], swing_lows: list[dict],
                window: int = 5) -> list[dict]:
    """Wick through a prior swing extreme that closes back inside = stop hunt."""
    out = []
    n = len(df)
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    for i in range(max(0, n - window), n):
        for s in swing_lows:
            if s["i"] < i - 1 and l[i] < s["price"] and c[i] > s["price"]:
                out.append({"dir": "bullish", "level": round(s["price"], 2),
                            "date": df.index[i].strftime("%m-%d"),
                            "note": f"扫过 {s['date']} 低点 ${s['price']:.2f} 后收回 — 空头流动性被收割"})
                break
        for s in swing_highs:
            if s["i"] < i - 1 and h[i] > s["price"] and c[i] < s["price"]:
                out.append({"dir": "bearish", "level": round(s["price"], 2),
                            "date": df.index[i].strftime("%m-%d"),
                            "note": f"扫过 {s['date']} 高点 ${s['price']:.2f} 后回落 — 多头流动性被收割"})
                break
    return out[-3:]


# ── composite ────────────────────────────────────────────────────────────────

def analyze_smc(df: pd.DataFrame, live_price: float | None = None) -> dict:
    """Full SMC read on the last ~120 daily bars."""
    d = df.tail(120).reset_index().rename(columns=str.lower)
    d = d.set_index(d.columns[0]) if d.columns[0] != "open" else d
    d.index = pd.DatetimeIndex(df.tail(120).index)

    price = float(live_price if live_price else df["close"].iloc[-1])

    swing_highs, swing_lows = find_swings(d)
    structure = analyze_structure(d, swing_highs, swing_lows)
    fvgs      = find_fvgs(d)
    obs       = find_order_blocks(d, structure["recent_events"])
    sweeps    = find_sweeps(d, swing_highs, swing_lows)

    # premium / discount within the dominant range (last major swing hi/lo)
    rng_hi = max((s["price"] for s in swing_highs[-4:]), default=price)
    rng_lo = min((s["price"] for s in swing_lows[-4:]),  default=price)
    pos = (price - rng_lo) / (rng_hi - rng_lo) if rng_hi > rng_lo else 0.5
    zone = "discount(折价区)" if pos < 0.4 else ("premium(溢价区)" if pos > 0.6 else "equilibrium(均衡区)")

    # nearest unmitigated zones relative to price
    all_zones = ([{"kind": "FVG", **z} for z in fvgs]
                 + [{"kind": "OB", "type": "bullish" if z["type"] == "demand" else "bearish",
                     "low": z["low"], "high": z["high"], "date": z["date"]} for z in obs])
    demand = sorted([z for z in all_zones if z["type"] == "bullish" and z["high"] <= price * 1.02],
                    key=lambda z: -z["high"])[:2]
    supply = sorted([z for z in all_zones if z["type"] == "bearish" and z["low"] >= price * 0.98],
                    key=lambda z: z["low"])[:2]

    # ── composite signal ─────────────────────────────────────────
    score = 0
    notes = []
    if structure["trend"] == "bullish":
        score += 1; notes.append("结构看多")
    elif structure["trend"] == "bearish":
        score -= 1; notes.append("结构看空")
    le = structure["last_event"]
    if le and le["kind"] == "CHoCH":
        score += 1 if le["dir"] == "bullish" else -1
        notes.append(f"{le['date']} 出现 {le['dir']} CHoCH（潜在反转）")
    for sw in sweeps:
        score += 1 if sw["dir"] == "bullish" else -1
        notes.append(sw["note"])
    if pos < 0.35 and structure["trend"] != "bearish":
        score += 1; notes.append(f"价格处于折价区({pos*100:.0f}%)，利于做多")
    elif pos > 0.65 and structure["trend"] != "bullish":
        score -= 1; notes.append(f"价格处于溢价区({pos*100:.0f}%)，利于做空")

    signal = 1 if score >= 2 else (-1 if score <= -2 else 0)
    label = {1: "BUY", -1: "SELL", 0: "HOLD"}[signal]

    return {
        "signal": signal,
        "label":  label,
        "score":  score,
        "trend":  structure["trend"],
        "last_event": structure["last_event"],
        "zone":   zone,
        "range_position": round(pos, 3),
        "range": {"high": round(rng_hi, 2), "low": round(rng_lo, 2)},
        "demand_zones": demand,
        "supply_zones": supply,
        "sweeps": sweeps,
        "rationale": "；".join(notes) if notes else "结构中性，无显著 SMC 信号",
        "price_used": round(price, 2),
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from data.fetcher import load_or_fetch
    _, df_d = load_or_fetch()
    import json
    print(json.dumps(analyze_smc(df_d), ensure_ascii=False, indent=2, default=str))
