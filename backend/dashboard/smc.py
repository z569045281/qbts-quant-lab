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

try:
    from dashboard.wavetrend import analyze_wavetrend
except ImportError:  # allow running as a loose module
    from wavetrend import analyze_wavetrend


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
        "recent_events": events[-40:],   # 窗口够 15m CHoCH 回看;下游 find_order_blocks 仍取 [-4:]
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


# ── multi-timeframe playbook (global lock → relay → 15m trigger → FVG) ───────

def resample_ohlc(df: pd.DataFrame | None, rule: str = "4h") -> pd.DataFrame | None:
    """Resample an intraday frame to a higher TF (e.g. 1h → 4h)."""
    if df is None or len(df) == 0:
        return None
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = df.resample(rule).agg(agg).dropna(subset=["open", "high", "low", "close"])
    return out if len(out) else None


def _frame_zones(df: pd.DataFrame | None, k: int = 2, tail: int = 320) -> tuple[list, list]:
    """(order_blocks, fvgs) on an intraday frame — reuses the daily machinery."""
    if df is None or len(df) < 2 * k + 12:
        return [], []
    d = df.tail(tail)
    sh, sl = find_swings(d, k=k)
    st = analyze_structure(d, sh, sl)
    obs = find_order_blocks(d, st["recent_events"])
    fvgs = find_fvgs(d, lookback=min(120, len(d)))
    return obs, fvgs


def _ltf15_trigger(df_15m: pd.DataFrame | None, lock: str) -> dict | None:
    """15m read for the final trigger: a fresh same-direction CHoCH + a
    close-confirmed WaveTrend (VMC) dot. Returns None when 15m data is absent."""
    if df_15m is None or len(df_15m) < 40:
        return None
    d15 = df_15m.tail(220)
    sh, sl = find_swings(d15, k=2)
    st15 = analyze_structure(d15, sh, sl)
    wt = analyze_wavetrend(d15)
    le15 = st15.get("last_event")
    n15 = len(d15)
    want_dir = "bullish" if lock == "bull" else "bearish"
    bars_since = (n15 - 1 - le15["i"]) if le15 else None
    # CHoCH 是转瞬即逝的:性格转变后价格再破一个点就变成同向 BOS,一两根内就把
    # last_event 覆盖成 BOS —— 所以"最新事件必须正好是 CHoCH"几乎永远不触发。
    # 改判:近 12 根内是否出现过【想要方向】的 CHoCH(即便随后被 BOS 覆盖)。
    # CHoCH→同向 BOS 恰是最理想的确认,不该算漏。
    choch_ev = next((e for e in reversed(st15.get("recent_events") or [])
                     if e["kind"] == "CHoCH" and e["dir"] == want_dir
                     and (n15 - 1 - e["i"]) <= 12), None)
    choch_ok = choch_ev is not None
    choch_bars = (n15 - 1 - choch_ev["i"]) if choch_ev else None
    # VMC 点同样是单根 bar 事件(仅穿越那一根 red_dot/green_dot=True)——只认最后一根
    # 几乎不触发。改判:近 12 根内印出过对应方向的 VMC 点(与 ④ CHoCH 同窗口)。
    # bars_since_red/green 由 analyze_wavetrend 已算好。
    dot_bars = (wt.get("bars_since_green") if lock == "bull" else wt.get("bars_since_red")) if wt else None
    dot_ok = dot_bars is not None and dot_bars <= 12
    return {"trend": st15["trend"], "last_event": le15, "bars_since_event": bars_since,
            "choch_ok": choch_ok, "choch_bars": choch_bars,
            "wt": wt, "dot_ok": dot_ok, "dot_bars": dot_bars}


