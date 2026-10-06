"""🌊 浪潮状态 —— QBTS 一波一波的,现在在浪的哪个位置(2026-10-06 用户点单)。

用户原话:「QBTS 像海浪,一波一波的,来的时候很猛烈,然后拍到沙滩上开始回调,
帮我在仪表盘上做一个这样的状态栏」。

切浪的办法:收盘价 zigzag,反向走 20% 才算转折(QBTS 年化波动 ~70%,20% 才过滤得掉日常噪声)。
2022-09 起的实测(2026-10-06):
  上涨浪 34 个,幅度中位 +60%(25–75%:+36%~+91%),只用 8 个交易日 —— 来得又快又猛
  回落浪 34 个,幅度中位 −34%(25–75%:−44%~−26%),花 12 个交易日 —— 退得慢

⚠️ **这是地图,不是买卖信号。** 同日回测:浪走到哪一步(回落了多深 / 涨了多少)对之后
10/20 日涨跌**没有稳定的预测力** —— 分档不单调,前后两半样本结论相反(回落 ≥35% 之后
20 日:前半均值 −15.8%,后半 +31.2%)。高抛低吸在 mining.md 已两次判死
(记忆 qbts-range-trading-no-edge、「折价买/溢价卖」),本模块不进决策 prompt、不进推送。

状态是**因果**的:只用当天及以前的收盘价。当前这一浪在反向走满 20% 之前都不会被判结束,
所以「转折确认线」= 本浪极值 ×(1 ± 20%),前端按实时价判断有没有越线。
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TH = 0.20          # 反向走 20% 才算一浪结束
_KEEP_PIVOTS = 8   # 前端只显示最近几个转折点


def _walk(close: pd.Series) -> tuple[list[dict], dict]:
    """逐日走一遍,返回已确认的转折点 + 当前这一浪的状态(全部因果)。"""
    c = close.values
    idx = close.index
    pivots: list[dict] = []
    trend = 0                      # 1 上涨浪 / −1 回落浪 / 0 还没走出第一浪
    anchor_i = 0                   # 这一浪的起点(上一个已确认的转折点)
    ext_i = 0                      # 这一浪到目前为止的极值
    for i in range(1, len(c)):
        p = c[i]
        if trend >= 0 and p > c[ext_i]:
            ext_i = i
        elif trend == -1 and p < c[ext_i]:
            ext_i = i
        if trend == 0:
            if p >= c[anchor_i] * (1 + TH):
                trend, ext_i = 1, i
            elif p <= c[anchor_i] * (1 - TH):
                trend, ext_i = -1, i
            continue
        if trend == 1 and p <= c[ext_i] * (1 - TH):          # 浪尖确认:从最高点回落 20%
            pivots.append({"i": ext_i, "kind": "peak"})
            trend, anchor_i, ext_i = -1, ext_i, i
        elif trend == -1 and p >= c[ext_i] * (1 + TH):       # 浪底确认:从最低点反弹 20%
            pivots.append({"i": ext_i, "kind": "trough"})
            trend, anchor_i, ext_i = 1, ext_i, i
    for pv in pivots:
        pv["date"] = str(pd.Timestamp(idx[pv["i"]]).date())
        pv["price"] = round(float(c[pv["i"]]), 2)
    cur = {
        "trend": {1: "up", -1: "down"}.get(trend, "none"),
        "anchor_price": round(float(c[anchor_i]), 2),
        "anchor_date": str(pd.Timestamp(idx[anchor_i]).date()),
        "extreme_price": round(float(c[ext_i]), 2),
        "extreme_date": str(pd.Timestamp(idx[ext_i]).date()),
        "days": int(len(c) - 1 - anchor_i),
        "close": round(float(c[-1]), 2),
        "close_date": str(pd.Timestamp(idx[-1]).date()),
    }
    return pivots, cur


def _legs(pivots: list[dict]) -> dict:
    up, down = [], []
    for a, b in zip(pivots, pivots[1:]):
        mag = b["price"] / a["price"] - 1
        days = b["i"] - a["i"]
        (up if b["kind"] == "peak" else down).append((mag, days))

    def summary(legs):
        if not legs:
            return None
        mags = [m for m, _ in legs]
        days = [d for _, d in legs]
        return {
            "n": len(legs),
            "mag_median": round(float(np.median(mags)), 4),
            "mag_p25": round(float(np.percentile(mags, 25)), 4),
            "mag_p75": round(float(np.percentile(mags, 75)), 4),
            "days_median": int(np.median(days)),
            # 前端用来按实时价算分位,保留原始数组(几十个数,很小)
            "mags": sorted(round(float(m), 4) for m in mags),
            "days": sorted(int(d) for d in days),
        }
    return {"up": summary(up), "down": summary(down)}


# 🧪 第四十六轮的样本内冠军(2026-10-06 用户点单「把最佳组合的海浪放上去」)。
# **观察项,不是信号**:11,200 组里事后挑出来的,样本外第 2 年 −43%(排 10,241/11,200),
# 两年排名秩相关 −0.48。按铁律「判死的策略不复活」—— 只显示,不进决策 prompt、不推送。
BEST = {"th": 0.12, "tp": 1.00, "tmax": 20, "stop": 0.10}
BEST_STUDY = {   # 第四十六轮原始数字,写死(不随每天滚动改变)
    "window": "2024-10-07 → 2026-10-05", "ret": 46.89, "bh": 15.29,
    "oos_note": "用第 1 年挑出的冠军,第 2 年 −43%(排 10,241/11,200);两年排名负相关 −0.48",
}


def best_combo(close: pd.Series) -> dict:
    """按冠军规则逐日走(因果):12% 浪确认起浪当天收盘买;+100% 止盈 / −10% 止损 / 满 20 天卖。"""
    c, idx = close.values, close.index
    th, tp, tmax, stop = BEST["th"], BEST["tp"], BEST["tmax"], BEST["stop"]
    trend, a, e = 0, 0, 0
    pos, ent, ent_i = False, 0.0, 0
    trades = []
    for i in range(1, len(c)):
        p, flip_up = c[i], False
        if trend >= 0 and p > c[e]:
            e = i
        elif trend == -1 and p < c[e]:
            e = i
        if trend == 0:
            if p >= c[a] * (1 + th):
                trend, e, flip_up = 1, i, True
            elif p <= c[a] * (1 - th):
                trend, e = -1, i
        elif trend == 1 and p <= c[e] * (1 - th):
            trend, a, e = -1, e, i
        elif trend == -1 and p >= c[e] * (1 + th):
            trend, a, e, flip_up = 1, e, i, True
        if pos:
            held = i - ent_i
            why = ("止损" if p <= ent * (1 - stop) else "止盈" if p >= ent * (1 + tp)
                   else "到期" if held >= tmax else None)
            if why:
                trades.append({"buy_date": str(pd.Timestamp(idx[ent_i]).date()), "buy": round(float(ent), 2),
                               "sell_date": str(pd.Timestamp(idx[i]).date()), "sell": round(float(p), 2),
                               "ret": round(float(p / ent - 1), 4), "why": why})
                pos = False
        elif flip_up:
            pos, ent, ent_i = True, float(p), i
    state = {"in_position": pos, "wave_trend": {1: "up", -1: "down"}.get(trend, "none"),
             "wave_extreme": round(float(c[e]), 2), "wave_extreme_date": str(pd.Timestamp(idx[e]).date())}
    if pos:
        state.update({"entry": round(ent, 2), "entry_date": str(pd.Timestamp(idx[ent_i]).date()),
                      "held": int(len(c) - 1 - ent_i), "tp_price": round(ent * (1 + tp), 2),
                      "stop_price": round(ent * (1 - stop), 2), "days_left": int(tmax - (len(c) - 1 - ent_i))})
    elif trend == -1:
        state["trigger"] = round(float(c[e]) * (1 + th), 2)     # 收盘站上这里 = 12% 起浪确认 = 买入
    return {"params": BEST, "study": BEST_STUDY, "state": state, "trades": trades[-6:]}


def compute_wave(df_d: pd.DataFrame) -> dict | None:
    """日线 → 浪潮状态。失败返回 None(前端不显示这条状态栏)。"""
    try:
        close = df_d.rename(columns=str.lower)["close"].astype(float).dropna()
        if len(close) < 120:
            return None
        pivots, cur = _walk(close)
        out = {
            "threshold": TH,
            "current": cur,
            "pivots": [{k: v for k, v in p.items() if k != "i"} for p in pivots[-_KEEP_PIVOTS:]],
            "legs": _legs(pivots),
            "since": str(pd.Timestamp(close.index[0]).date()),
            "note": ("地图,不是买卖信号:历史回测里,浪走到哪一步对之后 10/20 天的涨跌"
                     "没有稳定的预测力(前后两半样本结论相反)。高抛低吸已判死。"),
        }
        try:
            out["best"] = best_combo(close)
        except Exception as e:
            logger.warning(f"wave best_combo failed: {e}")
        return out
    except Exception as e:
        logger.warning(f"wave compute failed: {e}")
        return None


if __name__ == "__main__":
    import json
    import yfinance as yf
    d = yf.download("QBTS", start="2022-09-01", progress=False, auto_adjust=False)
    d.columns = [c[0].lower() for c in d.columns]
    w = compute_wave(d)
    print(json.dumps({k: v for k, v in w.items() if k != "legs"}, ensure_ascii=False, indent=1))
    for k in ("up", "down"):
        s = w["legs"][k]
        print(k, {x: s[x] for x in ("n", "mag_median", "mag_p25", "mag_p75", "days_median")})
