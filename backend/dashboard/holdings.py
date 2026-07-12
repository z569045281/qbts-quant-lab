"""
13F institutional holdings signal — "smart money" tracking.

Data source: yfinance (which pulls from SEC EDGAR 13F filings, already parsed).
Updates quarterly (45 days after quarter-end), so 24h cache is plenty.

KEY INSIGHT — separate active vs passive:
  Index ETFs (Vanguard Total Stock Market, iShares Russell 2000, etc.) buy/sell
  based on index inclusion and AUM flows, NOT conviction. Their pctChange is
  mostly noise as a stock-selection signal.

  Active managers (hedge funds, asset managers, prop trading desks like UBS,
  Goldman, Clear Street, HRT, Citadel) take POSITIONS based on conviction.
  Their pctChange — especially new entries and full exits — is real signal.

  We separate the two and weight active managers ~3× more heavily.

Signal levels:
  Active net change > +15% + ≥2 new positions  → BUY high
  Active net change > +8%                       → BUY medium
  Active net change < -15%                      → SELL high
  ≥3 exits + concentration dropping             → SELL medium
  Insider% > 5% growing                         → +0.15 tilt BUY

STALENESS GATE (2026-07-13, added after the dashboard audit): 13F is a quarterly
STATIC snapshot, but the old code re-emitted the same directional push every single
day — it fired on 18/19 graded days with the largest average log-odds in the whole
edge model (+0.26) while hitting only 18% (n=17), single-handedly dragging overall
edge direction accuracy to ~25% in a downtrend. A slow variable must not masquerade
as a daily direction signal. Fix: the directional push only speaks while the filing
is fresh — Date Reported is the quarter END and filings lag ≤45 days, so ≤75 days
old = full strength (the just-filed window), 75–120 days = linear fade to zero,
>120 days = muted (signal 0). The holders snapshot/card display is untouched; only
the edge push is gated.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timezone
from pathlib import Path

import yfinance as yf

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).parent.parent / "data" / "cache" / "holdings_signal.json"
_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

_CACHE_TTL = 86400          # 24h — 13F is quarterly, no point refreshing more often
_NEW_POSITION_THRESHOLD = 0.95   # pctChange ≥ this = new entry (was 0 last quarter)
_EXIT_THRESHOLD         = -0.50  # pctChange ≤ this = major exit (sold ≥50%)
_FRESH_DAYS = 75            # report_date(季度末)+45天申报滞后 ≈ 申报刚落地的新鲜窗
_MUTE_DAYS  = 120           # 超过此天数 → 方向推力静音(展示照旧)

# Keyword patterns that identify PASSIVE index/ETF holders
_PASSIVE_KEYWORDS = (
    "index", "russell", "s&p", "total stock market", "iShares", "spdr",
    "ftse", "msci", "extended market", "small-cap index", "growth index",
    "value index", "vanguard total", "vanguard index funds", "vanguard small-cap",
    "vanguard mid-cap", "vanguard world", "fidelity small cap index",
    "fidelity extended market", "tech-software sector etf",
    # 2026-07-13 审计修:凡 Vanguard 名下臂膀(Portfolio Management / Capital
    # Management 等)都是指数化运作,此前漏网被当"主动新建仓"给假票 + "geode"
    # 是 Fidelity 的指数臂。宁可错杀 Vanguard 极少数主动产品,不能让指数流
    # 冒充聪明钱。
    "vanguard", "geode",
)


def _is_passive(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in _PASSIVE_KEYWORDS)


def _row_to_holder(row, kind: str) -> dict:
    return {
        "name":         str(row.get("Holder", "?")),
        "kind":         kind,                                   # "institutional" or "mutualfund"
        "pct_held":     float(row.get("pctHeld", 0) or 0),
        "shares":       int(row.get("Shares", 0) or 0),
        "pct_change":   float(row.get("pctChange", 0) or 0),
        "value":        float(row.get("Value", 0) or 0),
        "date":         str(row.get("Date Reported", "")),
        "passive":      _is_passive(str(row.get("Holder", ""))),
    }


def fetch_holdings(ticker: str = "QBTS") -> dict:
    t = yf.Ticker(ticker)

    # Institutional holders (top 10 by stake)
    ih = t.institutional_holders
    institutional = []
    if ih is not None and not ih.empty:
        institutional = [_row_to_holder(row, "institutional") for _, row in ih.iterrows()]

    # Mutual fund holders
    mf = t.mutualfund_holders
    mutualfund = []
    if mf is not None and not mf.empty:
        mutualfund = [_row_to_holder(row, "mutualfund") for _, row in mf.iterrows()]

    # Major holders summary
    mh = t.major_holders
    summary = {}
    if mh is not None and not mh.empty:
        # yfinance schema: index = breakdown name, single "Value" column
        for breakdown, row in mh.iterrows():
            key = breakdown if isinstance(breakdown, str) else row.iloc[0]
            val = float(row.iloc[0]) if isinstance(breakdown, str) else float(row.iloc[1])
            summary[str(key)] = val

    insider_pct       = float(summary.get("insidersPercentHeld",      0))
    institution_pct   = float(summary.get("institutionsPercentHeld",   0))
    institution_count = int(summary.get("institutionsCount",           0))

    all_holders = institutional + mutualfund
    active   = [h for h in all_holders if not h["passive"]]
    passive  = [h for h in all_holders if h["passive"]]

    def _avg(seq, key):
        seq = list(seq)
        return float(sum(s[key] for s in seq) / max(len(seq), 1)) if seq else 0.0

    active_avg_change  = _avg(active,  "pct_change")
    passive_avg_change = _avg(passive, "pct_change")
    new_positions = [h for h in active if h["pct_change"] >= _NEW_POSITION_THRESHOLD]
    exits         = [h for h in active if h["pct_change"] <= _EXIT_THRESHOLD]

    top10_concentration = sum(h["pct_held"] for h in institutional[:10])
    # Most-recent 13F report date — 13F is filed up to 45d after quarter-end, so
    # this is often 2-4 months stale. Surface it so the prompt can down-weight it.
    report_date = max((h["date"] for h in all_holders if h["date"]), default="")
    # 陈旧度闸用这个:信号本体来自主动管理人的季度 13F。全体 max 会被月报的
    # 共同基金(如 05-31)洗白,让 03-31 的季度数据看起来"新鲜"。
    active_report_date = max((h["date"] for h in active if h["date"]), default="")

    return {
        "ticker":              ticker,
        "report_date":         report_date,
        "active_report_date":  active_report_date,
        "institution_pct":     round(institution_pct, 4),
        "institution_count":   institution_count,
        "insider_pct":         round(insider_pct, 4),
        "top10_concentration": round(top10_concentration, 4),
        "active_avg_change":   round(active_avg_change, 4),
        "passive_avg_change":  round(passive_avg_change, 4),
        "n_active":            len(active),
        "n_passive":           len(passive),
        "n_new_positions":     len(new_positions),
        "n_exits":             len(exits),
        "new_positions":       [h["name"] for h in new_positions[:5]],
        "exits":               [h["name"] for h in exits[:5]],
        "top_holders":         institutional[:10],   # full data for display
        "top_mutualfunds":     mutualfund[:5],
    }


def compute_holdings_signal(data: dict) -> dict:
    if not data or data.get("institution_count", 0) == 0:
        return {
            "signal": 0, "label": "HOLD", "confidence": "low",
            "log_odds_magnitude": 0.0,
            "rationale": "机构持仓数据缺失",
            "snapshot": data,
        }

    active_change = data["active_avg_change"]
    n_new   = data["n_new_positions"]
    n_exits = data["n_exits"]
    n_active = max(data["n_active"], 1)

    signal = 0
    confidence = "low"
    mag = 0.0
    bits = []

    # Net active-manager flow
    if active_change > 0.15 and n_new >= 2:
        signal, confidence, mag = 1, "high", 0.35
        bits.append(
            f"主动管理人净流入 {active_change*100:+.0f}% · {n_new}/{n_active} 新建仓"
        )
    elif active_change > 0.08:
        signal, confidence, mag = 1, "medium", 0.20
        bits.append(f"主动管理人净流入 {active_change*100:+.0f}%（温和积累）")
    elif active_change < -0.15 or n_exits >= 3:
        signal, confidence, mag = -1, "high", 0.30
        bits.append(
            f"主动管理人净流出 {active_change*100:+.0f}% · {n_exits} 个清仓"
        )
    elif active_change < -0.08:
        signal, confidence, mag = -1, "medium", 0.18
        bits.append(f"主动管理人净流出 {active_change*100:+.0f}%")

    # Insider tilt — if material insider holding + growing → small extra bull push
    insider_pct = data.get("insider_pct", 0)
    if insider_pct > 0.03 and signal >= 0:
        bits.append(f"内部人持仓 {insider_pct*100:.1f}%（管理层确认）")
        if signal == 0:
            signal = 1
            confidence = "low"
            mag = 0.10

    if not bits:
        bits.append(
            f"机构 {data['institution_pct']*100:.0f}% · "
            f"主动净变化 {active_change*100:+.1f}%（中性）"
        )

    # 陈旧度闸:季度静态文件不再天天冒充每日方向信号(见模块 docstring)。
    # 用主动持有人自己的报告期 —— 全体 max 会被月报共同基金洗白。
    if signal != 0:
        rd = str(data.get("active_report_date") or data.get("report_date") or "")[:10]
        age_days = None
        if rd:
            try:
                age_days = (datetime.now(timezone.utc).date() - date.fromisoformat(rd)).days
            except ValueError:
                age_days = None
        if age_days is None or age_days > _MUTE_DAYS:
            bits.append(f"⚠️ 报告期 {rd or '未知'}"
                        f"{f' 距今 {age_days} 天' if age_days is not None else ''}"
                        f" 已过时 → 方向推力静音(仅展示)")
            signal, confidence, mag = 0, "low", 0.0
        elif age_days > _FRESH_DAYS:
            fade = (_MUTE_DAYS - age_days) / (_MUTE_DAYS - _FRESH_DAYS)
            mag = mag * fade
            bits.append(f"报告期 {rd} 距今 {age_days} 天 → 推力衰减 ×{fade:.2f}")

    return {
        "signal":             signal,
        "label":              {1: "BUY", -1: "SELL", 0: "HOLD"}[signal],
        "confidence":         confidence,
        "log_odds_magnitude": round(mag, 3),
        "rationale":          " · ".join(bits),
        "snapshot":           data,
    }


def get_holdings_signal(force_refresh: bool = False) -> dict:
    if not force_refresh and _CACHE_PATH.exists():
        try:
            cached = json.loads(_CACHE_PATH.read_text())
            if time.time() - cached.get("_ts", 0) < _CACHE_TTL:
                return cached["payload"]
        except Exception:
            pass

    try:
        data = fetch_holdings("QBTS")
        payload = compute_holdings_signal(data)
    except Exception as e:
        logger.warning(f"Holdings fetch failed: {e}")
        payload = {
            "signal": 0, "label": "HOLD", "confidence": "low",
            "log_odds_magnitude": 0.0,
            "rationale": f"13F 数据获取失败: {str(e)[:60]}",
            "snapshot": {},
        }

    _CACHE_PATH.write_text(json.dumps({"_ts": time.time(), "payload": payload},
                                       ensure_ascii=False))
    return payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import warnings; warnings.filterwarnings("ignore")
    sig = get_holdings_signal(force_refresh=True)
    snap = sig["snapshot"]
    print(f'{sig["label"]} ({sig["confidence"]}) — {sig["rationale"]}')
    print(f'  机构持仓: {snap.get("institution_pct",0)*100:.1f}% / {snap.get("institution_count","?")} 家')
    print(f'  主动净变化: {snap.get("active_avg_change",0)*100:+.1f}% · 被动净变化: {snap.get("passive_avg_change",0)*100:+.1f}%')
    print(f'  新建仓 ({snap.get("n_new_positions",0)}): {", ".join(snap.get("new_positions",[])[:3])}')
    print(f'  清仓 ({snap.get("n_exits",0)}): {", ".join(snap.get("exits",[])[:3]) or "(无)"}')
    print(f'  Top 10 集中度: {snap.get("top10_concentration",0)*100:.1f}%')
