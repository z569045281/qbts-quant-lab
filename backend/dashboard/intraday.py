"""
Intraday volume-surge signal (no paid feed required).

Pulls QBTS 1-minute bars for today via yfinance and compares the most recent
hour's volume to the day's per-minute average × 60:

  surge_ratio = vol_last_60min / (avg_vol_per_min × 60)

  surge_ratio > 2.0 + price up   → aggressive intraday accumulation (BUY)
  surge_ratio > 2.0 + price down → capitulation / panic (contrarian BUY)
  surge_ratio < 0.4 + extended   → momentum fading (SELL)

Also tracks how the last hour's tick direction compares to the morning:
fast/slow money pivot.

Cached 5 minutes (intraday signal is the freshest input).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).parent.parent / "data" / "cache" / "intraday_signal.json"
_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
_CACHE_TTL  = 300       # 5 minutes


def _day_volume_ratio(ticker: str = "QBTS") -> float | None:
    """真·量比 = 当日总成交量 / 前 20 个交易日均量。

    与 surge_ratio 是两回事:surge_ratio 按当日自身均速归一化(答「盘中什么时候
    在放量」),这个答「今天整体比平常放量多少」。日级别的新闻暴涨只有这个看得见。
    """
    try:
        d = yf.download(ticker, period="60d", interval="1d",
                        progress=False, auto_adjust=True)
        if d is None or d.empty:
            return None
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = [c[0] for c in d.columns]
        vol = d["Volume"].astype(float)
        if len(vol) < 22:
            return None
        base = float(vol.iloc[-21:-1].mean())      # 前 20 日,不含当日
        if base <= 0:
            return None
        return round(float(vol.iloc[-1]) / base, 2)
    except Exception as e:
        logger.warning(f"day volume ratio failed: {e}")
        return None


def _fetch_intraday(ticker: str = "QBTS") -> dict:
    """Pull 1-day of 1-min bars and compute the surge metrics."""
    # 2d so we get the previous session's close — "当日" must mean 较昨收
    # (same base as the price section's 今日), not open→last which hides the gap.
    df = yf.download(ticker, period="2d", interval="1m",
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        return {}

    # yfinance returns MultiIndex columns when downloading a single ticker w/ certain flags
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    sessions = sorted({d for d in df.index.date})
    prev_close = None
    if len(sessions) >= 2:
        prev_bars = df[df.index.date == sessions[-2]]
        if not prev_bars.empty:
            prev_close = float(prev_bars["Close"].iloc[-1])
    session_date = sessions[-1].strftime("%m-%d")
    df = df[df.index.date == sessions[-1]]
    if df.empty:
        return {}

    close = df["Close"].astype(float)
    vol   = df["Volume"].astype(float)
    open_p = float(close.iloc[0])
    last_p = float(close.iloc[-1])
    high_p = float(df["High"].max())
    low_p  = float(df["Low"].min())

    n_bars = len(df)
    avg_vol_per_min = float(vol.mean()) if n_bars > 0 else 0.0
    last_60 = vol.tail(60)
    last_60_vol = float(last_60.sum())
    expected_60 = avg_vol_per_min * 60
    # ⚠️ 口径:这是「末 60 分钟 vs 当日自身均速」,**不是**量比。它按当日自我
    # 归一化,所以整天均匀放量时它照样 ≈1.0 —— 结构上不可能看见日级别放量。
    # (07-27 实测:全天 2.6× 天量,本比值 0.93 → 曾被错标成「量比 0.9×」)
    surge_ratio = last_60_vol / expected_60 if expected_60 > 1 else 1.0
    day_vol_ratio = _day_volume_ratio(ticker)

    # Tick direction over last hour
    if len(close) >= 60:
        h0 = float(close.iloc[-60])
        h_last = float(close.iloc[-1])
        last_hour_ret = (h_last - h0) / h0 if h0 > 0 else 0.0
    else:
        last_hour_ret = 0.0

    intraday_ret = (last_p - open_p) / open_p if open_p > 0 else 0.0
    # day_ret = 较昨收(含跳空) — the same base the price section's 今日 uses
    day_ret = (last_p - prev_close) / prev_close if prev_close else None

    return {
        "n_bars":          n_bars,
        "session":         session_date,
        "open":            round(open_p, 2),
        "last":            round(last_p, 2),
        "high":            round(high_p, 2),
        "low":             round(low_p, 2),
        "prev_close":      round(prev_close, 2) if prev_close else None,
        "day_ret":         round(day_ret, 4) if day_ret is not None else None,
        "intraday_ret":    round(intraday_ret, 4),
        "last_hour_ret":   round(last_hour_ret, 4),
        "avg_vol_per_min": int(avg_vol_per_min),
        "last_60_vol":     int(last_60_vol),
        "surge_ratio":     round(surge_ratio, 2),
        "day_vol_ratio":   day_vol_ratio,
    }


def _signal_from_intraday(s: dict) -> dict:
    if not s or s.get("n_bars", 0) < 30:
        return {
            "signal": 0, "label": "HOLD", "confidence": "low",
            "log_odds_magnitude": 0.0,
            "rationale": "盘中数据不足（市场未开盘或拉取失败）",
            "snapshot": s,
        }
    surge = s["surge_ratio"]
    # 当日 = 较昨收(含跳空), 与价格段今日同口径; 拿不到昨收才退回开盘基准
    intraday = s["day_ret"] if s.get("day_ret") is not None else s["intraday_ret"]
    last_hour = s["last_hour_ret"]
    tag = f"({s['session']}盘)" if s.get("session") else ""
    # 全日量比单独说 —— surge 按当日自我归一化,看不见日级别放量(见 _fetch_intraday 注释)
    dvr = s.get("day_vol_ratio")
    day_vol_bit = ""
    if dvr:
        lvl = "天量" if dvr >= 2.5 else ("放量" if dvr >= 1.5 else ("缩量" if dvr < 0.7 else "常量"))
        day_vol_bit = f" · 全日量比 {dvr:.1f}×({lvl})"

    signal = 0
    confidence = "low"
    mag = 0.0
    bits = []

    if surge > 2.5:
        # Major volume surge — direction matters
        if last_hour > 0.01:
            signal, confidence, mag = 1, "high", 0.35
            bits.append(f"末 60 分钟 {surge:.1f}× 当日均速 + 价格上行 {last_hour*100:+.1f}%（主力买入）")
        elif last_hour < -0.01:
            # Could be panic. If down a lot intraday, contrarian buy
            if intraday < -0.05:
                signal, confidence, mag = 1, "medium", 0.25
                bits.append(f"尾盘放量下跌 末60分 {surge:.1f}× 当日均速 + 当日 {intraday*100:.1f}%（恐慌见底）")
            else:
                signal, confidence, mag = -1, "medium", 0.20
                bits.append(f"尾盘放量下跌 末60分 {surge:.1f}× 当日均速 + 最后小时 {last_hour*100:.1f}%（持续抛压）")
    elif surge > 1.5:
        signal = 1 if last_hour > 0 else -1
        confidence = "medium"
        mag = 0.15
        bits.append(f"尾盘中等量能涌入 末60分 {surge:.1f}× 当日均速 · 最后小时 {last_hour*100:+.1f}%")
    elif surge < 0.4 and abs(intraday) > 0.03:
        # Trend fading — momentum exhaustion
        signal = -1 if intraday > 0 else 1
        confidence = "medium"
        mag = 0.18
        bits.append(f"尾盘量能枯竭 末60分 {surge:.1f}× 当日均速 + 当日已 {intraday*100:+.1f}%（动量衰竭）")

    if not bits:
        # 「正常区间」只描述尾盘节奏,不得暗示全日成交也正常 —— 07-27 天量日曾
        # 因两者混为一谈而输出「量比 0.9×(正常区间)」,与 2.6× 的实际天量相反。
        bits.append(f"尾盘节奏平稳 末60分 {surge:.1f}× 当日均速 · 当日 {intraday*100:+.1f}%")
    bits[-1] += day_vol_bit
    if tag:
        bits[-1] += f" {tag}"

    return {
        "signal":             signal,
        "label":              {1: "BUY", -1: "SELL", 0: "HOLD"}[signal],
        "confidence":         confidence,
        "log_odds_magnitude": round(mag, 3),
        "rationale":          " · ".join(bits),
        "snapshot":           s,
    }


def get_intraday_signal(force_refresh: bool = False) -> dict:
    if not force_refresh and _CACHE_PATH.exists():
        try:
            cached = json.loads(_CACHE_PATH.read_text())
            if time.time() - cached.get("_ts", 0) < _CACHE_TTL:
                return cached["payload"]
        except Exception:
            pass

    try:
        snap = _fetch_intraday("QBTS")
        payload = _signal_from_intraday(snap)
    except Exception as e:
        logger.warning(f"Intraday fetch failed: {e}")
        payload = {"signal": 0, "label": "HOLD", "confidence": "low",
                   "log_odds_magnitude": 0.0,
                   "rationale": f"盘中数据获取失败: {str(e)[:60]}",
                   "snapshot": {}}

    _CACHE_PATH.write_text(json.dumps({"_ts": time.time(), "payload": payload},
                                       ensure_ascii=False))
    return payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import warnings; warnings.filterwarnings("ignore")
    print(json.dumps(get_intraday_signal(force_refresh=True), indent=2, ensure_ascii=False))
