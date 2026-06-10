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


def _fetch_intraday(ticker: str = "QBTS") -> dict:
    """Pull 1-day of 1-min bars and compute the surge metrics."""
    df = yf.download(ticker, period="1d", interval="1m",
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        return {}

    # yfinance returns MultiIndex columns when downloading a single ticker w/ certain flags
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

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
    surge_ratio = last_60_vol / expected_60 if expected_60 > 1 else 1.0

    # Tick direction over last hour
    if len(close) >= 60:
        h0 = float(close.iloc[-60])
        h_last = float(close.iloc[-1])
        last_hour_ret = (h_last - h0) / h0 if h0 > 0 else 0.0
    else:
        last_hour_ret = 0.0

    intraday_ret = (last_p - open_p) / open_p if open_p > 0 else 0.0

    return {
        "n_bars":          n_bars,
        "open":            round(open_p, 2),
        "last":            round(last_p, 2),
        "high":            round(high_p, 2),
        "low":             round(low_p, 2),
        "intraday_ret":    round(intraday_ret, 4),
        "last_hour_ret":   round(last_hour_ret, 4),
        "avg_vol_per_min": int(avg_vol_per_min),
        "last_60_vol":     int(last_60_vol),
        "surge_ratio":     round(surge_ratio, 2),
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
    intraday = s["intraday_ret"]
    last_hour = s["last_hour_ret"]

    signal = 0
    confidence = "low"
    mag = 0.0
    bits = []

    if surge > 2.5:
        # Major volume surge — direction matters
        if last_hour > 0.01:
            signal, confidence, mag = 1, "high", 0.35
            bits.append(f"最后 1 小时量能 {surge:.1f}× 均值 + 价格上行 {last_hour*100:+.1f}%（主力买入）")
        elif last_hour < -0.01:
            # Could be panic. If down a lot intraday, contrarian buy
            if intraday < -0.05:
                signal, confidence, mag = 1, "medium", 0.25
                bits.append(f"放量下跌 {surge:.1f}× + 当日 {intraday*100:.1f}%（恐慌见底）")
            else:
                signal, confidence, mag = -1, "medium", 0.20
                bits.append(f"放量下跌 {surge:.1f}× + 最后小时 {last_hour*100:.1f}%（持续抛压）")
    elif surge > 1.5:
        signal = 1 if last_hour > 0 else -1
        confidence = "medium"
        mag = 0.15
        bits.append(f"中等量能涌入 {surge:.1f}× · 最后小时 {last_hour*100:+.1f}%")
    elif surge < 0.4 and abs(intraday) > 0.03:
        # Trend fading — momentum exhaustion
        signal = -1 if intraday > 0 else 1
        confidence = "medium"
        mag = 0.18
        bits.append(f"量能枯竭 {surge:.1f}× + 当日已 {intraday*100:+.1f}%（动量衰竭）")

    if not bits:
        bits.append(f"量比 {surge:.1f}× · 当日 {intraday*100:+.1f}%（正常区间）")

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
