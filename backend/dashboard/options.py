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


def _fetch_options_summary(ticker: str = "QBTS", spot_hint: float | None = None) -> dict:
    t = yf.Ticker(ticker)
    exps = list(t.options or [])[:_MAX_EXPS]
    if not exps:
        return {}

    # spot 优先用调用方给的**已清洗**收盘价(2026-07-31)。事故:07-30 上游返回一根
    # 违反 OHLC 不变式的坏 bar(C16.21,真实 17.97),fetcher 已剔除并用小时线重建,
    # 但这里自己去 yfinance 又把那个坏数捞了回来 —— ±10% 的 ATM 窗口(14.59~17.83)
    # 整个落在真实价格下方,atm_oi_share 算的是一批虚值 call。
    # 清洗过的价格拿不到时才回退自取。
    spot = float(spot_hint) if spot_hint and float(spot_hint) > 0 else float(
        t.info.get("regularMarketPrice") or t.history(period="1d")["Close"].iloc[-1])

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
    if not s or (s.get("call_vol", 0) + s.get("put_vol", 0)
                 + s.get("call_oi", 0) + s.get("put_oi", 0)) == 0:
        return {
            "signal": 0, "label": "HOLD", "confidence": "low",
            "log_odds_magnitude": 0.0,
            "rationale": "期权链数据缺失",
            "snapshot": s,
        }

    if (s.get("call_oi", 0) + s.get("put_oi", 0)) == 0:
        # Yahoo 间歇性把全链 openInterest 置 0(OI 来自 OCC 每日更新,Yahoo 时常断供)
        # 而 volume 正常 —— 2026-07-22 实测 3 个到期日 call_vol 7388/put_vol 3331 全有、
        # OI 全 0。全拉黑会让自检天天报"期权数据缺失",实际当日量能口径仍有信息:
        # 退回纯 PCR_vol 读数,权重压到 0.10、confidence=low,口径诚实标注。
        pcr_vol = s["put_vol"] / max(s["call_vol"], 1)
        signal, mag, note = 0, 0.0, "中性"
        if pcr_vol > 1.5:
            signal, mag, note = 1, 0.10, "put 流极端,反向偏多"
        elif pcr_vol < 0.35:
            signal, mag, note = -1, 0.10, "call 追逐极端,反向偏空"
        return {
            "signal": signal, "label": {1: "BUY", -1: "SELL", 0: "HOLD"}[signal],
            "confidence": "low", "log_odds_magnitude": mag,
            "rationale": (f"OI 断供(Yahoo)·仅当日量能口径:PCR_vol={pcr_vol:.2f}（{note}）"
                          f"— churn/持仓类读数不可用"),
            "snapshot": {**s, "pcr_vol": round(pcr_vol, 3), "oi_missing": True},
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


def get_options_signal(force_refresh: bool = False,
                       spot_hint: float | None = None) -> dict:
    """Public entry — cached 1 hour. Returns signal dict for the meta-model.

    `spot_hint` — 已清洗的收盘价(见 `_fetch_options_summary`)。
    """
    if not force_refresh and _CACHE_PATH.exists():
        try:
            cached = json.loads(_CACHE_PATH.read_text())
            if time.time() - cached.get("_ts", 0) < _CACHE_TTL:
                return cached["payload"]
        except Exception:
            pass

    try:
        summary = _fetch_options_summary("QBTS", spot_hint=spot_hint)
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
