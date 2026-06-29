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

  QBTS 量子 · POET 光电/AI光 · EOSE 储能 · RUN 太阳能 · LUNR 航天 · MARA 比特币 · AG 白银 · MU 存储芯片

Each ticker → a compact card: a buy-setup score, a plain-language trigger, and the
key levels to act on. Ranked best-setup-first.

The one per-name exception is a small static *lockup-event overlay* (informational
countdown for fresh IPOs like SPCX, dates from live research). It never feeds the
buy-setup score — it's there precisely because the mechanical signals are blind to
supply events. See CLAUDE.md "lead with WebSearch for stock topics".
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

from data.fetcher import _clean_ohlcv
from dashboard.smc import analyze_smc
from dashboard.volume_profile import analyze_volume_profile
from dashboard.regime import analyze_regime

logger = logging.getLogger(__name__)

# Diversified, high-vol, small-capital-friendly basket (one name per driver).
WATCHLIST = ["QBTS", "POET", "EOSE", "RUN", "LUNR", "MARA", "AG", "MU"]
THEME = {
    "QBTS": "量子", "POET": "光电", "EOSE": "储能", "RUN": "太阳能",
    "LUNR": "航天", "MARA": "比特币", "AG": "白银", "MU": "存储芯片",
    # personal-interest adds
    "NVDA": "芯片", "SPCX": "SpaceX",
    # diversifying drivers (low corr to basket, verified 2026-06-24)
    "MP": "稀土", "SYM": "机器人",
}

# ── Lockup-event overlay (informational only; does NOT feed the score) ────────────
# Static, hand-verified IPO lockup schedules for event-driven fresh listings — the
# mechanical scan cannot see supply unlocks, so we surface a countdown. Dates from
# live research (WebSearch 2026-06-24); re-verify before trusting near a date.
LOCKUPS: dict[str, dict] = {
    "SPCX": {
        "ipo_date": "2026-06-12", "ipo_price": 135.0,
        "note": "IPO 价 $135 是关键参考线 · 马斯克+大股东锁定至 2027-06-13",
        "events": [
            {"date": "2026-08-01", "label": "首次大解禁 ≈20%（早期机构/VC，≈2倍流通盘）", "approx": True, "big": True},
            {"date": "2026-08-21", "label": "解禁 7%（IPO+70天）"},
            {"date": "2026-09-10", "label": "解禁 7%（IPO+90天）"},
            {"date": "2026-09-25", "label": "解禁 7%（IPO+105天）"},
            {"date": "2026-10-10", "label": "解禁 7%（IPO+120天）"},
            {"date": "2026-10-25", "label": "解禁 7%（IPO+135天）"},
            {"date": "2026-12-08", "label": "180天主锁定期到期", "big": True},
            {"date": "2027-06-13", "label": "马斯克+大股东解禁（366天）", "big": True},
        ],
    },
}


def _lockup_info(ticker: str) -> dict | None:
    """Next upcoming lockup unlock for `ticker` + a days-remaining countdown.
    Returns None for names with no known schedule; informational only."""
    spec = LOCKUPS.get(ticker)
    if not spec:
        return None
    today = date.today()
    upcoming = [
        {**e, "days": (date.fromisoformat(e["date"]) - today).days}
        for e in spec["events"] if date.fromisoformat(e["date"]) >= today
    ]
    if not upcoming:
        return {"note": spec.get("note"), "next": None}
    nxt = upcoming[0]
    return {
        "next_date": nxt["date"], "days": nxt["days"], "label": nxt["label"],
        "approx": nxt.get("approx", False), "big": nxt.get("big", False),
        "note": spec.get("note"), "ipo_price": spec.get("ipo_price"),
        "upcoming": [{"date": u["date"], "label": u["label"], "days": u["days"]} for u in upcoming[:3]],
    }


_MIN_BARS = 60   # below this many daily bars, technicals are noise (e.g. fresh IPO)


