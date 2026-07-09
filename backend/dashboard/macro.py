"""
Macro economic calendar — CPI / PPI / FOMC / NFP and friends.

QBTS is a high-beta, long-duration small-cap sensitive to macro liquidity
expectations. 第十五轮实测(2026-07-09)修正了本模块最初的夸张假设:宏观数据日
放大的是【大盘/板块】波动(非农 SPY×1.56*/QTUM×1.46*、CPI×1.44、FOMC×1.31),
QBTS 单票系数全≈1.0 —— 6.3%/日固有波动淹没宏观脉冲。日历的正确用途 = 方向
背景(数据落地后看大盘转向),不是单票事件风险。

Source: ForexFactory weekly calendar JSON (faireconomy CDN, free, no key):
    https://nfs.faireconomy.media/ff_calendar_thisweek.json
    https://nfs.faireconomy.media/ff_calendar_nextweek.json
Covers ~14 days forward. Cached 6h.

Outputs:
  events        — USD medium/high-impact events with forecast/previous
  nuclear       — subset that historically whipsaws high-beta stocks
  risk_window   — True if a nuclear event lands within the next 48 h
                  (decision engine should size down / demand confirmation)
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Only thisweek is reliably published; FOMC beyond this week comes from the
# hardcoded schedule below.
_URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
]
_CACHE_PATH = Path(__file__).parent.parent / "data" / "cache" / "macro_calendar.json"
_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
_CACHE_SECONDS = 6 * 3600

_UA = "Mozilla/5.0 (QBTS-Quant-Lab/1.0)"

# FOMC meeting dates are published years in advance by the Fed — hardcoding is
# the most reliable source (the FF weekly feed only covers the current week).
# Second day = rate decision + press conference (14:00/14:30 ET).
_FOMC_2026 = [
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]

# Events that historically whipsaw high-beta growth stocks (substring match,
# case-insensitive, against the FF title).
# 第十五轮实测(2026-07-09,mining.md)按事件日 |ret| 放大倍数修剪:PPI/核心PCE/
# GDP/零售/JOLTS 连 SPY 都不动(×0.96~1.14, ns)→ 退出 nuclear,免得 risk_window
# 为无关数据收缩仓位;真重磅只有 非农>CPI>FOMC。失业率与非农同场发布,补进名单。
_NUCLEAR_PATTERNS = (
    "cpi", "fomc", "federal funds rate", "non-farm", "nonfarm",
    "unemployment rate", "jackson hole", "press conference",
)

# 第十五轮事件日影响系数(2022-08~2026-07,事件日 |ret| ÷ 无事件日 |ret|;
# *=统计显著)。核心发现:QBTS 单票所有宏观日系数≈1.0 —— 6.3%/日的固有波动
# 淹没宏观脉冲;宏观通过大盘/板块通道起作用(方向背景),不构成单票事件风险。
_IMPACT_COEF = (
    # (patterns, {spy, qtum, qbts, label})
    (("non-farm", "nonfarm", "unemployment rate", "average hourly"),
     {"spy": 1.56, "qtum": 1.46, "qbts": 1.05, "label": "非农/失业率 大盘×1.56*"}),
    (("cpi",),
     {"spy": 1.44, "qtum": 1.25, "qbts": 0.99, "label": "CPI 大盘×1.44"}),
    (("fomc", "federal funds rate", "press conference"),
     {"spy": 1.31, "qtum": 0.96, "qbts": 0.99, "label": "FOMC 大盘×1.31·余波常在次日"}),
    (("unemployment claims",),
     {"spy": 1.14, "qtum": 1.15, "qbts": 1.04, "label": "初请 大盘×1.14"}),
    (("ppi",),      {"spy": 1.00, "qtum": 0.92, "qbts": 1.12, "label": "PPI 大盘×1.0(实测不动)"}),
    (("core pce", "pce price index"),
     {"spy": 1.14, "qtum": 0.89, "qbts": 0.87, "label": "PCE 大盘×1.14(ns)"}),
    (("gdp",),      {"spy": 0.96, "qtum": 1.01, "qbts": 0.86, "label": "GDP 大盘×0.96(实测不动)"}),
    (("retail sales",),
     {"spy": 1.13, "qtum": 0.94, "qbts": 0.90, "label": "零售 大盘×1.13(ns)"}),
    (("jolts",),    {"spy": 1.10, "qtum": 1.08, "qbts": 1.00, "label": "JOLTS 大盘×1.1(ns)"}),
)


def _impact_coef(title: str) -> dict | None:
    t = title.lower()
    for pats, coef in _IMPACT_COEF:
        if any(p in t for p in pats):
            return coef
    return None


def _is_nuclear(title: str) -> bool:
    t = title.lower()
    return any(p in t for p in _NUCLEAR_PATTERNS)


def _fetch_raw() -> list[dict]:
    out: list[dict] = []
    for url in _URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=10) as r:
                out.extend(json.loads(r.read()))
        except Exception as e:
            logger.warning(f"macro calendar fetch failed for {url}: {e}")
    return out


def get_macro_calendar(force_refresh: bool = False) -> dict:
    """
    Returns:
      {
        "as_of": iso,
        "events":  [ {date, time_et, title, impact, forecast, previous, actual, nuclear} ... ],
        "nuclear": [ same shape, subset ],
        "risk_window": bool,        # nuclear event within next 48h
        "risk_note":  str,          # human-readable summary of the window
      }
    """
    # Cache
    if not force_refresh and _CACHE_PATH.exists():
        try:
            cached = json.loads(_CACHE_PATH.read_text())
            if time.time() - cached.get("_ts", 0) < _CACHE_SECONDS:
                return cached["payload"]
        except Exception:
            pass

    raw = _fetch_raw()
    # ALL comparisons in UTC. FF timestamps carry an ET offset
    # ("2026-06-10T08:30:00-04:00"); the user's machine may be in any
    # timezone (e.g. AEST, +14h vs ET) — naive local comparison silently
    # misclassifies "tonight's CPI" as already released.
    now_utc = datetime.now(timezone.utc)
    horizon = now_utc + timedelta(days=14)

    # Feed failed (rate-limit / outage)? Serve the previous cache rather than
    # overwriting it with a degraded FOMC-only payload.
    if not raw and _CACHE_PATH.exists():
        try:
            cached = json.loads(_CACHE_PATH.read_text())
            logger.warning("macro feed unavailable — serving stale cache")
            return cached["payload"]
        except Exception:
            pass

    def _mk_event(dt_aware: datetime, title: str, impact: str,
                  forecast: str = "", previous: str = "",
                  actual: str = "") -> dict:
        dt_utc = dt_aware.astimezone(timezone.utc)
        hours_until = round((dt_utc - now_utc).total_seconds() / 3600, 1)
        return {
            "date":        dt_aware.strftime("%Y-%m-%d"),   # ET calendar date
            "time_et":     dt_aware.strftime("%H:%M"),
            "title":       title,
            "impact":      impact,
            "forecast":    forecast,
            "previous":    previous,
            "actual":      actual,             # filled by FF after release — 实际值
            "nuclear":     _is_nuclear(title),
            "coef":        _impact_coef(title),  # 第十五轮实测影响系数(None=未测)
            "hours_until": hours_until,        # negative = already released
            "_utc":        dt_utc.isoformat(), # internal, for window math
        }

    events: list[dict] = []
    for e in raw:
        if e.get("country") != "USD":
            continue
        if e.get("impact") not in ("High", "Medium"):
            continue
        try:
            dt = datetime.fromisoformat(e.get("date") or "")  # aware (ET offset)
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone(timedelta(hours=-4)))
        dt_utc = dt.astimezone(timezone.utc)
        # Keep 24h of look-back: yesterday's release WITH its actual value is
        # exactly the context the decision engine needs ("CPI came in hot at
        # 4.3% and the stock fell 10%" beats not knowing why it fell).
        if dt_utc < now_utc - timedelta(hours=24) or dt_utc > horizon:
            continue
        events.append(_mk_event(dt, e.get("title", ""), e.get("impact"),
                                e.get("forecast") or "", e.get("previous") or "",
                                e.get("actual") or ""))

    # Inject hardcoded FOMC dates within horizon (FF feed only covers this week).
    # 14:00 ET; ET offset is -4 during DST (Mar-Nov meetings) else -5.
    for d in _FOMC_2026:
        try:
            month = int(d[5:7])
            et_offset = timezone(timedelta(hours=-5 if month in (1, 2, 12) else -4))
            dt = datetime.strptime(d, "%Y-%m-%d").replace(
                hour=14, minute=0, tzinfo=et_offset)
        except Exception:
            continue
        dt_utc = dt.astimezone(timezone.utc)
        if now_utc - timedelta(hours=12) <= dt_utc <= horizon:
            events.append(_mk_event(dt, "FOMC 利率决议 + 鲍威尔记者会", "High"))

    # Dedup (overlap between feed and hardcoded FOMC) + sort
    seen = set()
    deduped = []
    for ev in sorted(events, key=lambda x: (x["date"], x["time_et"])):
        # FOMC dedup: any feed event on an FOMC date containing rate/fomc
        key = (ev["date"], "FOMC") if ("fomc" in ev["title"].lower()
                                        or "federal funds" in ev["title"].lower()) \
              else (ev["date"], ev["title"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ev)

    # Backfill actual values for past releases from FRED (the FF feed never
    # carries them). No-op without FRED_API_KEY; only shows self-validated values.
    try:
        try:
            from dashboard.fred import enrich_actuals          # runtime (backend/ on path)
        except ImportError:
            from backend.dashboard.fred import enrich_actuals  # repo-root on path
        enrich_actuals(deduped)
    except Exception as ex:
        logger.warning(f"FRED enrichment skipped: {ex}")

    nuclear = [e for e in deduped if e["nuclear"]]

    # Risk window: any nuclear event still UPCOMING within the next 48h
    # (hours_until between -2 and 48 — the -2 grace keeps a just-released
    # print flagged while the market digests it).
    in_window = [e for e in nuclear if -2 <= e["hours_until"] <= 48]

    risk_window = len(in_window) > 0
    if risk_window:
        descs = []
        for ev in dict.fromkeys(ev["title"] for ev in in_window):
            h = next(e["hours_until"] for e in in_window if e["title"] == ev)
            descs.append(f"{ev}（{abs(h):.0f}小时{'后发布' if h >= 0 else '前已发布'}）")
        risk_note = ("未来48小时重磅数据：" + "、".join(descs)
                     + " — 实测宏观日只放大大盘/板块波动(QBTS 单票系数≈1.0)，"
                       "别提前恐惧；数据落地后看大盘反应再定方向")
    else:
        nxt = next((e for e in nuclear if e["hours_until"] > 0), None)
        risk_note = (f"下一个重磅数据：{nxt['date']} {nxt['title']}（约{nxt['hours_until']/24:.0f}天后）"
                     if nxt else "未来14天无重磅宏观数据")

    # Strip internal field before persisting/serving
    for e in deduped:
        e.pop("_utc", None)

    payload = {
        "as_of":       now_utc.astimezone().strftime("%Y-%m-%d %H:%M"),
        "events":      deduped,
        "nuclear":     [e for e in deduped if e["nuclear"]],
        "risk_window": risk_window,
        "risk_note":   risk_note,
    }
    try:
        _CACHE_PATH.write_text(json.dumps({"_ts": time.time(), "payload": payload},
                                           ensure_ascii=False))
    except Exception:
        pass
    return payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cal = get_macro_calendar(force_refresh=True)
    print(f"as_of: {cal['as_of']}  risk_window: {cal['risk_window']}")
    print(f"note: {cal['risk_note']}")
    print(f"\n核弹级事件 ({len(cal['nuclear'])}):")
    for e in cal["nuclear"]:
        print(f"  {e['date']} {e['time_et']}ET [{e['impact']}] {e['title']} "
              f"(预测 {e['forecast'] or '-'} / 前值 {e['previous'] or '-'})")
