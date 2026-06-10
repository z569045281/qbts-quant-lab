"""
Macro economic calendar — CPI / PPI / FOMC / NFP and friends.

QBTS is a high-beta, long-duration small-cap: macro liquidity expectations move
it MORE than its own news on data days. A hot CPI print can sink the quantum
basket 5-10% regardless of company fundamentals. The dashboard was blind to
this — this module closes the gap.

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
from datetime import datetime, timedelta
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
_NUCLEAR_PATTERNS = (
    "cpi", "ppi", "fomc", "federal funds rate", "non-farm", "nonfarm",
    "core pce", "pce price index", "gdp", "jackson hole", "press conference",
)


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
        "events":  [ {date, time_et, title, impact, forecast, previous, nuclear} ... ],
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
    now = datetime.now()
    horizon = now + timedelta(days=14)

    # Feed failed (rate-limit / outage)? Serve the previous cache rather than
    # overwriting it with a degraded FOMC-only payload.
    if not raw and _CACHE_PATH.exists():
        try:
            cached = json.loads(_CACHE_PATH.read_text())
            logger.warning("macro feed unavailable — serving stale cache")
            return cached["payload"]
        except Exception:
            pass

    events: list[dict] = []
    for e in raw:
        if e.get("country") != "USD":
            continue
        if e.get("impact") not in ("High", "Medium"):
            continue
        # FF dates look like "2026-06-10T08:30:00-04:00" (ET with offset)
        date_str = (e.get("date") or "")[:16]
        try:
            dt = datetime.fromisoformat(date_str)
        except Exception:
            continue
        if dt < now - timedelta(hours=12) or dt > horizon:
            continue
        title = e.get("title", "")
        events.append({
            "date":     dt.strftime("%Y-%m-%d"),
            "time_et":  dt.strftime("%H:%M"),
            "title":    title,
            "impact":   e.get("impact"),
            "forecast": e.get("forecast") or "",
            "previous": e.get("previous") or "",
            "nuclear":  _is_nuclear(title),
        })

    # Inject hardcoded FOMC dates within horizon (FF feed only covers this week)
    for d in _FOMC_2026:
        try:
            dt = datetime.strptime(d, "%Y-%m-%d").replace(hour=14, minute=0)
        except Exception:
            continue
        if now - timedelta(hours=12) <= dt <= horizon:
            events.append({
                "date": d, "time_et": "14:00",
                "title": "FOMC 利率决议 + 鲍威尔记者会",
                "impact": "High", "forecast": "", "previous": "",
                "nuclear": True,
            })

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

    nuclear = [e for e in deduped if e["nuclear"]]

    # Risk window: any nuclear event in next 48h (including today's not-yet-released)
    win_end = now + timedelta(hours=48)
    in_window = []
    for e in nuclear:
        try:
            dt = datetime.strptime(f"{e['date']} {e['time_et']}", "%Y-%m-%d %H:%M")
        except Exception:
            continue
        if now - timedelta(hours=6) <= dt <= win_end:
            in_window.append(e)

    risk_window = len(in_window) > 0
    if risk_window:
        names = "、".join(dict.fromkeys(ev["title"] for ev in in_window))
        risk_note = f"未来48小时内有重磅宏观数据：{names} — 高beta股波动放大，建议降低仓位或等数据落地"
    else:
        nxt = nuclear[0] if nuclear else None
        risk_note = (f"下一个重磅数据：{nxt['date']} {nxt['title']}" if nxt
                     else "未来14天无重磅宏观数据")

    payload = {
        "as_of":       now.strftime("%Y-%m-%d %H:%M"),
        "events":      deduped,
        "nuclear":     nuclear,
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