def _dealing_range(d: pd.DataFrame, swing_highs: list, swing_lows: list,
                   last_event: dict | None, price: float) -> tuple[float, float]:
    """Premium/discount range anchored to the swing that PRINTED the last
    structure label — NOT the global hi/lo (which inflates the 0.5 line).

    Down-break (bearish BOS/CHoCH): top = the Lower High just BEFORE the break,
    bottom = the lowest low SINCE the break. Up-break: mirror. This binds the
    50% equilibrium to the active structural leg, per the SMC dealing-range rule.
    """
    h, l = d["high"].values, d["low"].values
    n = len(d)

    def _recent_swing_range():
        hi = max((s["price"] for s in swing_highs[-4:]), default=float(h.max()))
        lo = min((s["price"] for s in swing_lows[-4:]),  default=float(l.min()))
        return hi, lo

    if not last_event:
        return _recent_swing_range()
    bi = int(last_event["i"])
    if last_event["dir"] == "bearish":
        prior = [s for s in swing_highs if s["i"] < bi]
        rng_hi = float(prior[-1]["price"]) if prior else float(h[:max(bi, 1)].max())
        rng_lo = float(l[bi:].min()) if bi < n else float(l.min())
    else:
        prior = [s for s in swing_lows if s["i"] < bi]
        rng_lo = float(prior[-1]["price"]) if prior else float(l[:max(bi, 1)].min())
        rng_hi = float(h[bi:].max()) if bi < n else float(h.max())
    if rng_hi <= rng_lo:                       # degenerate guard
        return _recent_swing_range()
    return rng_hi, rng_lo


