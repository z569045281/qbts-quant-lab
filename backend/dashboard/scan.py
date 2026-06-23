"""
Watchlist scanner — a daily buy-setup scan across a diversified high-beta basket.

This is the "广而浅" companion to the deep single-stock QBTS dashboard. It reuses
ONLY the ticker-agnostic signal modules — SMC structure, volume profile, and the
volatility regime — plus simple trend/RSI on freshly fetched bars. It deliberately
does NOT use any QBTS-specific data (13F / short volume / leveraged-ETF flow /
quantum peer basket) and makes NO per-name LLM call, so it's pure mechanical and
costs ~$0.

Basket = 7 different *drivers* (avg pairwise return-correlation ≈ 0.30), chosen
for high volatility + low mutual correlation + small-capital affordability, so on
any given day some theme is usually moving:

  QBTS 量子 · POET 光电/AI光 · EOSE 储能 · RUN 太阳能 · LUNR 航天 · MARA 比特币 · AG 白银

Each ticker → a compact card: a buy-setup score, a plain-language trigger, and the
key levels to act on. Ranked best-setup-first.
"""

from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

from data.fetcher import _clean_ohlcv
from dashboard.smc import analyze_smc
from dashboard.volume_profile import analyze_volume_profile
from dashboard.regime import analyze_regime

logger = logging.getLogger(__name__)

# Diversified, high-vol, small-capital-friendly basket (one name per driver).
WATCHLIST = ["QBTS", "POET", "EOSE", "RUN", "LUNR", "MARA", "AG"]
THEME = {
    "QBTS": "量子", "POET": "光电", "EOSE": "储能", "RUN": "太阳能",
    "LUNR": "航天", "MARA": "比特币", "AG": "白银",
}


