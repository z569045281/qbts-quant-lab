"""
FRED actual-value enrichment for the macro calendar.

faireconomy's FF JSON feed (see macro.py) carries forecast/previous only — it
NEVER fills the actual released print (verified: even 2-day-old events stay
actual=null). This module backfills `actual` for past events from FRED
(St. Louis Fed, free API key in env var FRED_API_KEY).

Safety model — self-validation, never show a wrong number
--------------------------------------------------------
For each past event we map the FF title → a FRED series + transform, then fetch
the two most recent observations. We accept FRED's LATEST value as `actual`
ONLY IF FRED's PREVIOUS observation is CLOSE to the feed's `previous` value
(within a per-kind tolerance that absorbs routine data revisions / rounding,
but not a whole-period offset). A mismatch — wrong series, transform misaligned,
FRED not yet updated minutes after the release, or a same-period revision whose
feed `previous` is the earlier estimate — means we skip silently; the card shows
no actual rather than a wrong one.

Consequence: first-print weekly/monthly series (Core PCE, CPI, PPI, NFP,
unemployment claims, UoM *preliminary*) validate cleanly and show. SAME-period
REVISIONS (Final GDP, Revised UoM) won't validate — their feed `previous` is the
earlier estimate of the SAME period, while FRED stores one value per period — so
by design they stay blank. That's the safe trade-off.

No new dependency: stdlib urllib only. Degrades to a no-op without FRED_API_KEY.
"""

from __future__ import annotations

import logging
import os
import urllib.parse
import urllib.request
import json

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_KEY = os.getenv("FRED_API_KEY")
_BASE = "https://api.stlouisfed.org/fred/series/observations"
_UA = "Mozilla/5.0 (QBTS-Quant-Lab/1.0)"

# FF title (lowercased substring) → (series_id, fred_units, kind).
# ORDER MATTERS: more specific patterns first ("core cpi" before "cpi",
# "gdp price index" before "gdp"). First substring hit wins.
#   fred_units: "lin" = level as-is · "pch" = % change vs prior period
#               · "chg" = change in level vs prior period
#   kind (display + parse): "pct" one-decimal % · "claims" level→K
#               · "jobs" thousands→K · "num" one-decimal number
#   series_id None = explicitly unsupported (skip; stops a looser pattern from
#   capturing it — e.g. "gdp price index" must not fall through to real GDP).
_FRED_MAP: list[tuple[tuple[str, ...], str | None, str, str]] = [
    (("core pce",),                       "PCEPILFE",          "pch", "pct"),
    (("pce price index", "pce"),          "PCEPI",             "pch", "pct"),
    (("core cpi",),                       "CPILFESL",          "pch", "pct"),
    (("cpi",),                            "CPIAUCSL",          "pch", "pct"),
    (("ppi",),                            "PPIFIS",            "pch", "pct"),
    (("gdp price index",),                None,                "lin", "pct"),
    (("final gdp", "gdp"),                "A191RL1Q225SBEA",   "lin", "pct"),
    (("unemployment claims", "jobless claims", "initial claims"),
                                          "ICSA",              "lin", "claims"),
    (("unemployment rate",),              "UNRATE",            "lin", "pct"),
    (("non-farm", "nonfarm", "employment change"),
                                          "PAYEMS",            "chg", "jobs"),
    (("average hourly earnings",),        "CES0500000003",     "pch", "pct"),
    (("retail sales",),                   "RSAFS",             "pch", "pct"),
    (("consumer sentiment", "michigan sentiment"),
                                          "UMCSENT",           "lin", "num"),
    (("inflation expectations",),         "MICH",              "lin", "pct"),
]

# Per-kind tolerance for the `previous`-match check: big enough to absorb routine
# revisions/rounding between FF and FRED, small enough to reject a same-period
# revision (whose feed `previous` is a whole period away from FRED's prior obs).
_TOL = {"pct": 0.15, "claims": 5000.0, "jobs": 40000.0, "num": 1.0}


def _match(title: str) -> tuple[str, str, str] | None:
    t = title.lower()
    for patterns, series, units, kind in _FRED_MAP:
        if any(p in t for p in patterns):
            return (series, units, kind) if series else None
    return None


def _fmt(v: float, kind: str) -> str:
    if kind == "pct":
        return f"{round(v, 1):.1f}%"
    if kind == "claims":
        return f"{round(v / 1000):d}K"
    if kind == "jobs":
        return f"{round(v):d}K"
    if kind == "num":
        return f"{round(v, 1):.1f}"
    return str(v)


def _num(s: str) -> float | None:
    """Parse a display value ('0.2%', '226K', '48.9') to a comparable float."""
    if not s:
        return None
    s = s.strip().upper().replace(",", "")
    mult = 1.0
    if s.endswith("K"):
        mult, s = 1000.0, s[:-1]
    if s.endswith("%"):
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def _fetch_obs(series: str, units: str) -> list[float]:
    """Latest two observations (newest first), with the FRED transform applied."""
    qs = urllib.parse.urlencode({
        "series_id": series, "api_key": _KEY, "file_type": "json",
        "sort_order": "desc", "limit": 2, "units": units,
    })
    req = urllib.request.Request(f"{_BASE}?{qs}", headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    out: list[float] = []
    for o in data.get("observations", []):
        try:
            out.append(float(o["value"]))   # FRED uses "." for missing → ValueError
        except (KeyError, ValueError):
            continue
    return out


def enrich_actuals(events: list[dict]) -> None:
    """
    Mutate `events` in place, filling `actual` for past releases that validate
    against FRED. No-op without FRED_API_KEY or on any network/parse error.
    """
    if not _KEY:
        return
    cache: dict[str, list[float]] = {}
    for e in events:
        if e.get("actual"):                      # feed (unexpectedly) had it
            continue
        if (e.get("hours_until") or 0) >= 0:      # not released yet
            continue
        m = _match(e.get("title", ""))
        if not m:
            continue
        series, units, kind = m
        try:
            obs = cache.get(series)
            if obs is None:
                obs = _fetch_obs(series, units)
                cache[series] = obs
            if len(obs) < 2:
                continue
            latest, prev = obs[0], obs[1]
            ff_prev = _num(e.get("previous", ""))
            fred_prev = _num(_fmt(prev, kind))
            # Self-validation: FRED's previous obs must be close to the feed's
            # previous (tolerance absorbs revisions/rounding, rejects offsets).
            if ff_prev is None or fred_prev is None:
                continue
            if abs(ff_prev - fred_prev) > _TOL.get(kind, 0.0):
                continue
            e["actual"] = _fmt(latest, kind)
        except Exception as ex:  # network/JSON/parse — degrade to no actual
            logger.warning(f"FRED enrich failed for {series} ({e.get('title')}): {ex}")
            continue