def _earnings_info(ticker: str) -> dict | None:
    """Next earnings date + countdown, best-effort from yfinance. Earnings = gap risk
    the mechanical signals can't see. None when unknown / >120 days out / already past."""
    try:
        cal = yf.Ticker(ticker).calendar
    except Exception:
        return None
    ed = None
    try:
        if isinstance(cal, dict):
            v = cal.get("Earnings Date")
            ed = v[0] if isinstance(v, (list, tuple)) and v else v
        elif cal is not None and hasattr(cal, "loc"):
            ed = cal.loc["Earnings Date"][0]
    except Exception:
        ed = None
    if ed is None:
        return None
    try:
        d = pd.Timestamp(ed).date()
    except Exception:
        return None
    days = (d - date.today()).days
    if days < 0 or days > 120:
        return None
    return {"date": d.isoformat(), "days": days, "soon": days <= 14}


def _dilution_info(ticker: str) -> dict | None:
    """Recent SEC dilution filings (424B offering / S-3 shelf) — event-aware backstop
    for the event-blind mechanical scan. Free EDGAR; never raises."""
    try:
        from data.altdata import fetch_sec_dilution
        return fetch_sec_dilution(ticker)
    except Exception:
        return None


def _market_context() -> dict | None:
    """Risk-on/off gate from SPY/QQQ vs their 50-day MA + VIX, computed once per scan.
    The per-name scan is otherwise blind to the broad tape — a buy signal in a market-
    wide selloff is not the same as one in an uptrend."""
    try:
        px = yf.download(["SPY", "QQQ", "^VIX"], period="6mo", interval="1d",
                         auto_adjust=True, progress=False)["Close"]
        def vs50(sym: str) -> float:
            s = px[sym].dropna()
            return round(float(s.iloc[-1] / s.rolling(50).mean().iloc[-1] - 1), 4)
        spy, qqq = vs50("SPY"), vs50("QQQ")
        vix = float(px["^VIX"].dropna().iloc[-1])
        ups = (spy >= 0) + (qqq >= 0)
        if ups == 2 and vix < 20:
            regime, note = "risk_on", "大盘在 50 日线上方、VIX 偏低 —— 顺风,买入信号更可信。"
        elif ups == 0 or vix >= 28:
            regime, note = "risk_off", "大盘走弱 / VIX 偏高 —— 逆风,买入信号打折扣,宁可空仓等。"
        else:
            regime, note = "caution", "大盘中性偏震荡 —— 买入信号谨慎对待、小仓位为宜。"
        return {"regime": regime, "note": note, "vix": round(vix, 1),
                "spy_vs_50dma": spy, "qqq_vs_50dma": qqq}
    except Exception as e:
        logger.warning(f"market context failed: {e}")
        return None


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


def _exit_hint(close: float, target_num, sma20, sma50, buy_zone) -> dict | None:
    """Lightweight, position-aware exit cue judged purely from *today's* price vs the
    printed upside target and the 20/50-day moving averages. Stateless — we don't track
    the user's entry — so it's framed as "如有持仓" and only fires on events that are
    visible the day of the scan (at/near target, or already below an MA). Returns
    {kind, tag, text} or None when a holder has nothing obvious to do (just hold)."""
    # 止损侧:失守均线 = 结构走弱(扫描当天即可判定)。先判止损再判止盈——
    # 否则价格回落后"上方最近目标"会塌到现价头顶,把破位止损误判成止盈。
    if isinstance(sma50, (int, float)) and pd.notna(sma50) and close < sma50:
        return {"kind": "risk", "tag": "⚠️ 跌破50日线",
                "text": f"已失守 50 日线 {_money(sma50)} —— 中期结构走弱,如有持仓注意止损"}
    if isinstance(sma20, (int, float)) and pd.notna(sma20) and close < sma20:
        return {"kind": "risk", "tag": "⚠️ 跌破20日线",
                "text": f"已失守 20 日线 {_money(sma20)} —— 短线转弱,如有持仓收紧止损"}
    # 止盈侧:接近或越过上方目标
    if isinstance(target_num, (int, float)) and pd.notna(target_num) and target_num > 0:
        if close >= target_num:
            return {"kind": "profit", "tag": "🎯 已到目标",
                    "text": f"已到/越过上方目标 {_money(target_num)} —— 如有持仓可分批止盈、落袋为安"}
        if close >= target_num * 0.97:
            return {"kind": "profit", "tag": "🎯 接近目标",
                    "text": f"接近上方目标 {_money(target_num)} —— 如有持仓可考虑分批减"}
    # 警戒侧:正贴着下方需求区上沿,跌破则走弱
    edge = buy_zone.get("high") if isinstance(buy_zone, dict) else None
    if isinstance(edge, (int, float)) and pd.notna(edge) and edge < close <= edge * 1.02:
        return {"kind": "warn", "tag": "👀 测试支撑",
                "text": f"正贴着支撑 {_money(edge)},跌破则走弱 —— 如有持仓收紧止损"}
    return None


