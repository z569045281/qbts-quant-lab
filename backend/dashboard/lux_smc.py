"""
LuxAlgo「Smart Money Concepts」(Pine v5) 的**忠实移植** —— 单遍逐 bar 复刻。

源码在仓库根目录 `SMC.docx`(CC BY-NC-SA 4.0 © LuxAlgo)。这个模块把整张指标
搬过来,不只是结构那一段:

    internal / swing 结构   BOS · CHoCH · 当前未破 pivot(两级同时跑,互相耦合)
    trailing extremes       Strong/Weak High · Strong/Weak Low(图上那两根横线)
    premium / discount      **从 trailing extremes 算**,不是全局 hi/lo
    order blocks            parsedHigh/Low + 高波动 bar 反转 + 极值定位 + 回补消除
    fair value gaps         LuxAlgo 的自适应阈值口径 + 它自己的(不对称的)回补规则
    EQH / EQL               等高等低
    MTF levels              PDH/PDL · PWH/PWL · PMH/PML

为什么要整块搬:2026-07-29 之前我们只有"看起来像 SMC"的自制实现,和用户
TradingView 上看到的指标逐项都不一样(结构那一段当天已经换过一次,见
`smc.py::lux_structure` 的历史注释)。仪表盘要和用户眼前的图说同一种话,
就不能各写各的。

┌ 与 Pine 的已知差异(全部是刻意的,别当 bug 修) ────────────────────────┐
│ ① Pine 的 `for [i, x] in arr` 里 `arr.remove(i)` 会跳元素(Pine 的老坑)。  │
│    这里改成一次性过滤 —— 只有"同一根 bar 上有两个区同时被回补"时才有   │
│    差别,那种情况原版会漏删一个,我们不漏。                              │
│ ② 画图相关的一切(box/line/label/颜色/plotcandle)不移植,只留数值。      │
│ ③ 默认打开了原版默认关闭的开关(swing OB / FVG / premium-discount /      │
│    MTF levels),因为我们要的是读数不是图面。                             │
└──────────────────────────────────────────────────────────────────────┘

⚠️ **原版 FVG 的回补规则是不对称的,这里照抄了**:看涨 FVG 要价格**完全穿透**
才消除,看跌 FVG **一碰近端就消除**(源码 `fairValueGap.new(currentHigh,
last2Low, BEARISH)` 把 top 存成了数值更低的那条边,而删除条件用 `high > top`)。
后果是看跌 FVG 的存活率被系统性压低。这是原指标的行为,用户图上看到的就是它;
要改得先决定"我们到底要不要和图一致",别偷偷修。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BULLISH = +1
BEARISH = -1

_BULLISH_LEG = 1
_BEARISH_LEG = 0

# LuxAlgo 默认输入(名字保持和 Pine 一致,方便对照源码)
SWINGS_LENGTH = 50            # swingsLengthInput
INTERNAL_LENGTH = 5           # getCurrentStructure(5, false, true) —— 源码硬编码
EQUAL_LENGTH = 3              # equalHighsLowsLengthInput
EQUAL_THRESHOLD = 0.1         # equalHighsLowsThresholdInput
ATR_LENGTH = 200              # ta.atr(200)
INTERNAL_OB_SHOWN = 5         # internalOrderBlocksSizeInput
SWING_OB_SHOWN = 5            # swingOrderBlocksSizeInput


# ── Pine 内建函数的等价实现 ──────────────────────────────────────────────

def _true_range(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    """ta.tr(true) —— 第一根用 high-low(handle_na)。"""
    tr = np.empty(len(h))
    tr[0] = h[0] - l[0]
    if len(h) > 1:
        prev = c[:-1]
        tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - prev), np.abs(l[1:] - prev)])
    return tr


def _rma(x: np.ndarray, length: int) -> np.ndarray:
    """ta.rma —— 前 length-1 根为 na,第 length 根用 SMA 起播,之后 Wilder 平滑。"""
    out = np.full(len(x), np.nan)
    if len(x) < length:
        return out
    out[length - 1] = x[:length].mean()
    for i in range(length, len(x)):
        out[i] = (out[i - 1] * (length - 1) + x[i]) / length
    return out


class _Pivot:
    """Pine 的 `type pivot`。`level_prev` 是我们额外维护的"上一根 bar 结束时的值"
    —— Pine 的 `ta.crossover(close, p.currentLevel)` 比的是 `currentLevel[1]`,
    不是当前值;不存这一份就会在"pivot 刚更新的那根 bar"上判错穿越。"""

    __slots__ = ("current_level", "last_level", "crossed", "bar_index", "level_prev")

    def __init__(self) -> None:
        self.current_level: float | None = None
        self.last_level: float | None = None
        self.crossed: bool = False
        self.bar_index: int | None = None
        self.level_prev: float | None = None


class _Trend:
    __slots__ = ("bias",)

    def __init__(self) -> None:
        self.bias = 0


# ── 主引擎 ────────────────────────────────────────────────────────────────

def run_lux(df: pd.DataFrame,
            swings_length: int = SWINGS_LENGTH,
            internal_length: int = INTERNAL_LENGTH,
            equal_length: int = EQUAL_LENGTH,
            equal_threshold: float = EQUAL_THRESHOLD,
            atr_length: int = ATR_LENGTH,
            ob_mitigation: str = "High/Low",
            fvg_auto_threshold: bool = True,
            events_kept: int = 40) -> dict:
    """把整张指标跑一遍,返回它"画出来的所有东西"的数值形式。

    df 需要 open/high/low/close 列(小写)与 DatetimeIndex。
    """
    d = df.rename(columns=str.lower)
    o = d["open"].astype(float).values
    h = d["high"].astype(float).values
    l = d["low"].astype(float).values
    c = d["close"].astype(float).values
    idx = d.index
    n = len(d)
    if n == 0:
        return _empty_result()

    def _date(i: int) -> str:
        ts = idx[i]
        return ts.strftime("%m-%d") if hasattr(ts, "strftime") else str(ts)

    atr = _rma(_true_range(h, l, c), atr_length)

    # parsedHigh/parsedLow:高波动 bar(振幅 ≥ 2×ATR)把高低**对调**,
    # 免得一根长针把订单块拉成一整条巨柱(源码 highVolatilityBar)。
    hv = np.zeros(n, dtype=bool)
    valid = ~np.isnan(atr)
    hv[valid] = (h[valid] - l[valid]) >= (2 * atr[valid])
    parsed_high = np.where(hv, l, h)
    parsed_low = np.where(hv, h, l)

    swing_high, swing_low = _Pivot(), _Pivot()
    internal_high, internal_low = _Pivot(), _Pivot()
    equal_high, equal_low = _Pivot(), _Pivot()
    swing_trend, internal_trend = _Trend(), _Trend()
    # 三个 getCurrentStructure 调用点各有一份自己的 `var leg`
    legs = {"swing": _BEARISH_LEG, "internal": _BEARISH_LEG, "equal": _BEARISH_LEG}

    trailing = {"top": None, "bottom": None, "bar_index": None,
                "last_top_i": None, "last_bottom_i": None}

    internal_obs: list[dict] = []
    swing_obs: list[dict] = []
    fvgs: list[dict] = []
    internal_events: list[dict] = []
    swing_events: list[dict] = []
    eq_events: list[dict] = []
    swing_points: list[dict] = []
    alerts: dict[str, bool] = {}
    cum_abs_delta = 0.0

    bear_ob_src = c if ob_mitigation == "Close" else h
    bull_ob_src = c if ob_mitigation == "Close" else l

    # ── getCurrentStructure ────────────────────────────────────────
    def _current_structure(i: int, size: int, equal_hl: bool = False,
                           internal: bool = False) -> None:
        key = "equal" if equal_hl else ("internal" if internal else "swing")
        if i < size:
            return
        win_hi = h[i - size + 1:i + 1].max()      # ta.highest(size)
        win_lo = l[i - size + 1:i + 1].min()      # ta.lowest(size)
        new_leg = legs[key]
        if h[i - size] > win_hi:
            new_leg = _BEARISH_LEG                # → pivot HIGH 落定
        elif l[i - size] < win_lo:
            new_leg = _BULLISH_LEG                # → pivot LOW 落定
        if new_leg == legs[key]:
            return                                # ta.change(leg) == 0
        legs[key] = new_leg

        pi = i - size
        if new_leg == _BULLISH_LEG:               # pivot low
            p = equal_low if equal_hl else (internal_low if internal else swing_low)
            if (equal_hl and p.current_level is not None and not np.isnan(atr[i])
                    and abs(p.current_level - l[pi]) < equal_threshold * atr[i]):
                eq_events.append({"kind": "EQL", "level": round(float(l[pi]), 2),
                                  "prev_level": round(float(p.current_level), 2),
                                  "from_date": _date(p.bar_index) if p.bar_index is not None else None,
                                  "date": _date(pi), "i": pi})
            p.last_level, p.current_level = p.current_level, float(l[pi])
            p.crossed, p.bar_index = False, pi
            if not equal_hl and not internal:
                trailing["bottom"] = p.current_level
                trailing["bar_index"] = pi
                trailing["last_bottom_i"] = pi
                swing_points.append({
                    "tag": "LL" if (p.last_level is not None and p.current_level < p.last_level) else "HL",
                    "price": round(p.current_level, 2), "date": _date(pi), "i": pi})
        else:                                     # pivot high
            p = equal_high if equal_hl else (internal_high if internal else swing_high)
            if (equal_hl and p.current_level is not None and not np.isnan(atr[i])
                    and abs(p.current_level - h[pi]) < equal_threshold * atr[i]):
                eq_events.append({"kind": "EQH", "level": round(float(h[pi]), 2),
                                  "prev_level": round(float(p.current_level), 2),
                                  "from_date": _date(p.bar_index) if p.bar_index is not None else None,
                                  "date": _date(pi), "i": pi})
            p.last_level, p.current_level = p.current_level, float(h[pi])
            p.crossed, p.bar_index = False, pi
            if not equal_hl and not internal:
                trailing["top"] = p.current_level
                trailing["bar_index"] = pi
                trailing["last_top_i"] = pi
                swing_points.append({
                    "tag": "HH" if (p.last_level is not None and p.current_level > p.last_level) else "LH",
                    "price": round(p.current_level, 2), "date": _date(pi), "i": pi})

    # ── storeOrdeBlock ─────────────────────────────────────────────
    def _store_ob(i: int, p: _Pivot, internal: bool, bias: int) -> None:
        if p.bar_index is None or i <= p.bar_index:
            return
        lo, hi = p.bar_index, i                   # Pine: slice(barIndex, bar_index) 不含当根
        if bias == BEARISH:
            seg = parsed_high[lo:hi]
            k = int(np.argmax(seg))               # array.indexof(max) = 第一个极值
        else:
            seg = parsed_low[lo:hi]
            k = int(np.argmin(seg))
        j = lo + k
        arr = internal_obs if internal else swing_obs
        if len(arr) >= 100:
            arr.pop()
        arr.insert(0, {"bias": bias, "high": float(parsed_high[j]), "low": float(parsed_low[j]),
                       "i": j, "date": _date(j), "break_date": _date(i),
                       # 下面两个只给校验/回放用,面板不外发
                       "pivot_i": lo, "break_i": hi})

    # ── displayStructure ───────────────────────────────────────────
    def _display_structure(i: int, internal: bool) -> None:
        if i == 0:
            return
        t = internal_trend if internal else swing_trend
        events = internal_events if internal else swing_events

        p = internal_high if internal else swing_high
        # 源码:internal 的额外条件是"internal pivot 不能和 swing pivot 是同一个价"
        # (confluence filter 默认关,bullishBar/bearishBar 恒 true)
        extra = (internal_high.current_level != swing_high.current_level) if internal else True
        if (p.current_level is not None and p.level_prev is not None and not p.crossed
                and extra and c[i] > p.current_level and c[i - 1] <= p.level_prev):
            tag = "CHoCH" if t.bias == BEARISH else "BOS"
            events.append({"i": i, "date": _date(i), "kind": tag, "dir": "bullish",
                           "level": round(p.current_level, 2)})
            alerts[f"{'internal' if internal else 'swing'}Bullish{tag}"] = True
            p.crossed, t.bias = True, BULLISH
            _store_ob(i, p, internal, BULLISH)

        p = internal_low if internal else swing_low
        extra = (internal_low.current_level != swing_low.current_level) if internal else True
        if (p.current_level is not None and p.level_prev is not None and not p.crossed
                and extra and c[i] < p.current_level and c[i - 1] >= p.level_prev):
            tag = "CHoCH" if t.bias == BULLISH else "BOS"
            events.append({"i": i, "date": _date(i), "kind": tag, "dir": "bearish",
                           "level": round(p.current_level, 2)})
            alerts[f"{'internal' if internal else 'swing'}Bearish{tag}"] = True
            p.crossed, t.bias = True, BEARISH
            _store_ob(i, p, internal, BEARISH)

    # ── 逐 bar 执行(顺序照抄源码底部的 EXECUTION 段)──────────────
    for i in range(n):
        # updateTrailingExtremes:math.max(high, na) 在 Pine 里还是 na,
        # 所以第一个 swing pivot 落定之前 top/bottom 一直是空的 —— 照抄。
        if trailing["top"] is not None:
            if h[i] > trailing["top"]:
                trailing["top"] = float(h[i])
                trailing["last_top_i"] = i
            elif trailing["top"] == h[i]:
                trailing["last_top_i"] = i
        if trailing["bottom"] is not None:
            if l[i] < trailing["bottom"]:
                trailing["bottom"] = float(l[i])
                trailing["last_bottom_i"] = i
            elif trailing["bottom"] == l[i]:
                trailing["last_bottom_i"] = i

        # deleteFairValueGaps —— 在新建之前,用当根的 high/low 判回补
        if fvgs:
            fvgs[:] = [g for g in fvgs
                       if not ((l[i] < g["bottom"] and g["bias"] == BULLISH)
                               or (h[i] > g["top"] and g["bias"] == BEARISH))]

        _current_structure(i, swings_length, False, False)
        _current_structure(i, internal_length, False, True)
        _current_structure(i, equal_length, True, False)

        _display_structure(i, internal=True)
        _display_structure(i, internal=False)

        # deleteOrderBlocks(回补即消除;默认口径 High/Low)
        internal_obs[:] = [b for b in internal_obs
                           if not ((b["bias"] == BEARISH and bear_ob_src[i] > b["high"])
                                   or (b["bias"] == BULLISH and bull_ob_src[i] < b["low"]))]
        swing_obs[:] = [b for b in swing_obs
                        if not ((b["bias"] == BEARISH and bear_ob_src[i] > b["high"])
                                or (b["bias"] == BULLISH and bull_ob_src[i] < b["low"]))]

        # drawFairValueGaps —— 同周期口径(fairValueGapsTimeframeInput = '')
        if i >= 2:
            # 源码原样:除以 (lastOpen * 100)。这是 LuxAlgo 自己的量纲,阈值用的是
            # 同一个量纲的累计均值,比较仍然成立 —— 照抄,不"顺手修正"。
            bar_delta = (c[i - 1] - o[i - 1]) / (o[i - 1] * 100) if o[i - 1] else 0.0
            cum_abs_delta += abs(bar_delta)
            threshold = (cum_abs_delta / i * 2) if fvg_auto_threshold else 0.0
            if l[i] > h[i - 2] and c[i - 1] > h[i - 2] and bar_delta > threshold:
                fvgs.insert(0, {"bias": BULLISH, "top": float(l[i]), "bottom": float(h[i - 2]),
                                "i": i, "date": _date(i)})
                alerts["bullishFairValueGap"] = True
            if h[i] < l[i - 2] and c[i - 1] < l[i - 2] and -bar_delta > threshold:
                fvgs.insert(0, {"bias": BEARISH, "top": float(h[i]), "bottom": float(l[i - 2]),
                                "i": i, "date": _date(i)})
                alerts["bearishFairValueGap"] = True
        elif i >= 1:
            bar_delta = (c[i - 1] - o[i - 1]) / (o[i - 1] * 100) if o[i - 1] else 0.0
            cum_abs_delta += abs(bar_delta)

        # 每根结束时存一份 level,给下一根的 ta.crossover 当 `[1]` 用
        for p in (swing_high, swing_low, internal_high, internal_low, equal_high, equal_low):
            p.level_prev = p.current_level

        if i < n - 1:
            alerts.clear()                        # alerts 只反映最后一根

    # ── 输出 ───────────────────────────────────────────────────────
    price = float(c[-1])
    top, bottom = trailing["top"], trailing["bottom"]
    zones = None
    if top is not None and bottom is not None and top > bottom:
        zones = {
            "premium": [round(0.95 * top + 0.05 * bottom, 2), round(top, 2)],
            "equilibrium": [round(0.525 * bottom + 0.475 * top, 2),
                            round(0.525 * top + 0.475 * bottom, 2)],
            "discount": [round(bottom, 2), round(0.95 * bottom + 0.05 * top, 2)],
            "position": round(max(0.0, min(1.0, (price - bottom) / (top - bottom))), 3),
        }

    def _fmt_ob(b: dict) -> dict:
        return {"type": "demand" if b["bias"] == BULLISH else "supply",
                "low": round(b["low"], 2), "high": round(b["high"], 2),
                "date": b["date"], "break_date": b["break_date"], "i": b["i"],
                "pivot_i": b["pivot_i"], "break_i": b["break_i"]}

    def _fmt_fvg(g: dict) -> dict:
        lo, hi = sorted((g["top"], g["bottom"]))
        return {"type": "bullish" if g["bias"] == BULLISH else "bearish",
                "low": round(lo, 2), "high": round(hi, 2), "date": g["date"], "i": g["i"]}

    return {
        "internal": _structure_out(internal_trend, internal_high, internal_low,
                                   internal_events, events_kept),
        "swing": _structure_out(swing_trend, swing_high, swing_low,
                                swing_events, events_kept),
        "trailing": {
            "top": round(top, 2) if top is not None else None,
            "bottom": round(bottom, 2) if bottom is not None else None,
            "top_date": _date(trailing["last_top_i"]) if trailing["last_top_i"] is not None else None,
            "bottom_date": _date(trailing["last_bottom_i"]) if trailing["last_bottom_i"] is not None else None,
            # 源码:topLabel = swingTrend.bias == BEARISH ? 'Strong High' : 'Weak High'
            "top_label": "Strong High" if swing_trend.bias == BEARISH else "Weak High",
            "bottom_label": "Strong Low" if swing_trend.bias == BULLISH else "Weak Low",
        },
        "zones": zones,
        "internal_ob": [_fmt_ob(b) for b in internal_obs[:INTERNAL_OB_SHOWN]],
        "swing_ob": [_fmt_ob(b) for b in swing_obs[:SWING_OB_SHOWN]],
        "internal_ob_all": [_fmt_ob(b) for b in internal_obs],
        "swing_ob_all": [_fmt_ob(b) for b in swing_obs],
        "fvg": [_fmt_fvg(g) for g in fvgs],
        "equal_hl": eq_events[-6:],
        "swing_points": swing_points[-8:],
        "alerts": sorted(k for k, v in alerts.items() if v),
        "atr": round(float(atr[-1]), 3) if not np.isnan(atr[-1]) else None,
        "price": round(price, 2),
        "bars": n,
    }


def _structure_out(t: _Trend, ph: _Pivot, pl: _Pivot,
                   events: list[dict], keep: int) -> dict:
    return {
        "trend": "bullish" if t.bias == BULLISH else ("bearish" if t.bias == BEARISH else "neutral"),
        "last_event": events[-1] if events else None,
        "recent_events": events[-keep:],
        "pivot_high": round(ph.current_level, 2) if ph.current_level is not None else None,
        "pivot_low": round(pl.current_level, 2) if pl.current_level is not None else None,
        "pivot_high_crossed": ph.crossed,
        "pivot_low_crossed": pl.crossed,
    }


def _empty_result() -> dict:
    empty = {"trend": "neutral", "last_event": None, "recent_events": [],
             "pivot_high": None, "pivot_low": None,
             "pivot_high_crossed": True, "pivot_low_crossed": True}
    return {"internal": dict(empty), "swing": dict(empty),
            "trailing": {"top": None, "bottom": None, "top_date": None, "bottom_date": None,
                         "top_label": "Weak High", "bottom_label": "Weak Low"},
            "zones": None, "internal_ob": [], "swing_ob": [],
            "internal_ob_all": [], "swing_ob_all": [],
            "fvg": [], "equal_hl": [], "swing_points": [], "alerts": [],
            "atr": None, "price": None, "bars": 0}


# ── Highs & Lows MTF(源码 drawLevels)──────────────────────────────────

def mtf_levels(df_daily: pd.DataFrame) -> dict:
    """PDH/PDL · PWH/PWL · PMH/PML。

    源码 `drawLevels('D', timeframe.isdaily, …)`:图表周期 == 目标周期时走
    `sameTimeframe` 分支,用的是**当根**的 high/low。我们的图就是日线,所以
    PDH/PDL = 今天的高低,PWH/PWL、PMH/PML = **上一个已完结**周/月的高低
    (`request.security(…, [high[1], low[1]])`)。
    """
    d = df_daily.rename(columns=str.lower)
    if len(d) == 0:
        return {}
    out = {"PDH": round(float(d["high"].iloc[-1]), 2),
           "PDL": round(float(d["low"].iloc[-1]), 2),
           "PDH_date": d.index[-1].strftime("%m-%d")}
    for rule, tag in (("W", "PW"), ("ME", "PM")):
        try:
            g = d.resample(rule).agg({"high": "max", "low": "min"}).dropna()
            if len(g) >= 2:
                out[f"{tag}H"] = round(float(g["high"].iloc[-2]), 2)
                out[f"{tag}L"] = round(float(g["low"].iloc[-2]), 2)
        except Exception:
            pass
    return out


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from data.fetcher import load_or_fetch

    _, df_d = load_or_fetch()
    res = run_lux(df_d)
    res["mtf"] = mtf_levels(df_d)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
