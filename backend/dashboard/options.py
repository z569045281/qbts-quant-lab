"""
Options flow signal for the dashboard meta-model.

Pulls the QBTS options chain via yfinance (current snapshot, no historical):
  - Put/Call open-interest ratio (PCR_oi) across near-term expirations
  - Put/Call volume ratio (PCR_vol)
  - Gamma-exposure proxy: OI concentration around ATM
  - Unusual activity flag: today's call volume / call OI > 0.5

What it tells us:
  - PCR_oi > 0.9 + price holding = bears over-positioned → squeeze setup (BUY)
  - PCR_oi < 0.4 + price extended = bulls crowded → mean-revert risk (SELL)
  - High call vol/OI ratio = aggressive new bullish positioning (BUY)
  - High put vol/OI ratio = hedging or directional bear positioning (SELL)

Cached for 1 hour — options snapshot doesn't move fast enough to justify
hitting yfinance every dashboard refresh.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).parent.parent / "data" / "cache" / "options_signal.json"
_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
_CACHE_TTL  = 3600       # 1 hour
_MAX_EXPS   = 3          # use up to 3 near-term expirations


def _fetch_options_summary(ticker: str = "QBTS") -> dict:
    t = yf.Ticker(ticker)
    exps = list(t.options or [])[:_MAX_EXPS]
    if not exps:
        return {}

    spot = float(t.info.get("regularMarketPrice") or t.history(period="1d")["Close"].iloc[-1])

    call_oi_tot = put_oi_tot = 0.0
    call_vol_tot = put_vol_tot = 0.0
    atm_oi = 0.0
    total_oi = 0.0

    for exp in exps:
        try:
            chain = t.option_chain(exp)
        except Exception:
            continue
        for df, side in ((chain.calls, "call"), (chain.puts, "put")):
            if df is None or df.empty:
                continue
            oi  = pd.to_numeric(df.get("openInterest", 0), errors="coerce").fillna(0)
            vol = pd.to_numeric(df.get("volume",       0), errors="coerce").fillna(0)
            strike = pd.to_numeric(df.get("strike", 0), errors="coerce").fillna(0)
            oi_sum  = float(oi.sum())
            vol_sum = float(vol.sum())
            if side == "call":
                call_oi_tot += oi_sum
                call_vol_tot += vol_sum
            else:
                put_oi_tot  += oi_sum
                put_vol_tot += vol_sum
            # ATM concentration (±10% of spot)
            atm_mask = (strike >= spot * 0.9) & (strike <= spot * 1.1)
            atm_oi  += float(oi[atm_mask].sum())
            total_oi += oi_sum

    return {
        "spot":         round(spot, 2),
        "call_oi":      int(call_oi_tot),
        "put_oi":       int(put_oi_tot),
        "call_vol":     int(call_vol_tot),
        "put_vol":      int(put_vol_tot),
        "atm_oi_share": round(atm_oi / max(total_oi, 1), 3),
        "n_expirations": len(exps),
    }


def _signal_from_summary(s: dict) -> dict:
    """Convert raw OI/vol numbers into BUY/SELL/HOLD + rationale + log-odds magnitude."""
    if not s or (s.get("call_oi", 0) + s.get("put_oi", 0)) == 0:
        return {
            "signal": 0, "label": "HOLD", "confidence": "low",
            "log_odds_magnitude": 0.0,
            "rationale": "期权链数据缺失",
            "snapshot": s,
        }

    call_oi  = max(s["call_oi"], 1)
    put_oi   = max(s["put_oi"],  1)
    call_vol = s["call_vol"]
    put_vol  = s["put_vol"]
    pcr_oi  = put_oi  / call_oi
    pcr_vol = put_vol / max(call_vol, 1)
    call_churn = call_vol / call_oi   # new aggressive call positioning
    put_churn  = put_vol  / put_oi    # new aggressive put positioning

    signal     = 0
    confidence = "low"
    log_odds_mag = 0.0
    bits = []

    # Extreme PCR → contrarian setup
    if pcr_oi > 1.0:
        signal       = 1
        confidence   = "high" if pcr_oi > 1.3 else "medium"
        log_odds_mag = 0.35 if pcr_oi > 1.3 else 0.20
        bits.append(f"PCR_OI={pcr_oi:.2f}（put 主导，挤空燃料）")
    elif pcr_oi < 0.5:
        signal       = -1
        confidence   = "high" if pcr_oi < 0.35 else "medium"
        log_odds_mag = 0.30 if pcr_oi < 0.35 else 0.18
        bits.append(f"PCR_OI={pcr_oi:.2f}（call 过度拥挤）")

    # Unusual aggressive activity overrides
    if call_churn > 0.5 and signal != -1:
        signal = 1
        confidence = "high"
        log_odds_mag = max(log_odds_mag, 0.40)
        bits.append(f"call_churn={call_churn:.0%}（异常新增看涨头寸）")
    if put_churn > 0.5 and signal != 1:
        signal = -1
        confidence = "high"
        log_odds_mag = max(log_odds_mag, 0.40)
        bits.append(f"put_churn={put_churn:.0%}（异常新增看跌对冲）")

    if not bits:
        bits.append(f"PCR_OI={pcr_oi:.2f}（中性区间）")

    return {
        "signal":             signal,
        "label":              {1: "BUY", -1: "SELL", 0: "HOLD"}[signal],
        "confidence":         confidence,
        "log_odds_magnitude": round(log_odds_mag, 3),
        "rationale":          " · ".join(bits),
        "snapshot": {
            **s,
            "pcr_oi":     round(pcr_oi, 3),
            "pcr_vol":    round(pcr_vol, 3),
            "call_churn": round(call_churn, 3),
            "put_churn":  round(put_churn, 3),
        },
    }


def get_options_signal(force_refresh: bool = False) -> dict:
    """Public entry — cached 1 hour. Returns signal dict for the meta-model."""
    if not force_refresh and _CACHE_PATH.exists():
        try:
            cached = json.loads(_CACHE_PATH.read_text())
            if time.time() - cached.get("_ts", 0) < _CACHE_TTL:
                return cached["payload"]
        except Exception:
            pass

    try:
        summary = _fetch_options_summary("QBTS")
        payload = _signal_from_summary(summary)
    except Exception as e:
        logger.warning(f"Options fetch failed: {e}")
        payload = {"signal": 0, "label": "HOLD", "confidence": "low",
                   "log_odds_magnitude": 0.0,
                   "rationale": f"期权数据获取失败: {str(e)[:60]}",
                   "snapshot": {}}

    _CACHE_PATH.write_text(json.dumps({"_ts": time.time(), "payload": payload},
                                       ensure_ascii=False))
    return payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    s = get_options_signal(force_refresh=True)
    print(json.dumps(s, indent=2, ensure_ascii=False))
