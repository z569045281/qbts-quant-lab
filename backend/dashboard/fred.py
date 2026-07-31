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
    # core retail sales: RSFSXMV 与 FF 口径对不齐(2026-07 实测 May 1.0% vs FF 前值
    # 0.8%) — 显式不支持,防落 headline RSAFS
    (("core retail sales",),              None,                "pch", "pct"),
    (("philly fed",),                     "GACDFSA066MSFRBPHI", "lin", "num"),
    (("consumer sentiment", "michigan sentiment"),
                                          "UMCSENT",           "lin", "num"),
    (("inflation expectations",),         "MICH",              "lin", "pct"),
    # 政策利率(2026-07-30 补):此前**根本没有这条映射** → FOMC 决议永远填不上实际值,
    # 前端只能打「已公布·待结果」挂在那儿(用户 07-30 报"显示已出结果但没数据",
    # 4 条里最刺眼的就是它——决议过了 19 小时还空着)。
    # DFEDTARU = Federal Funds Target Range 上限,日频、决议当日即生效
    # (实查 2026-07-30 = 3.75%,与 FF 的 forecast/previous 口径一致;
    #  EFFR/DFF 是"有效利率"3.63%,对不上 FF 显示的目标区间,不能用)。
    (("federal funds rate", "fomc statement", "interest rate decision"),
                                          "DFEDTARU",          "lin", "policy"),
]

# Per-kind tolerance for the `previous`-match check: big enough to absorb routine
# revisions/rounding between FF and FRED, small enough to reject a same-period
# revision (whose feed `previous` is a whole period away from FRED's prior obs).
_TOL = {"pct": 0.15, "claims": 5000.0, "num": 1.0,
        # policy:会前目标利率与 feed 的 previous 应当是同一个数,容差只留舍入余量。
        # 放宽到 0.15 会让"差 25bp"也算匹配,等于放弃这道自校验。
        "policy": 0.02}                              # jobs 不走值容差 → 参考期日期精确校验


def _ref_ok(series: str, kind: str, ev_date: _dt.date, latest_date: str) -> bool:
    """参考期校验:FRED 最新观测必须是本次发布对应的数据期。

    值容差挡不住"FRED 未更新 → 上期值冒充今日实际"(2026-07-15 PPI 事故:发布后
    33 分钟 FRED 还停在 5 月,5 月旧口径 1.1% 恰好等于 feed 前值,期错位骗过值校验,
    决策 prompt 拿上月值当今日实际)。期数是硬校验:一期都不能错。"""
    try:
        od = _dt.date.fromisoformat(latest_date)
    except ValueError:
        return False
    if kind == "policy":                      # 政策利率:决议当日生效,日频序列
        # 观测日必须落在会议日当天或之后几天(周末/假日会让下一条观测晚 1-3 天)。
        # 若 FRED 还停在会议日**之前**,说明这次决议还没落进序列 → 拒,别拿旧利率
        # 冒充今日结果(与 07-15 PPI 事故同一个防线)。
        return 0 <= (od - ev_date).days <= 4
    if kind == "claims":                      # 周度:上周六截止,发布滞后 ~5 天
        return 0 < (ev_date - od).days <= 10
    if series in ("UMCSENT", "MICH", "GACDFSA066MSFRBPHI"):  # 密歇根/费城联储:当月发当月
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


def coverage(title: str) -> str:
    """该标题在回填器里的覆盖状态 —— 用来让 UI 区分「还没到」和「永远不会到」。

    `_match` 对「显式不支持」(表里 series=None,如 core PPI / GDP 价格指数,
    口径对不齐故意不接)和「压根没映射」两种情况都返回 None,于是前端只能一律
    打「待结果」—— 用户 2026-07-30 报的就是这个:徽章说"已公布"却永远没数据,
    看起来像 bug,其实三种原因(会来 / 不会来 / 真漏了)长得一模一样。

      mapped      → 有 FRED 系列,值会在之后某次发布补上
      unsupported → 表里显式 None,免费源口径对不齐,**永远不会有值**
      unmapped    → 表里没有这条,同样不会有值(但属于可以补的缺口)
    """
    t = title.lower()
    for patterns, series, _units, _kind in _FRED_MAP:
        if any(p in t for p in patterns):
            return "mapped" if series else "unsupported"
    return "unmapped"


def _fmt(v: float, kind: str) -> str:
    if kind == "policy":
        # 政策利率报到 2 位(3.75%)—— 走 pct 的 1 位会印成 3.8%,与 FF 的口径对不上
        return f"{round(v, 2):.2f}%"
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


def _fetch_obs(series: str, units: str, limit: int = 2) -> list[tuple[str, float]]:
    """Latest `limit` (obs_date, value) pairs (newest first), FRED transform applied.

    月度/季度序列 2 条就够(本期 + 上期)。**日频序列不够** —— 政策利率要拿到
    "会议日之前那条"才能自校验,而会议日前一天可能是周末/假日,2 条只覆盖 2 天,
    `before` 必然为空、回填被静默跳过(2026-07-30 实测:FOMC 决议过了 19 小时
    仍是空值,根因就在这个 limit,不在映射表)。
    """
    qs = urllib.parse.urlencode({
        "series_id": series, "api_key": _KEY, "file_type": "json",
        "sort_order": "desc", "limit": limit, "units": units,
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

    同时给每条已过期的事件打 `actual_status`,让 UI 能说实话(见 `coverage`):
      released / pending(会来)/ no_source(永远不会来)。
    """
    def _stamp() -> None:
        """给已过期事件打状态。跑两次:回填前(没 key 时也要有状态)+ 回填后
        (刚填上的要从 pending 翻成 released)—— 比在三个赋值点各补一行可靠。"""
        for e in events:
            if e.get("actual"):
                e["actual_status"] = "released"
            elif (e.get("hours_until") or 0) < 0:
                e["actual_status"] = ("pending" if coverage(e.get("title", "")) == "mapped"
                                      else "no_source")

    _stamp()
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
                # 日频政策序列要多拉几条才能回溯到会议日之前(含周末/假日缓冲)
                obs = _fetch_obs(series, units, limit=15 if kind == "policy" else 2)
                cache[series] = obs
            if len(obs) < 2:
                continue
            (latest_date, latest), (_, prev) = obs[0], obs[1]
            # 参考期硬校验(全系列):FRED 未更新时最新观测=上一期,值容差挡不住
            # (07-15 PPI 事故),期错位一律拒。
            if not _ref_ok(series, kind, ev_date, latest_date):
                continue
            if kind == "policy":
                # 「前值」必须取会议日**之前**最后一条观测。日频序列里 obs[1] 只是
                # "昨天" —— 若这次决议当天就改了利率,obs[1] 已经是新利率,拿它做
                # 自校验会把一次**正确**的回填拒掉(降息/加息时必然发生)。
                before = [o for o in obs if o[0] < ev_date.isoformat()]
                if not before:
                    continue
                ff_p = _num(e.get("previous", ""))
                fred_p = _num(_fmt(before[0][1], kind))
                if ff_p is None or fred_p is None:
                    continue
                if abs(ff_p - fred_p) > _TOL["policy"]:
                    continue
                e["actual"] = _fmt(latest, kind)
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
    _stamp()    # 刚回填上的那些从 pending 翻成 released