def build_playbook(price: float, structure: dict, pos: float,
                   rng_hi: float, rng_lo: float,
                   daily_fvgs: list, daily_obs: list,
                   df_4h: pd.DataFrame | None, df_1h: pd.DataFrame | None,
                   df_15m: pd.DataFrame | None, tol: float = 0.006) -> dict:
    """
    Disciplined trend-following state machine:

      Module 1  Global lock  — direction is read ONLY from the latest daily
                               structure label (BOS/CHoCH). Bull lock → longs only.
      Module 2  Relay/降维   — on a pullback, drop to 4h/1h for a relay OB + the
                               fib-0.5 equilibrium; price in discount(premium) AND
                               touching a sub-TF OB ⇒ ARMED. Then 15m CHoCH + VMC
                               (WaveTrend) dot ⇒ TRIGGER (AND logic).
      Module 3  FVG          — entry = FVG edge ∩ OB overlap (共振狙击点);
                               TP1 = nearest unfilled FVG edge ahead (止盈磁吸).
    """
    le = structure.get("last_event")
    lock = ("bull" if le and le["dir"] == "bullish"
            else "bear" if le and le["dir"] == "bearish" else "none")
    lock_reason = (f"{le['date']} {'向上' if le['dir'] == 'bullish' else '向下'}"
                   f"{le['kind']} @ ${le['level']:.2f}" if le else "日线尚无明确结构标签")
    eq = round((rng_hi + rng_lo) / 2, 2) if rng_hi > rng_lo else round(price, 2)

    # ── zone pools across daily + 4h + 1h ────────────────────────
    obs_4h, fvg_4h = _frame_zones(df_4h)
    obs_1h, fvg_1h = _frame_zones(df_1h)
    pool_obs = ([{**z, "tf": "日线"} for z in daily_obs]
                + [{**z, "tf": "4h"} for z in obs_4h]
                + [{**z, "tf": "1h"} for z in obs_1h])
    pool_fvg = ([{**z, "tf": "日线"} for z in daily_fvgs]
                + [{**z, "tf": "4h"} for z in fvg_4h]
                + [{**z, "tf": "1h"} for z in fvg_1h])

    want_ob = "demand" if lock == "bull" else "supply"

    # ── relay zones (Module 2 降维): direction-appropriate zones near the 0.5
    # equilibrium that price can still travel INTO. Do NOT skip a zone just
    # because price poked its near edge — the nearest UNTESTED supply/demand zone
    # around eq IS the relay target. Prefer intraday (1h/4h) over the far daily
    # Extreme OB; pick the zone NEAREST the equilibrium line.
    def _dist_to_eq(z):
        return 0.0 if z["low"] <= eq <= z["high"] else min(abs(z["low"] - eq), abs(z["high"] - eq))
    tf_rank = {"1h": 0, "4h": 1, "日线": 2}     # finer/intraday relay preferred

    relay = []
    for z in pool_obs:
        if z["type"] != want_ob:
            continue
        if lock == "bull":                       # demand: room below price, discount half
            if z["low"] <= price * (1 + tol) and z["low"] <= eq * (1 + tol):
                relay.append(z)
        else:                                    # supply: room above price, premium half
            if z["high"] >= price * (1 - tol) and z["high"] >= eq * (1 - tol):
                relay.append(z)
    # dedup identical zones across TFs, keeping the finer TF
    _best: dict = {}
    for z in relay:
        key = (z["low"], z["high"])
        if key not in _best or tf_rank.get(z["tf"], 3) < tf_rank.get(_best[key]["tf"], 3):
            _best[key] = z
    relay = sorted(_best.values(), key=lambda z: (_dist_to_eq(z), tf_rank.get(z["tf"], 3)))
    nearest_relay = relay[0] if relay else None
    touching_relay = bool(nearest_relay and
                          nearest_relay["low"] * (1 - tol) <= price <= nearest_relay["high"] * (1 + tol))

    in_zone = False
    if rng_hi > rng_lo:
        in_zone = (pos <= 0.5) if lock == "bull" else (pos >= 0.5) if lock == "bear" else False

    ltf15 = _ltf15_trigger(df_15m, lock) if lock != "none" else None

    # ── state machine (action/label finalized AFTER the RR circuit breaker) ──
    if lock == "none":
        state = "NO_LOCK"
    else:
        armed = in_zone and touching_relay
        triggered = bool(armed and ltf15 and ltf15["choch_ok"] and ltf15["dot_ok"])
        state = "TRIGGER" if triggered else ("ARMED" if armed else "WAIT")

    # ── entry = precise confluence INSIDE the relay zone, drilled to 1h/4h
    # (Module 2/3 共振狙击点). The relay zone is the region; refine to the finest-
    # TF FVG∩OB overlap / sub-TF imbalance that falls inside it for the exact
    # price. Never fall back to the far daily Extreme OB when a relay zone exists.
    entry_zone = None
    if nearest_relay:
        r_lo, r_hi = nearest_relay["low"], nearest_relay["high"]

        def _clip(lo, hi):
            return round(max(lo, r_lo), 2), round(min(hi, r_hi), 2)

        confl = []
        # (a) FVG ∩ OB overlaps intersecting the relay region → resonance level
        for ob in (z for z in pool_obs if z["type"] == want_ob):
            for fv in pool_fvg:
                lo, hi = max(ob["low"], fv["low"]), min(ob["high"], fv["high"])
                if hi > lo and hi >= r_lo and lo <= r_hi:
                    clo, chi = _clip(lo, hi)
                    confl.append({"low": clo, "high": chi, "tf": ob["tf"],
                                  "basis": f"FVG∩OB ({ob['tf']})"})
        # (b) sub-TF (1h/4h) FVGs inside the region → precise imbalance level
        for z in pool_fvg:
            if z["tf"] in ("1h", "4h") and z["high"] >= r_lo and z["low"] <= r_hi:
                clo, chi = _clip(z["low"], z["high"])
                confl.append({"low": clo, "high": chi, "tf": z["tf"],
                              "basis": f"{z['tf']} FVG×中继区"})
        # (c) sub-TF (1h/4h) OBs inside the region → precise relay level
        for z in pool_obs:
            if (z["type"] == want_ob and z["tf"] in ("1h", "4h")
                    and z["high"] >= r_lo and z["low"] <= r_hi):
                clo, chi = _clip(z["low"], z["high"])
                confl.append({"low": clo, "high": chi, "tf": z["tf"],
                              "basis": f"{z['tf']} {'供给' if want_ob == 'supply' else '需求'}区"})
        # never emit a wide daily OB span — prefer the TIGHTEST (≤$1) 1h/4h
        # confluence; tie-break by finer TF then nearest the equilibrium.
        MAX_W = 1.00
        if confl:
            confl.sort(key=lambda c: (0 if (c["high"] - c["low"]) <= MAX_W else 1,
                                      tf_rank.get(c["tf"], 3), _dist_to_eq(c)))
            entry_zone = {k: confl[0][k] for k in ("low", "high", "basis")}
        else:
            entry_zone = {"low": r_lo, "high": r_hi, "basis": f"中继OB ({nearest_relay['tf']})"}
        # enforce ≤$1.00: if still a wide daily region (no LTF confluence found),
        # clip to a $1 band at the PROXIMAL edge (where price first interacts).
        if (entry_zone["high"] - entry_zone["low"]) > MAX_W:
            if lock == "bear":     # supply: proximal edge = bottom (first touched on a rally)
                entry_zone = {"low": round(r_lo, 2), "high": round(r_lo + MAX_W, 2),
                              "basis": f"中继区近端·需1h确认 ({nearest_relay['tf']})"}
            else:                  # demand: proximal edge = top (first touched on a dip)
                entry_zone = {"low": round(r_hi - MAX_W, 2), "high": round(r_hi, 2),
                              "basis": f"中继区近端·需1h确认 ({nearest_relay['tf']})"}

    # ── stop just beyond the (refined) ENTRY zone — 降维 = tighter stop → higher RR ──
    stop = None
    if entry_zone:
        stop = round(entry_zone["low"] * (1 - 0.008), 2) if lock == "bull" \
            else round(entry_zone["high"] * (1 + 0.008), 2)

    # ── TP1 = nearest unfilled FVG edge BEYOND the entry zone (Module 3 止盈磁吸).
    # Measured from the entry edge (not current price) so an FVG overlapping the
    # entry can't masquerade as the target and collapse RR into a false veto. ─
    tp1 = None
    if lock == "bull":
        floor_ = (entry_zone or {}).get("high", price)
        ahead = [z for z in pool_fvg if z["low"] > floor_]
        if ahead:
            m = min(ahead, key=lambda z: z["low"])
            tp1 = {"price": m["low"], "basis": f"FVG 磁吸 ${m['low']}–${m['high']} ({m['tf']})"}
    elif lock == "bear":
        cap = (entry_zone or {}).get("low", price)
        ahead = [z for z in pool_fvg if z["high"] < cap]
        if ahead:
            m = max(ahead, key=lambda z: z["high"])
            tp1 = {"price": m["high"], "basis": f"FVG 磁吸 ${m['low']}–${m['high']} ({m['tf']})"}

    tp2 = None
    if lock == "bull" and rng_hi > price:
        tp2 = {"price": round(rng_hi, 2), "basis": "区间高（主摆动高）"}
    elif lock == "bear" and rng_lo < price:
        tp2 = {"price": round(rng_lo, 2), "basis": "区间低（主摆动低）"}

    rr = None
    if entry_zone and stop and tp1:
        mid = (entry_zone["low"] + entry_zone["high"]) / 2
        risk, reward = abs(mid - stop), abs(tp1["price"] - mid)
        rr = round(reward / risk, 2) if risk > 0 else None

    # ── 风控熔断: RR < 2.0 的入场策略无效 → 强制观望 (Module 3) ──
    rr_veto = (rr is not None and rr < 2.0)
    if rr_veto and state in ("TRIGGER", "ARMED"):
        state = "WAIT"
    action = ("buy" if lock == "bull" else "sell") if state == "TRIGGER" else "wait"
    state_cn = {"TRIGGER": "扣扳机 · 可入场", "ARMED": "预警 · 已就位，等 15m 触发",
                "WAIT": "等待回踩到位", "NO_LOCK": "无方向锁定 · 观望"}[state]
    risk_note = None
    if rr_veto:
        state_cn = f"观望 · RR {rr}<2 风控熔断"
        risk_note = f"⚠️ 盈亏比 {rr} < 2.0,风险收益不达标 → 风控熔断,此入场策略无效,强制观望。"

    bias_note = {"bull": "多头锁定：一切回落视为【回踩 (Mitigation)】，只找做多，不做空。",
                 "bear": "空头锁定：一切反弹视为【诱多回撤】，只找做空，不抄底。",
                 "none": "日线无明确结构锁定，保持观望，等新的 BOS/CHoCH 印出方向。"}[lock]

    # ── actionable checklist (✓/✗ in the UI) ─────────────────────
    side_cn = "做空" if lock == "bear" else "做多"
    zone_label = "溢价区(≥50%)" if lock == "bear" else "折价区(≤50%)"
    dir_cn = "向下" if lock == "bear" else "向上"
    dot_cn = "红点" if lock == "bear" else "绿点"
    relay_detail = (f"{nearest_relay['tf']} {'供给' if want_ob == 'supply' else '需求'}区 "
                    f"${nearest_relay['low']}–${nearest_relay['high']}"
                    if nearest_relay else "暂无次级别中继区")
    wt = ltf15.get("wt") if ltf15 else None
    le15 = ltf15.get("last_event") if ltf15 else None
    checklist = [
        {"key": "lock", "label": "① 日线方向锁定", "ok": lock != "none", "detail": lock_reason},
        {"key": "pullback", "label": f"② 价格回到{zone_label}", "ok": bool(in_zone),
         "detail": f"当前区间位置 {pos * 100:.0f}%（均衡线 ${eq}）"},
        {"key": "relay", "label": "③ 触及次级别中继订单块 (4h/1h)", "ok": bool(touching_relay),
         "detail": relay_detail},
        {"key": "choch15", "label": f"④ 15m 出现{dir_cn} CHoCH", "ok": bool(ltf15 and ltf15["choch_ok"]),
         "detail": (f"15m {dir_cn} CHoCH 已现（{ltf15['choch_bars']} 根前）"
                    if (ltf15 and ltf15["choch_ok"])
                    else (f"近12根无{dir_cn} CHoCH（最近 {le15['dir']} {le15['kind']}，{ltf15['bars_since_event']} 根前）"
                          if le15 else ("无 15m 数据" if not ltf15 else "15m 暂无反转结构")))},
        {"key": "vmc", "label": f"⑤ 15m VMC {dot_cn}（收盘确认）", "ok": bool(ltf15 and ltf15["dot_ok"]),
         "detail": (f"VMC {dot_cn}已现（{ltf15['dot_bars']} 根前）· wt2={wt['wt2']}（{wt['zone']}）"
                    if (ltf15 and ltf15["dot_ok"] and wt)
                    else (f"近12根无{dot_cn} · wt1={wt['wt1']}/wt2={wt['wt2']}（{wt['zone']}）"
                          if wt else ("无 15m 数据" if not ltf15 else "WaveTrend 未就绪")))},
    ]
    n_ok = sum(1 for c in checklist if c["ok"])

    return {
        "lock": lock, "lock_reason": lock_reason, "bias_note": bias_note,
        "state": state, "state_cn": state_cn, "action": action,
        "side_cn": side_cn,
        "equilibrium": eq, "discount_premium": ("discount" if pos < 0.5 else "premium"),
        "range_position": round(pos, 3),
        "entry_zone": entry_zone, "stop": stop, "tp1": tp1, "tp2": tp2, "rr": rr,
        "rr_veto": rr_veto, "risk_note": risk_note,
        "relay_ob": nearest_relay, "relay_obs": relay[:3],
        "ltf15": ltf15,
        "checklist": checklist, "conditions_met": f"{n_ok}/5",
    }


