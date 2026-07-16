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

**Plus a hard reference-period check (`_ref_ok`, added 2026-07-16)**: the value
tolerance alone was defeated on 2026-07-15 — 33 min after the PPI release FRED
still held May as its latest obs; May's pre-revision print (1.1%) happened to
equal the feed's `previous`, the adjacent-month values sat inside the tolerance,
and last month's number was published as today's actual (the decision prompt
then showed "✅已公布 实际 1.1%" for a release whose true print was −0.3%).
Values can coincide; periods cannot — the latest obs must be the exact reference
period of the release (monthly first-prints: event month −1; UoM: same month;
GDP: 3–5 months; weekly claims: ≤10 days).

Consequence: first-print weekly/monthly series (Core PCE, CPI, PPI, NFP,
unemployment claims, UoM *preliminary*) validate cleanly and show. SAME-period
REVISIONS (Final GDP, Revised UoM) won't validate — their feed `previous` is the
earlier estimate of the SAME period, while FRED stores one value per period — so
by design they stay blank. That's the safe trade-off.

No new dependency: stdlib urllib only. Degrades to a no-op without FRED_API_KEY.
"""

from __future__ import annotations

import datetime as _dt
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
    # core PPI: PPIFES/WPSFD4131 都对不齐 FF 的口径(2026-07 实测 May 0.1%/0.3%
    # vs FF 前值 0.4%) — 显式不支持,防止落到 headline PPIFIS
    (("core ppi",),                       None,                "pch", "pct"),
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
_TOL = {"pct": 0.15, "claims": 5000.0, "num": 1.0}   # jobs 不走值容差 → 参考期日期精确校验


def _ref_ok(series: str, kind: str, ev_date: _dt.date, latest_date: str) -> bool:
    """参考期校验:FRED 最新观测必须是本次发布对应的数据期。

    值容差挡不住"FRED 未更新 → 上期值冒充今日实际"(2026-07-15 PPI 事故:发布后
    33 分钟 FRED 还停在 5 月,5 月旧口径 1.1% 恰好等于 feed 前值,期错位骗过值校验,
    决策 prompt 拿上月值当今日实际)。期数是硬校验:一期都不能错。"""
    try:
        od = _dt.date.fromisoformat(latest_date)
    except ValueError:
        return False
    if kind == "claims":                      # 周度:上周六截止,发布滞后 ~5 天
        return 0 < (ev_date - od).days <= 10
    if series in ("UMCSENT", "MICH"):         # 密歇根:当月中旬发当月
        lo = hi = 0
    elif series == "A191RL1Q225SBEA":         # GDP:季度,advance/second/final 滞后 3-5 月
        lo, hi = 3, 5
    else:                                     # 月度首发(CPI/PPI/PCE/零售/时薪/失业率/非农)
        lo = hi = 1
    lag = (ev_date.year - od.year) * 12 + (ev_date.month - od.month)
    return lo <= lag <= hi


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


def _fetch_obs(series: str, units: str) -> list[tuple[str, float]]:
    """Latest two (obs_date, value) pairs (newest first), FRED transform applied."""
    qs = urllib.parse.urlencode({
        "series_id": series, "api_key": _KEY, "file_type": "json",
        "sort_order": "desc", "limit": 2, "units": units,
    })
    req = urllib.request.Request(f"{_BASE}?{qs}", headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    out: list[tuple[str, float]] = []
    for o in data.get("observations", []):
        try:
            out.append((str(o.get("date", "")), float(o["value"])))  # "." for missing → ValueError
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
            ev_date = _dt.date.fromisoformat(str(e.get("date", ""))[:10])
        except ValueError:
            continue
        try:
            obs = cache.get(series)
            if obs is None:
                obs = _fetch_obs(series, units)
                cache[series] = obs
            if len(obs) < 2:
                continue
            (latest_date, latest), (_, prev) = obs[0], obs[1]
            # 参考期硬校验(全系列):FRED 未更新时最新观测=上一期,值容差挡不住
            # (07-15 PPI 事故),期错位一律拒。
            if not _ref_ok(series, kind, ev_date, latest_date):
                continue
            if kind == "jobs":
                # 非农月修 40-100K 是常态 — 值容差会把合法修正当错期拒掉
                # (实例 2026-07:5月 172K 下修至 129K)。期校验已在上面,直接采纳。
                e["actual"] = _fmt(latest, kind)
                continue
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
