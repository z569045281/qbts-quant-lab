"""
千元挑战「今日照做」篮子状态(/challenge/lessons 页的活部件)。

复刻本地挑战 bot 的进场纪律,对固定篮子 SOXL/FNGU/TQQQ/LABU 每日算一遍:
  上升趋势 = 收盘 > 50 日线 且 近 5 个交易日收益 > 0(bot 的两条硬门)
  今日之选 = 合格者中 20 日动量最强的一只(动量口径是对 bot「动量最强」的
             复刻近似 —— bot 源码在仓库外,以页面口径为准)
  照做参考价 = 现收盘 ×1.10 止盈 / ×0.88 止损(bot 的 bracket 比例)

纯读数,不下单、不进 edge、不进决策 prompt —— 只是把挑战赢下来的那套
纪律变成每天可以照做/照不做的检查表。没有合格标的时,空仓也是信号。
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

BASKET = ["SOXL", "FNGU", "TQQQ", "LABU"]
_TP_PCT = 0.10
_STOP_PCT = 0.12


def analyze_challenge_basket() -> dict | None:
    """篮子四只杠杆 ETF 的趋势门/动量排名/bracket 参考价;失败返回 None。"""
    try:
        import yfinance as yf
        raw = yf.download(" ".join(BASKET), period="6mo", interval="1d",
                          progress=False, auto_adjust=True, group_by="ticker")
        etfs = []
        for t in BASKET:
            try:
                c = raw[t]["Close"].dropna()
                if len(c) < 55:
                    etfs.append({"ticker": t, "error": "数据不足"})
                    continue
                close = float(c.iloc[-1])
                ma50 = float(c.rolling(50).mean().iloc[-1])
                week_ret = float(close / c.iloc[-6] - 1)
                mom20 = float(close / c.iloc[-21] - 1)
                uptrend = bool(close > ma50 and week_ret > 0)
                etfs.append({
                    "ticker": t,
                    "close": round(close, 2),
                    "ma50": round(ma50, 2),
                    "above_50dma": bool(close > ma50),
                    "week_ret": round(week_ret, 4),
                    "mom20": round(mom20, 4),
                    "uptrend": uptrend,
                    "tp": round(close * (1 + _TP_PCT), 2),
                    "stop": round(close * (1 - _STOP_PCT), 2),
                })
            except Exception as e:
                logger.warning(f"challenge_basket: {t} failed — {e}")
                etfs.append({"ticker": t, "error": str(e)[:60]})
        ok = [e for e in etfs if e.get("uptrend")]
        pick = max(ok, key=lambda e: e["mom20"])["ticker"] if ok else None
        as_of = None
        for t in BASKET:
            try:
                as_of = str(pd.Timestamp(raw[t]["Close"].dropna().index[-1]).date())
                break
            except Exception:
                continue
        return {
            "as_of": as_of,
            "etfs": etfs,
            "pick": pick,
            "n_qualified": len(ok),
            "note": ("合格=收盘>50日线且近一周上涨;之选=合格中20日动量最强"
                     "(bot 动量口径的复刻近似)。无合格标的=按纪律空仓等待。"),
        }
    except Exception as e:
        logger.warning(f"challenge_basket failed: {e}")
        return None