# ── lower-timeframe structure (multi-timeframe confluence) ───────────────────

def analyze_ltf_structure(df_h: pd.DataFrame, bars: int = 240, k: int = 3) -> dict | None:
    """1h structure read — reuses the daily swing/structure machinery.

    Used ONLY for entry timing (HTF defines bias, LTF confirms the trigger). It
    is deliberately NOT folded into the daily composite score: multiple
    timeframes of the same price series are not independent evidence, so adding
    them would double-count and inflate conviction.
    """
    if df_h is None or len(df_h) < 2 * k + 5:
        return None
    d = df_h.tail(bars)
    sh, sl = find_swings(d, k=k)
    st = analyze_structure(d, sh, sl)
    return {"trend": st["trend"], "last_event": st["last_event"]}


# ── composite ────────────────────────────────────────────────────────────────

def analyze_smc(df: pd.DataFrame, live_price: float | None = None,
                df_h: pd.DataFrame | None = None,
                df_15m: pd.DataFrame | None = None) -> dict:
    """Full SMC read on the last ~120 daily bars (+ optional 1h confluence
    + optional 4h/1h/15m playbook when intraday frames are supplied)."""
    d = df.tail(120).reset_index().rename(columns=str.lower)
    d = d.set_index(d.columns[0]) if d.columns[0] != "open" else d
    d.index = pd.DatetimeIndex(df.tail(120).index)

    price = float(live_price if live_price else df["close"].iloc[-1])

    swing_highs, swing_lows = find_swings(d)
    structure = analyze_structure(d, swing_highs, swing_lows)
    fvgs      = find_fvgs(d)
    obs       = find_order_blocks(d, structure["recent_events"])
    sweeps    = find_sweeps(d, swing_highs, swing_lows)

    # premium / discount within the DEALING RANGE anchored to the swing that
    # printed the last structure label (not the global hi/lo — that inflates 0.5).
    rng_hi, rng_lo = _dealing_range(d, swing_highs, swing_lows, structure["last_event"], price)
    pos = (price - rng_lo) / (rng_hi - rng_lo) if rng_hi > rng_lo else 0.5
    pos = max(0.0, min(1.0, pos))
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

    # multi-timeframe confluence (1h vs daily) — context only, not scored
    ltf = analyze_ltf_structure(df_h)
    confluence = "neutral"
    if ltf and ltf["trend"] != "neutral" and structure["trend"] != "neutral":
        confluence = "aligned" if ltf["trend"] == structure["trend"] else "conflict"

    # ── disciplined trend-following playbook (lock → relay → 15m → FVG) ──
    df_4h = resample_ohlc(df_h, "4h") if df_h is not None else None
    try:
        playbook = build_playbook(price, structure, pos, rng_hi, rng_lo,
                                  fvgs, obs, df_4h, df_h, df_15m)
    except Exception as e:  # never let the playbook break the base SMC read
        playbook = {"lock": "none", "state": "NO_LOCK",
                    "state_cn": f"playbook 计算失败: {str(e)[:60]}", "checklist": []}

    return {
        "signal": signal,
        "label":  label,
        "score":  score,
        "trend":  structure["trend"],
        "last_event": structure["last_event"],
        "ltf":        ltf,
        "confluence": confluence,
        "zone":   zone,
        "range_position": round(pos, 3),
        "range": {"high": round(rng_hi, 2), "low": round(rng_lo, 2)},
        "demand_zones": demand,
        "supply_zones": supply,
        "sweeps": sweeps,
        "rationale": "；".join(notes) if notes else "结构中性，无显著 SMC 信号",
        "price_used": round(price, 2),
        "playbook": playbook,
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from data.fetcher import load_or_fetch, load_15m
    df_h, df_d = load_or_fetch()
    df_15m = load_15m()
    import json
    print(json.dumps(analyze_smc(df_d, df_h=df_h, df_15m=df_15m),
                     ensure_ascii=False, indent=2, default=str))