def _fetch(ticker: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Light fetch: ~1y daily + ~60d hourly, cleaned to the same lowercase OHLCV
    format the signal modules expect. Single yf.download per resolution (no 730-day
    windowing) so the whole 7-name scan finishes fast enough for a daily Lambda."""
    d_raw = yf.download(ticker, period="1y", interval="1d", auto_adjust=True, progress=False)
    h_raw = yf.download(ticker, period="60d", interval="1h", auto_adjust=True, progress=False)
    if d_raw is None or d_raw.empty:
        raise RuntimeError(f"no daily data for {ticker}")
    df_d = _clean_ohlcv(d_raw, "1d")
    df_h = _clean_ohlcv(h_raw, "1h") if (h_raw is not None and not h_raw.empty) else pd.DataFrame()
    return df_d, df_h


def _rsi(close: pd.Series, n: int = 14) -> float | None:
    d = close.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    rs = up / dn.replace(0, np.nan)
    val = (100 - 100 / (1 + rs)).iloc[-1]
    return float(val) if pd.notna(val) else None


def _money(x) -> str | None:
    return f"${x:.2f}" if isinstance(x, (int, float)) and pd.notna(x) else None


def scan_ticker(ticker: str) -> dict:
    """Scan one ticker → a compact buy-setup card. Never raises; errors are captured."""
    base = {"ticker": ticker, "theme": THEME.get(ticker, "?")}
    try:
        df_d, df_h = _fetch(ticker)
        close = float(df_d["close"].iloc[-1])
        prev = float(df_d["close"].iloc[-2])
        today_change = (close / prev - 1) if prev > 0 else 0.0
        sma20 = float(df_d["close"].rolling(20).mean().iloc[-1])
        sma50 = float(df_d["close"].rolling(50).mean().iloc[-1])
        rsi = _rsi(df_d["close"])
        rets = df_d["close"].pct_change().dropna().tail(90)
        vol_annual = float(rets.std() * np.sqrt(252)) if len(rets) > 5 else None

        smc = analyze_smc(df_d, None, df_h if not df_h.empty else None)
        vp = analyze_volume_profile(df_h, None) if not df_h.empty else {}
        reg = analyze_regime(df_d)

        # ── transparent buy-setup score (-7..+7) ────────────────────────────
        pts = 0
        trend = smc.get("trend")
        if trend == "bullish":  pts += 2
        elif trend == "bearish": pts -= 2
        if close > sma20 and sma20 > sma50:   pts += 2
        elif close < sma20 and sma20 < sma50: pts -= 2
        elif close > sma20:                   pts += 1
        st = vp.get("stance")
        if st == "偏多":   pts += 1
        elif st == "偏空": pts -= 1
        zone = smc.get("zone", "") or ""
        if "discount" in zone or "折价" in zone:  pts += 1
        elif "premium" in zone or "溢价" in zone: pts -= 1
        if rsi is not None:
            if rsi < 35:   pts += 1
            elif rsi > 75: pts -= 1

        if pts >= 3:    stance, emoji = "买入区", "🟢"
        elif pts >= 1:  stance, emoji = "接近买点", "🟡"
        elif pts >= -1: stance, emoji = "观望", "⚪"
        else:           stance, emoji = "偏空回避", "🔴"
        score = round((pts + 7) / 14 * 100)

        # ── key levels ───────────────────────────────────────────────────────
        demand = smc.get("demand_zones") or []
        supply = smc.get("supply_zones") or []
        val, vah = vp.get("val"), vp.get("vah")
        mag_up = vp.get("nearest_magnet_up")
        below_demand = [z for z in demand if z.get("high", 1e9) <= close]
        buy_zone = max(below_demand, key=lambda z: z["high"]) if below_demand else None
        supply_above = [z["low"] for z in supply if z.get("low", 0) > close]
        target = mag_up or vah or (min(supply_above) if supply_above else None)
        brk = (min(supply_above) if supply_above else None) or vah

        # ── plain-language trigger ───────────────────────────────────────────
        bz = f"{_money(buy_zone['low'])}–{_money(buy_zone['high'])}" if buy_zone else None
        if stance == "买入区":
            if bz:     trig = f"结构偏多,可在需求区 {bz} 分批买"
            elif val:  trig = f"结构偏多,回踩价值区下沿 {_money(val)} 附近可买"
            else:      trig = "结构偏多,回踩不破前低可分批买"
            if target: trig += f",上方先看 {_money(target)}"
        elif stance == "接近买点":
            ref = bz or _money(val)
            if brk: trig = f"偏多但需确认:放量站上 {_money(brk)} 再进,或回踩 {ref} 企稳买"
            else:   trig = "偏多但需确认:等回踩企稳或放量突破再进"
        elif stance == "观望":
            parts = []
            if brk: parts.append(f"站上 {_money(brk)} 转强")
            if val: parts.append(f"回到价值区 {_money(val)} 下沿")
            trig = "方向不明," + ("、".join(parts) + " 再看" if parts else "等更明确的信号")
        else:  # 偏空回避
            dz = buy_zone or (demand[0] if demand else None)
            trig = "结构偏空,暂时回避"
            if dz: trig += f";想抄底等跌到需求区 {_money(dz['low'])}–{_money(dz['high'])} 出现企稳"

        notes = []
        if reg.get("regime"):
            reg_cn = {"expansion": "扩张", "contraction": "收缩", "normal": "正常"}.get(reg["regime"], "")
            pctl = reg.get("atr_pct_percentile")
            notes.append(f"波动{reg_cn}" + (f"（{pctl:.0f}%位）" if pctl is not None else ""))
        if vp.get("action_hint"):
            notes.append(vp["action_hint"][:60])

        base.update({
            "price": round(close, 2),
            "today_change": round(today_change, 4),
            "vol_annual": round(vol_annual, 3) if vol_annual is not None else None,
            "score": score, "points": pts,
            "stance": stance, "stance_emoji": emoji,
            "trend": trend, "regime": reg.get("regime"),
            "rsi": round(rsi, 0) if rsi is not None else None,
            "trigger": trig,
            "levels": {"buy_zone": bz, "target": _money(target), "stop_hint": reg.get("stop_hint")},
            "notes": notes,
            "error": None,
        })
    except Exception as e:
        logger.warning(f"scan {ticker} failed: {e}")
        base.update({"error": f"{type(e).__name__}: {str(e)[:80]}",
                     "stance": "—", "stance_emoji": "⚠️", "score": 0})
    return base


def scan_watchlist(tickers: list[str] | None = None) -> dict:
    """Scan the whole basket, ranked best-setup-first. Returns the publishable payload."""
    tickers = tickers or WATCHLIST
    results = [scan_ticker(t) for t in tickers]
    # rank: errored last, then by score desc
    results.sort(key=lambda r: (r.get("error") is not None, -(r.get("score") or 0)))
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tickers": tickers,
        "results": results,
    }


if __name__ == "__main__":
    import sys, json
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    out = scan_watchlist()
    for r in out["results"]:
        if r.get("error"):
            print(f"  ⚠️ {r['ticker']:5s} {r['error']}"); continue
        print(f"  {r['stance_emoji']} {r['ticker']:5s}{r['theme']:5s} 分{r['score']:>3d} "
              f"${r['price']:>7.2f} {r['today_change']*100:+5.1f}% 波{(r['vol_annual'] or 0)*100:3.0f}% | {r['trigger']}")
