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
                     + " — 高beta股波动放大，建议降低仓位或等数据落地再确认方向")
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