def scan_ticker(ticker: str) -> tuple[dict, "pd.DataFrame | None"]:
    """Scan one ticker → (card, daily_df). Never raises; errors are captured.
    The daily df is returned so the caller can grade past calls without re-fetching."""
    base = {"ticker": ticker, "theme": THEME.get(ticker, "其他"),
            "lockup": _lockup_info(ticker), "earnings": _earnings_info(ticker),
            "dilution": _dilution_info(ticker)}
    df_d = None
    try:
        df_d, df_h = _fetch(ticker)
        n_bars = len(df_d)
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
        # 上方参照必须真的在现价之上 —— 突破/创新高的票上方常无成交节点或供给,
        # 兜底绝不能吐一个低于现价的数当"上方目标"(读着像胡说,还会污染纸面止盈)。
        _cand = [mag_up, vah, (min(supply_above) if supply_above else None)]
        _ups = [x for x in _cand if isinstance(x, (int, float)) and pd.notna(x) and x > close]
        target = min(_ups) if _ups else None
        brk = (min(supply_above) if supply_above else None) \
              or (vah if (isinstance(vah, (int, float)) and pd.notna(vah) and vah > close) else None)

        # ── plain-language trigger ───────────────────────────────────────────
        bz = f"{_money(buy_zone['low'])}–{_money(buy_zone['high'])}" if buy_zone else None
        if stance == "买入区":
            if bz:     trig = f"结构偏多,可在需求区 {bz} 分批买"
            elif val:  trig = f"结构偏多,回踩价值区下沿 {_money(val)} 附近可买"
            else:      trig = "结构偏多,回踩不破前低可分批买"
            if target: trig += f",上方先看 {_money(target)}"
            else:      trig += ",已突破·上方无成交参照(创新高,追高谨慎)"
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

        thin = n_bars < _MIN_BARS
        if thin:
            notes.insert(0, f"⚠️ 仅 {n_bars} 天历史,技术信号不可靠(已排除出模拟交易)")
        # extreme single-day move = possible bad/stale data
        if abs(today_change) > 0.5:
            notes.insert(0, f"⚠️ 单日 {today_change*100:+.0f}% 异常,核对数据")

        base.update({
            "price": round(close, 2),
            "today_change": round(today_change, 4),
            "vol_annual": round(vol_annual, 3) if vol_annual is not None else None,
            "bars": n_bars, "thin_data": thin,
            "score": score, "points": pts,
            "stance": stance, "stance_emoji": emoji,
            "trend": trend, "regime": reg.get("regime"),
            "rsi": round(rsi, 0) if rsi is not None else None,
            "trigger": trig,
            "levels": {"buy_zone": bz, "target": _money(target), "stop_hint": reg.get("stop_hint")},
            "target_num": round(target, 2) if isinstance(target, (int, float)) and pd.notna(target) else None,
            "exit_hint": _exit_hint(close, target, sma20, sma50, buy_zone),
            "notes": notes,
            "error": None,
        })
    except Exception as e:
        logger.warning(f"scan {ticker} failed: {e}")
        base.update({"error": f"{type(e).__name__}: {str(e)[:80]}",
                     "stance": "—", "stance_emoji": "⚠️", "score": 0})
    return base, df_d


def _commentary_fallback(buys: list[dict]) -> str:
    names = "、".join(r["ticker"] for r in buys[:3])
    return f"今天比较接近买点的是 {names}——可以重点盯着,等它们到上面写的价位再考虑,不急。"


