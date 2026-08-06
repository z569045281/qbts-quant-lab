"""
Smart Money Concepts (SMC) structural analysis on QBTS daily bars.

Quantifies the ICT/SMC playbook into deterministic, explainable components:

  swings            fractal swing highs/lows (k bars each side)
  structure         trend from HH/HL vs LH/LL + last BOS / CHoCH event
  FVG               fair value gaps (3-candle imbalance), unmitigated only
  order blocks      last opposite candle before a structure-breaking impulse
  liquidity sweep   wick through a prior swing extreme that closes back inside
  premium/discount  position of price within the dominant swing range

结构引擎 = 本模块自己的 `analyze_structure`(对称 fractal swing + 逐 bar 破位)。
2026-07-29 曾整体换成 LuxAlgo Pine 源码的忠实移植,2026-08-06 用户点单**整套撤回**:
`lux_smc.py`、原版面板 `smc['lux']`、swing(50)/背离那几个派生字段一并删除。

**为什么撤回 —— 这是灵敏度取舍,不是"修 bug"**:本实现遍历**所有**未被破的历史
摆动高点,破掉其中任意一个就翻多;LuxAlgo 只认「当前那一个」pivot,那个点往往远
在天上(07-29 时是 $24.73),所以它几乎不开口。用户明确要前者:「之前的 smc,在
16 块涨到 17 块的时候就说已经从空转多了,很灵敏,我想要那个版本」。

逐日回放坐实(每天只用截至当天的数据):07-24 $16.21 → 07-27 $19.51 那波,
**只有本引擎(k=2)翻多**,k=8 与 LuxAlgo 从 6 月底一路 bearish 到 08-05 一次没翻。
上一版把这个性质定性成缺陷(见 git ef53ffa),那是**单方面**的 —— 它同时也是用户
唯一想要的那个功能。两种定性都对,取决于你要早开口还是要少犯错。

⚠️ 灵敏是**单向**的:翻多快、翻回空慢。翻空要收盘跌破一个未被破的摆动**低点**,
而一波反弹会把近期低点抬高 —— 07-29 价格跌回 $16.18(低于触发翻多的位置)时,
锁仍然是 bullish。用它做「早发现转多」可以,别拿它当「已经转空了」的凭据。

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


# `find_swings` 的对称 fractal 敏感度。它同时决定**趋势方向**(analyze_structure
# 拿这些摆动点做破位判定)和 sweeps / dealing range / order block 的粒度。
#
# 变更轨迹(全部记在 epoch 里):
#   ① 2026-07-29 k 由 2 → 8:压住"下跌途中破一个陈旧小高点就翻多"的症状
#   ② 2026-07-29 换 LuxAlgo 引擎(k 随之退出方向锁)
#   ③ 2026-08-04 用户点单 k 回 2
#   ④ 2026-08-06 用户点单**撤回整套 LuxAlgo**,回到 analyze_structure,k 保持 2
#      → k 重新进入方向锁。k 越小摆动点越密 ⇒ 可破的旧高点越多 ⇒ 翻多越早,
#        这正是用户要的灵敏度(见模块顶部)。想更钝就调大 k,别再换引擎。
#
# ⚠️ SMC playbook 驱动 ntfy TRIGGER 且是 8/15 受审信号,`smc.epoch` 随快照带出,
# 审判按代际分组统计,别把几代混在一起算胜率。
_DAILY_SWING_K = 2
# 口径代际标签(8/15 审判按它分组)。
# 08-06 又分一代:结构引擎从 LuxAlgo 移植撤回本模块自己的 analyze_structure。
# 方向锁的判定规则整个换了(实测当天 bearish → bullish),与 k2-rangefix-20260805
# 那一代的记录**不可比**,绝不能放同一个池子算胜率。
SMC_EPOCH = "legacy-k2-20260806"

# LTF(1h/15m)不动:日内本来就该用短摆动,而且它们不驱动方向锁。


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

    每个摆动点只能被"消费"一次(broken_high_i/broken_low_i),但**所有**未被破的
    历史摆动点都参与判定 —— 这就是它比 LuxAlgo 灵敏的原因,见模块顶部说明。
    """
    closes = df["close"].values
    n = len(df)
    trend = 0                  # +1 bullish / -1 bearish / 0 unknown

    events: list[dict] = []
    hi_q = list(swing_highs)
    lo_q = list(swing_lows)

    broken_high_i: set[int] = set()
    broken_low_i:  set[int] = set()
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

    return {
        "trend": "bullish" if trend > 0 else ("bearish" if trend < 0 else "neutral"),
        "last_event": events[-1] if events else None,
        "recent_events": events[-40:],   # 窗口够 15m CHoCH 回看;find_order_blocks 全扫
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
    For each structure break, the last opposite-direction candle before the
    breaking move = order block. Unmitigated = price hasn't closed through it.

    2026-07-13 修:原来只看最近 4 次结构事件 —— 单边下跌里事件全是向下 BOS,
    需求侧 OB 被整个滚出窗口(5 月突破 OB $18-19 一直未回补,TradingView/LuxAlgo
    还记得,我们忘了)。改成扫全部传入事件:未回补的 OB 不论新旧都保留,与 FVG
    同等待遇;时效筛选交给展示层(最近 2 个/侧)与 playbook 的区域相交逻辑。
    """
    out = []
    o, c, h, l = df["open"].values, df["close"].values, df["high"].values, df["low"].values
    n = len(df)
    for ev in structure_events:
        i = ev["i"]
        if ev["dir"] == "bullish":
            # last bearish candle before i
            for j in range(i - 1, max(0, i - 10), -1):
                if c[j] < o[j]:
                    zone_lo, zone_hi = float(l[j]), float(max(o[j], c[j]))
                    if not any(c[k2] < zone_lo for k2 in range(i, n)):
                        zone = {"type": "demand", "low": round(zone_lo, 2),
                                "high": round(zone_hi, 2),
                                "date": df.index[j].strftime("%m-%d")}
                        # 同一段行情里两个结构事件(如 CHoCH+BOS)常回溯到同一根蜡烛
                        # → 同一 OB 原样出现两次;去重
                        if zone not in out:
                            out.append(zone)
                    break
        else:
            for j in range(i - 1, max(0, i - 10), -1):
                if c[j] > o[j]:
                    zone_lo, zone_hi = float(min(o[j], c[j])), float(h[j])
                    if not any(c[k2] > zone_hi for k2 in range(i, n)):
                        zone = {"type": "supply", "low": round(zone_lo, 2),
                                "high": round(zone_hi, 2),
                                "date": df.index[j].strftime("%m-%d")}
                        if zone not in out:   # 同上:两个事件共享同一根 OB 蜡烛 → 去重
                            out.append(zone)
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
        ev_date = df.index[i].strftime("%m-%d")
        for s in swing_lows:
            if s["i"] < i - 1 and l[i] < s["price"] and c[i] > s["price"]:
                # note 里显式带上"扫单当天"日期(ev_date),不能只写被扫旧低/高点的日期
                # (s['date'] 可能是几个月前)——2026-07-22 AI 自检把旧低/高点误读成
                # "近期事件"就是栽在这句只字面写着旧日期上,补一句消歧义。
                out.append({"dir": "bullish", "level": round(s["price"], 2),
                            "date": ev_date,
                            "note": f"{ev_date} 扫过 {s['date']} 低点 ${s['price']:.2f} 后收回 — 空头流动性被收割"})
                break
        for s in swing_highs:
            if s["i"] < i - 1 and h[i] > s["price"] and c[i] < s["price"]:
                out.append({"dir": "bearish", "level": round(s["price"], 2),
                            "date": ev_date,
                            "note": f"{ev_date} 扫过 {s['date']} 高点 ${s['price']:.2f} 后回落 — 多头流动性被收割"})
                break
    # 价格在同一被扫价位附近连续多日反复插针时,每根 bar 都会重报同一事件
    # (实例:24.04 三天报三次)。同 (方向,价位) 只保留最新一次。
    dedup: dict[tuple, dict] = {}
    for sw in out:
        dedup[(sw["dir"], sw["level"])] = sw   # 后面的 bar 覆盖前面 → 留最新
    return list(dedup.values())[-3:]


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
    st = analyze_structure(d, sh, sl)         # 与日线同一套引擎
    obs = find_order_blocks(d, st["recent_events"])
    fvgs = find_fvgs(d, lookback=min(120, len(d)))
    return obs, fvgs


def _ltf15_trigger(df_15m: pd.DataFrame | None, lock: str) -> dict | None:
    """15m read for the final trigger: a fresh same-direction CHoCH.

    The close-confirmed WaveTrend (VMC) dot is still computed and returned
    (`dot_ok`/`dot_bars`) so the 8/15 audit can ask whether it added anything,
    but since 2026-08-04 it no longer gates TRIGGER and no longer shows on the
    checklist. Returns None when 15m data is absent."""
    if df_15m is None or len(df_15m) < 40:
        return None
    d15 = df_15m.tail(220)
    sh15, sl15 = find_swings(d15, k=2)
    st15 = analyze_structure(d15, sh15, sl15)  # 同上 —— 一个模块里不留两套结构引擎
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
                               touching a sub-TF OB ⇒ ARMED. Then a fresh 15m
                               same-direction CHoCH ⇒ TRIGGER (AND logic).
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
        # 2026-08-04 用户点单:纪律只保留 ①②③④,删掉 ⑤VMC 点 —— 扳机 = 15m
        # 同向 CHoCH,不再 AND 一个 WaveTrend 点。`dot_ok` 仍照算并随 ltf15 带出
        # (审判时还想看它到底有没有加分),但**不再有否决权**。
        # ⚠️ 少一道 AND = TRIGGER 会变多 = ntfy 推送会变多,这是预期内的。
        triggered = bool(armed and ltf15 and ltf15["choch_ok"])
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
    relay_detail = (f"{nearest_relay['tf']} {'供给' if want_ob == 'supply' else '需求'}区 "
                    f"${nearest_relay['low']}–${nearest_relay['high']}"
                    if nearest_relay else "暂无次级别中继区")
    le15 = ltf15.get("last_event") if ltf15 else None
    # 清单 = 纪律本身(AND 全 ✓ 才进场),所以它必须和状态机逐条对齐。
    # 2026-08-04 起只有 ①②③④ —— 原 ⑤「15m VMC 点」按用户点单删除,状态机那边
    # 也同步松了 AND(见上)。别只删显示不删闸门:那会出现「4/4 全绿却还是预警」。
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
        "checklist": checklist, "conditions_met": f"{n_ok}/{len(checklist)}",
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

    swing_highs, swing_lows = find_swings(d, k=_DAILY_SWING_K)

    # 结构、sweeps、dealing range、order block 全部在同一个 tail(120) 坐标系 `d`
    # 上算 —— 2026-08-06 撤回 LuxAlgo 后不再有"全量 df 上跑、事件下标要平移回来"
    # 这回事,08-05 那个 `_off` 平移 bug(坏了 7 天的区间位置/均衡线/tp2)也随之
    # 在结构上不可能再发生:没有第二个坐标系了。
    structure = analyze_structure(d, swing_highs, swing_lows)

    fvgs      = find_fvgs(d)
    obs       = find_order_blocks(d, structure["recent_events"])
    sweeps    = find_sweeps(d, swing_highs, swing_lows)

    # premium / discount within the DEALING RANGE anchored to the swing that
    # printed the last structure label (not the global hi/lo — that inflates 0.5).
    #
    # `last_event["i"]` 与 `_dealing_range` 索引的 d 同坐标系,直接传即可。
    rng_hi, rng_lo = _dealing_range(d, swing_highs, swing_lows,
                                    structure["last_event"], price)
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
        "epoch":  SMC_EPOCH,      # 口径代际 —— 8/15 审判按它分组,别把两代混算胜率
        "swing_k": _DAILY_SWING_K,
        "trend":  structure["trend"],          # 方向锁用它
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

    # ── 回归守卫:dealing range 的坐标系(2026-07-29 串过一次,坏了 7 天)──
    # 不变量:区间必须真的**框住**破位以来的行情。坐标系一串,下沿会退化成全期
    # 最低、上沿会取到破位之后的高点,于是区间位置钉在 100%、tp2 钉在全期最低。
    _s = analyze_smc(df_d, df_h=df_h)
    _pb, _px = _s["playbook"], float(df_d["close"].iloc[-1])
    _lo, _hi = _s["range"]["low"], _s["range"]["high"]
    assert _lo < _hi, f"区间退化 {_lo}/{_hi}"
    assert _lo >= float(df_d["low"].tail(120).min()), \
        f"下沿 ${_lo} 跌到全期最低 —— 坐标系又串了(应是破位后的低点)"
    assert _hi >= _px or _pb["range_position"] < 1.0, \
        f"上沿 ${_hi} < 现价 ${_px} 却报 100% —— 区间没框住行情"
    print(f"✅ dealing range 守卫通过:${_lo}–${_hi} 位置 {_pb['range_position']*100:.0f}%")

    import json
    print(json.dumps(analyze_smc(df_d, df_h=df_h, df_15m=df_15m),
                     ensure_ascii=False, indent=2, default=str))