def _commentary(results: list[dict]) -> str:
    """A cheap, plain-language one-liner on the top buy-leaning picks (Haiku, ~$0.001)."""
    buys = [r for r in results if r.get("stance") in ("买入区", "接近买点")]
    if not buys:
        return "今天篮子里没有明显买点——多数在观望或结构偏空,适合空仓等待。"
    try:
        import anthropic
        top = buys[:3]
        facts = "\n".join(
            f"- {r['ticker']}（{r['theme']}）：{r['stance']}，{r.get('trigger','')}" for r in top)
        prompt = (
            "你是个把行情讲给完全不懂股票的朋友听的人。下面是今天扫描里最接近买点的几只股票,"
            "用最朴实的大白话两三句话点评:别用任何术语(不要说 止损/盈亏比/结构/RSI/区间 等),"
            "说说今天可以重点看哪只、为什么,并提醒这只是观察、不是必须买。只输出这几句话。\n\n" + facts)
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=300,
            messages=[{"role": "user", "content": prompt}])
        txt = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "").strip()
        return txt or _commentary_fallback(buys)
    except Exception as e:
        logger.warning(f"scan commentary failed: {e}")
        return _commentary_fallback(buys)


def scan_watchlist(tickers: list[str] | None = None) -> dict:
    """Scan the watchlist, ranked best-setup-first. Grades past calls, records today's,
    attaches each ticker's track record, and adds a plain-language commentary.
    Returns the publishable payload."""
    from dashboard import scan_store as store
    tickers = tickers or store.load_watchlist(WATCHLIST)

    results: list[dict] = []
    dfs: dict[str, "pd.DataFrame"] = {}
    for t in tickers:
        r, df_d = scan_ticker(t)
        results.append(r)
        if df_d is not None:
            dfs[t] = df_d
    results.sort(key=lambda r: (r.get("error") is not None, -(r.get("score") or 0)))

    # track record: grade old calls + record today's, then attach per-ticker hit rate
    overall = {"n": 0, "correct": 0, "hit_rate": None}
    try:
        store.grade_and_record(results, dfs)
        summary = store.scan_summary()
        overall = summary["overall"]
        for r in results:
            r["record"] = summary["by_ticker"].get(r["ticker"])
    except Exception as e:
        logger.warning(f"scan track-record failed: {e}")

    # paper trades: $1000 per buy signal, held to a sell signal → realized/unrealized P&L
    paper = None
    try:
        paper = store.run_paper_trades(results)
    except Exception as e:
        logger.warning(f"scan paper-trades failed: {e}")

    # broad-tape context (the per-name scan is otherwise blind to it)
    market = _market_context()

    # portfolio-level risk: if >1 clean buy signal, how correlated are they?
    concurrent = None
    buys = [r["ticker"] for r in results if r.get("stance") == "买入区" and not r.get("thin_data")]
    if len(buys) >= 2:
        try:
            import itertools
            rmat = pd.DataFrame({t: dfs[t]["close"].pct_change()
                                 for t in buys if t in dfs}).dropna().tail(120)
            cm = rmat.corr()
            pairs = [cm.loc[a, b] for a, b in itertools.combinations(rmat.columns, 2)]
            avg = round(float(np.mean(pairs)), 2) if pairs else None
            if avg is not None and avg >= 0.6:
                note = f"今天 {len(buys)} 个买入信号彼此相关性高({avg})——同涨同跌,全买≈加杠杆,控制总仓位、别等额铺开。"
            elif avg is not None:
                note = f"今天 {len(buys)} 个买入信号相关性 {avg},分散尚可,但合计仓位仍要设上限。"
            else:
                note = None
            concurrent = {"tickers": buys, "avg_corr": avg, "note": note}
        except Exception as e:
            logger.warning(f"concurrent-buys corr failed: {e}")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),   # tz-aware UTC → 前端转本地
        "tickers": tickers,
        "results": results,
        "record_overall": overall,
        "paper": paper,
        "market": market,
        "concurrent_buys": concurrent,
        "commentary": _commentary(results),
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
