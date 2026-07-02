"""
Alternative Data Pipeline — Phase 3a.

Three data sources beyond OHLCV:

  1. ETF FLOW (QBTX/QBTZ leveraged ETF volume)
       Direct read on retail leverage demand. When QBTX (quantum-bull-2x)
       volume spikes vs QBTZ (quantum-bear-2x), retail is FOMO-buying;
       when QBTZ dominates, retail is panicking. Free via yfinance.

  2. EARNINGS CALENDAR (QBTS reporting dates)
       Post-earnings drift + pre-earnings vol expansion are persistent
       single-stock anomalies. days_to_earnings as a continuous feature.

  3. FINRA SHORT VOLUME (daily short sale ratio)
       Real-time short pressure. High short ratio + price strength = squeeze
       setup. Free daily files from FINRA's reg_sho directory.

Each fetcher caches to backend/data/cache/ and degrades gracefully when
the source is unavailable (filled with neutral defaults — no crashes).
"""

from __future__ import annotations

import logging
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent / "cache"
_CACHE_DIR.mkdir(exist_ok=True)

_ETF_CACHE       = _CACHE_DIR / "etf_flow.parquet"
_EARNINGS_CACHE  = _CACHE_DIR / "qbts_earnings.parquet"
_SHORT_CACHE     = _CACHE_DIR / "finra_short_qbts.parquet"

_CACHE_HOURS_ETF      = 24
_CACHE_HOURS_EARNINGS = 24 * 7        # weekly refresh
_CACHE_HOURS_SHORT    = 12

_FINRA_USER_AGENT = "QBTS-Miner research@qbts-miner.local"
_SHORT_FETCH_DAYS = 365                # ~1 trading year of FINRA history
_SHORT_FETCH_WORKERS = 8


# ── 1. ETF flow (QBTX / QBTZ) ────────────────────────────────────────────────

def _cache_age_hours(path: Path) -> float:
    if not path.exists():
        return float("inf")
    return (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 3600


def fetch_etf_flow(force_refresh: bool = False) -> pd.DataFrame:
    """
    Returns DataFrame indexed by date with columns:
      qbtx_vol, qbtz_vol     — daily share volume
      qbtx_close, qbtz_close — daily close price (for live target conversion)
    Falls back to empty DataFrame if yfinance is unavailable.
    """
    if not force_refresh and _cache_age_hours(_ETF_CACHE) < _CACHE_HOURS_ETF:
        try:
            cached = pd.read_parquet(_ETF_CACHE)
            # Schema-aware: if close columns missing (old cache), force re-fetch
            if "qbtx_close" in cached.columns or "qbtz_close" in cached.columns:
                return cached
        except Exception:
            pass

    try:
        raw = yf.download(
            ["QBTX", "QBTZ"], period="2y", interval="1d",
            progress=False, auto_adjust=True, group_by="ticker",
        )
        if raw.empty:
            return pd.DataFrame()

        out = pd.DataFrame(index=raw.index)
        for sym in ("QBTX", "QBTZ"):
            sl = sym.lower()
            if (sym, "Volume") in raw.columns:
                out[f"{sl}_vol"]   = raw[(sym, "Volume")].fillna(0).astype(float)
            else:
                out[f"{sl}_vol"]   = 0.0
            if (sym, "Close") in raw.columns:
                out[f"{sl}_close"] = raw[(sym, "Close")].ffill().astype(float)
            else:
                out[f"{sl}_close"] = float("nan")

        if out.index.tz is not None:
            out.index = out.index.tz_convert("America/New_York").tz_localize(None)
        out.index.name = "datetime"
        out.to_parquet(_ETF_CACHE)
        latest_qbtx = out["qbtx_close"].dropna().iloc[-1] if "qbtx_close" in out and out["qbtx_close"].notna().any() else float("nan")
        latest_qbtz = out["qbtz_close"].dropna().iloc[-1] if "qbtz_close" in out and out["qbtz_close"].notna().any() else float("nan")
        logger.info(
            f"ETF flow: QBTX {(out['qbtx_vol'] > 0).sum()}d (${latest_qbtx:.2f}), "
            f"QBTZ {(out['qbtz_vol'] > 0).sum()}d (${latest_qbtz:.2f})"
        )
        return out
    except Exception as e:
        logger.warning(f"ETF flow fetch failed: {e}")
        return pd.DataFrame()


def get_latest_etf_prices() -> dict:
    """Return latest available close prices for QBTX and QBTZ."""
    etf = fetch_etf_flow()
    if etf.empty:
        return {"qbtx": None, "qbtz": None}
    def _latest(col: str):
        if col not in etf.columns:
            return None
        s = etf[col].dropna()
        return round(float(s.iloc[-1]), 2) if not s.empty else None
    return {"qbtx": _latest("qbtx_close"), "qbtz": _latest("qbtz_close")}


def add_etf_flow_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds:
      etf_long_share — QBTX_vol / (QBTX_vol + QBTZ_vol), in [0,1]
                       0.7+ = retail FOMO bullish, 0.3- = bearish panic, 0.5 = neutral
      etf_flow_z     — z-score of combined ETF volume vs 20-day rolling mean
                       high = unusual retail attention (signal-worthy regime)
    """
    df = df.copy()
    etf = fetch_etf_flow()
    if etf.empty:
        df["etf_long_share"] = 0.5
        df["etf_flow_z"]     = 0.0
        return df

    dates  = df.index.normalize()
    qbtx_v = etf["qbtx_vol"].reindex(dates, method="ffill").fillna(0).values
    qbtz_v = etf["qbtz_vol"].reindex(dates, method="ffill").fillna(0).values
    total  = qbtx_v + qbtz_v

    long_share = np.where(total > 0, qbtx_v / np.maximum(total, 1), 0.5)
    total_ser  = pd.Series(total, index=df.index)
    roll_mean  = total_ser.rolling(20).mean().replace(0, np.nan)
    roll_std   = total_ser.rolling(20).std().replace(0, np.nan)
    flow_z     = ((total_ser - roll_mean) / roll_std).fillna(0).clip(-5, 5)

    df["etf_long_share"] = long_share.round(4)
    df["etf_flow_z"]     = flow_z.round(3).values
    return df


# ── 2. Earnings calendar ─────────────────────────────────────────────────────

def fetch_earnings_dates(force_refresh: bool = False) -> list[datetime]:
    """Returns sorted list of historical+future QBTS earnings dates."""
    if not force_refresh and _cache_age_hours(_EARNINGS_CACHE) < _CACHE_HOURS_EARNINGS:
        try:
            df = pd.read_parquet(_EARNINGS_CACHE)
            return sorted(pd.to_datetime(df["date"]).tolist())
        except Exception:
            pass

    try:
        ed = yf.Ticker("QBTS").earnings_dates
        if ed is None or ed.empty:
            return []
        dates = sorted(ed.index.tz_localize(None).normalize().tolist())
        pd.DataFrame({"date": dates}).to_parquet(_EARNINGS_CACHE)
        logger.info(f"QBTS earnings: {len(dates)} dates fetched (range {dates[0].date()} → {dates[-1].date()})")
        return dates
    except Exception as e:
        logger.warning(f"Earnings fetch failed: {e}")
        if _EARNINGS_CACHE.exists():
            try:
                df = pd.read_parquet(_EARNINGS_CACHE)
                return sorted(pd.to_datetime(df["date"]).tolist())
            except Exception:
                pass
        return []


def add_earnings_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds:
      days_to_earnings  — signed days to *next* earnings (positive = future).
                          Capped at +/- 60. NaN-filled by neutral 60.
      earnings_window   — 1 if bar is within ±3 days of an earnings date, else 0
    """
    df = df.copy()
    dates = fetch_earnings_dates()
    if not dates:
        df["days_to_earnings"] = 60
        df["earnings_window"]  = 0
        return df

    ed_idx = pd.DatetimeIndex(dates).normalize()
    bar_d  = df.index.normalize()

    dte = []
    for d in bar_d:
        future = ed_idx[ed_idx >= d]
        if len(future) == 0:
            dte.append(60)
            continue
        delta = int((future[0] - d).days)
        dte.append(min(delta, 60))

    df["days_to_earnings"] = dte
    df["earnings_window"]  = (df["days_to_earnings"].abs() <= 3).astype(int)
    return df


# ── 3. FINRA daily short volume ──────────────────────────────────────────────

def _finra_url(date: datetime) -> str:
    return f"https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date.strftime('%Y%m%d')}.txt"


def _fetch_short_for_date(date: datetime) -> tuple[datetime, float, float] | None:
    """Return (date, short_vol, total_vol) for QBTS on `date` or None on failure."""
    try:
        req = urllib.request.Request(_finra_url(date), headers={"User-Agent": _FINRA_USER_AGENT})
        with urllib.request.urlopen(req, timeout=8) as resp:
            for line in resp.read().decode(errors="ignore").splitlines():
                if "|QBTS|" in line:
                    parts = line.split("|")
                    if len(parts) >= 5:
                        return date, float(parts[2]), float(parts[4])
    except Exception:
        return None
    return None


def _read_short_cache() -> pd.DataFrame:
    """Read the FINRA cache, with index normalised to midnight (no time component)."""
    if not _SHORT_CACHE.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(_SHORT_CACHE)
        df.index = pd.DatetimeIndex(df.index).normalize()
        return df[~df.index.duplicated(keep="last")].sort_index()
    except Exception:
        return pd.DataFrame()


def fetch_short_volume(
    force_refresh: bool = False,
    n_days: int = _SHORT_FETCH_DAYS,
    allow_network: bool = True,
) -> pd.DataFrame:
    """
    Returns DataFrame indexed by date with columns: short_vol, total_vol, short_ratio.

    allow_network=False → SERVING PATH: return whatever is cached immediately,
    never hit the network (so request handlers never block on a 50s FINRA fetch).
    allow_network=True  → REFRESH PATH: incrementally fetch only the missing
    recent business days (normalised date matching, so it grabs ~5 not 365).
    """
    cached = _read_short_cache()

    # Serving path: never block on network.
    if not allow_network:
        return cached

    # Fresh enough? return as-is.
    if not force_refresh and not cached.empty and _cache_age_hours(_SHORT_CACHE) < _CACHE_HOURS_SHORT:
        return cached

    end_date   = datetime.today()
    start_date = end_date - timedelta(days=int(n_days * 1.4))
    all_days   = pd.date_range(start_date, end_date, freq="B").normalize()

    have     = set(cached.index) if not cached.empty else set()
    to_fetch = [d.to_pydatetime() for d in all_days if d not in have]
    if not to_fetch:
        # nothing new — touch the cache file mtime so the TTL resets
        if not cached.empty:
            cached.to_parquet(_SHORT_CACHE)
        return cached

    logger.info(f"FINRA short volume: fetching {len(to_fetch)} new dates (parallel)…")
    results: list[tuple[datetime, float, float]] = []
    with ThreadPoolExecutor(max_workers=_SHORT_FETCH_WORKERS) as ex:
        futures = {ex.submit(_fetch_short_for_date, d): d for d in to_fetch}
        for f in as_completed(futures):
            r = f.result()
            if r is not None:
                results.append(r)

    if not results:
        return cached  # network failed — keep what we had

    new_df = pd.DataFrame(
        results, columns=["datetime", "short_vol", "total_vol"]
    )
    new_df["datetime"] = pd.DatetimeIndex(new_df["datetime"]).normalize()
    new_df = new_df.set_index("datetime").sort_index()
    new_df["short_ratio"] = (new_df["short_vol"] / new_df["total_vol"].replace(0, np.nan)).fillna(0).round(4)

    combined = pd.concat([cached, new_df]) if not cached.empty else new_df
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    combined.to_parquet(_SHORT_CACHE)
    logger.info(
        f"FINRA short volume: +{len(results)} new, {len(combined)} total cached rows"
    )
    return combined


def refresh_short_volume() -> int:
    """Incrementally refresh the FINRA cache (blocking). Returns total rows cached.
    Call this at mining-session start, NOT during dashboard serving."""
    df = fetch_short_volume(allow_network=True)
    return len(df)


# ── Supabase persistence (so the FINRA cache survives stateless cloud runs) ───
# Lambda's /tmp is wiped on every cold start, and the cache is only ever
# network-refreshed in the local mining path — so without this the cloud has NO
# FINRA data and the squeeze's short component shows "短仓数据缺失". We mirror the
# journal/calibration pattern: keep the cache in a `finra_short` table, restore it
# at publish, refresh only the missing recent days, push the result back.

def short_cache_records() -> list[dict]:
    """Dump the FINRA short cache to JSON-safe records for Supabase."""
    df = _read_short_cache()
    if df.empty:
        return []
    out = df.copy()
    out.index = pd.DatetimeIndex(out.index).strftime("%Y-%m-%d")
    out = out.reset_index()
    out.columns = ["date"] + list(out.columns[1:])
    return [{"date": str(r["date"]),
             "short_vol":   float(r.get("short_vol", 0) or 0),
             "total_vol":   float(r.get("total_vol", 0) or 0),
             "short_ratio": float(r.get("short_ratio", 0) or 0)}
            for r in out.to_dict("records")]


def seed_short_cache(records: list[dict]) -> None:
    """Restore the cache file from Supabase records IF there's no local cache yet
    (e.g. a fresh Lambda /tmp). Never clobbers an existing/fresher local cache."""
    if not records or _SHORT_CACHE.exists():
        return
    try:
        df = pd.DataFrame(records)
        df["datetime"] = pd.DatetimeIndex(df["date"]).normalize()
        df = df.drop(columns=["date"]).set_index("datetime").sort_index()
        _SHORT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(_SHORT_CACHE)
    except Exception as e:
        logger.warning(f"seed_short_cache failed: {e}")


def sync_short_volume(sb, n_days: int = 150) -> int:
    """Cloud-safe FINRA refresh: restore cache from Supabase → incrementally fetch
    only the missing recent days → push the result back. `sb` is a Supabase client
    (passed in so this module stays supabase-free). Returns total cached rows."""
    table = "finra_short"
    try:
        rows = sb.table(table).select("data").eq("id", "current").execute().data
        if rows and rows[0].get("data"):
            seed_short_cache(rows[0]["data"])
    except Exception as e:
        logger.warning(f"finra restore from supabase failed: {e}")
    # force_refresh bypasses the 12h TTL (the seeded file looks fresh) but the
    # to_fetch logic still only grabs dates not already cached → incremental.
    df = fetch_short_volume(allow_network=True, force_refresh=True, n_days=n_days)
    try:
        sb.table(table).upsert({"id": "current", "data": short_cache_records()}).execute()
    except Exception as e:
        logger.warning(f"finra push to supabase failed: {e}")
    return len(df)


def add_short_interest_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds:
      short_ratio       — daily short volume / total volume (FINRA), 0..1
      short_ratio_5d    — 5-day rolling avg (smoother regime indicator)
      short_pressure_z  — z-score of short_ratio vs 60-day window (anomaly detector)

    Uses cache-only (allow_network=False) so enrichment NEVER blocks on FINRA.
    The cache is refreshed separately via refresh_short_volume() at mining start.
    """
    df = df.copy()
    short = fetch_short_volume(allow_network=False)   # never blocks
    if short.empty:
        df["short_ratio"]      = 0.0
        df["short_ratio_5d"]   = 0.0
        df["short_pressure_z"] = 0.0
        return df

    dates = df.index.normalize()
    sr    = short["short_ratio"].reindex(dates, method="ffill").fillna(0)

    df["short_ratio"]    = sr.round(4).values
    df["short_ratio_5d"] = sr.rolling(5, min_periods=1).mean().round(4).values

    roll_mean = sr.rolling(60, min_periods=20).mean()
    roll_std  = sr.rolling(60, min_periods=20).std().replace(0, np.nan)
    z         = ((sr - roll_mean) / roll_std).fillna(0).clip(-5, 5)
    df["short_pressure_z"] = z.round(3).values
    return df


# ── Public composite ─────────────────────────────────────────────────────────

def add_all_altdata_features(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all three alt-data feature sets in sequence."""
    df = add_etf_flow_features(df)
    df = add_earnings_features(df)
    df = add_short_interest_features(df)
    return df


def altdata_health_check(refresh: bool = False) -> dict:
    """Returns the latest status of each alt-data source for the startup log.

    refresh=True → incrementally refresh the FINRA short cache (blocking, used at
    mining-session start). refresh=False → cache-only (used for dashboard serving).
    """
    etf      = fetch_etf_flow()
    earnings = fetch_earnings_dates()
    short    = fetch_short_volume(allow_network=refresh)
    return {
        "etf":      {"rows": len(etf),      "ok": not etf.empty},
        "earnings": {"rows": len(earnings), "ok": len(earnings) > 0},
        "short":    {"rows": len(short),    "ok": not short.empty},
    }


# ── SEC EDGAR: 增发/稀释文件叠加(免费,无需 key)──────────────────────────────
# 机械扫描看不见公司层面的供给冲击(增发、货架登记、ATM)——但这些都必须报备 SEC,
# 所以 EDGAR 一定有。我们只拉每家"最近文件清单",标记近 N 天内出现的稀释类文件:
#   424B2/B3/B4/B5 = 实际增发定价(强信号) · S-1/S-3/S-3ASR/EFFECT = 登记/货架(有弹药)。
# 免费接口,但 SEC 要求带 User-Agent;任何失败都安静返回 None,绝不影响扫描。
import json as _json
import os as _os

# SEC 要求 UA 带"邮箱形式"的联系方式,否则 403(不会校验邮箱真伪)。沿用 FINRA 的伪域名。
_SEC_USER_AGENT  = _os.getenv("SEC_USER_AGENT", "qbts-quant-lab research@qbts-quant-lab.local")
_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_DILUTION_OFFERING = {"424B5", "424B4", "424B3", "424B2"}                  # actual takedown/offering
_DILUTION_SHELF    = {"S-3", "S-3/A", "S-3ASR", "S-1", "S-1/A", "EFFECT"}  # registered capacity
_cik_map: "dict[str, int] | None" = None


def _sec_get(url: str, timeout: int = 8) -> "bytes | None":
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                import gzip
                raw = gzip.decompress(raw)
            return raw
    except Exception:
        return None


def _sec_cik(ticker: str) -> "int | None":
    """Ticker → SEC CIK (cached for the process). SEC's company_tickers.json maps both."""
    global _cik_map
    if _cik_map is None:
        raw = _sec_get(_SEC_TICKERS_URL)
        _cik_map = {}
        if raw:
            try:
                for row in _json.loads(raw).values():
                    _cik_map[row["ticker"].upper()] = int(row["cik_str"])
            except Exception:
                _cik_map = {}
    return _cik_map.get(ticker.upper())


def fetch_sec_dilution(ticker: str, offering_days: int = 120, shelf_days: int = 365) -> "dict | None":
    """Recent dilution-relevant SEC filings for `ticker`.

    Two windows by relevance: an actual offering (424B*) matters while recent
    (`offering_days`); a shelf/registration (S-3/S-1) stays loaded ammunition for
    up to ~3 years, so we use a longer `shelf_days` window — but not so long that
    every company's ancient effective shelf over-flags.

    Returns {risk, level('high'|'warn'), recent:[{form,date}], note} or None when
    there are none / the lookup fails. 'high' = an actual offering was filed;
    'warn' = only registered capacity. Event-aware backstop for the otherwise
    event-blind mechanical scan — informational, not a trade signal.
    """
    cik = _sec_cik(ticker)
    if cik is None:
        return None
    raw = _sec_get(_SEC_SUBMISSIONS.format(cik=cik))
    if not raw:
        return None
    try:
        recent = _json.loads(raw)["filings"]["recent"]
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
    except Exception:
        return None

    today = datetime.now().date()
    off_cut   = today - timedelta(days=offering_days)
    shelf_cut = today - timedelta(days=shelf_days)
    hits: list[dict] = []
    for form, ds in zip(forms, dates):
        f = (form or "").upper()
        try:
            d = datetime.fromisoformat(ds).date()
        except Exception:
            continue
        if f in _DILUTION_OFFERING and d >= off_cut:
            hits.append({"form": f, "date": ds, "kind": "offering"})
        elif f in _DILUTION_SHELF and d >= shelf_cut:
            hits.append({"form": f, "date": ds, "kind": "shelf"})
    if not hits:
        return None
    hits.sort(key=lambda h: h["date"], reverse=True)
    has_offering = any(h["kind"] == "offering" for h in hits)
    # Age of the most-recent relevant filing — a 5-month-old shelf is background,
    # not a current catalyst; without decay the prompt over-weights stale events.
    latest = datetime.fromisoformat(hits[0]["date"]).date()
    age_days = (today - latest).days
    mo = age_days / 30.0
    if has_offering:
        note = (f"{age_days}天前实际增发定价(424B),新股供给正在/刚冲击 —— 买点上方真实稀释,做多打折"
                if age_days <= 30 else
                f"{age_days}天前的增发(424B,约{mo:.0f}个月前),供给冲击多已消化,作背景")
    else:
        note = (f"{age_days}天前刚登记货架(S-3 等),增发弹药新就位、随时可能发,关注"
                if age_days <= 45 else
                f"货架登记已 {age_days} 天(约{mo:.0f}个月前)、期间未实际增发 —— 只是注册容量,"
                f"属陈旧背景而非当前催化,权重应低")
    return {"risk": True, "level": "high" if has_offering else "warn",
            "age_days": age_days,
            "recent": [{"form": h["form"], "date": h["date"]} for h in hits[:4]],
            "note": note}


# ── Adanos retail sentiment (Reddit buzz + sentiment) ─────────────────────────
# Replaces the dead Reddit signal — Reddit's own API is approval-gated + bans AI use
# since 2026-06, and keyless StockTwits/Reddit .json are 403-blocked. Adanos is a
# free-tier aggregator: 250 req/mo (daily publish uses ~30). Needs ADANOS_API_KEY
# (sk_live_…, free at adanos.org/register); returns None without it, so it degrades
# cleanly. Fields: buzz_score 0-100 (attention/velocity), sentiment_score -1..+1.
_ADANOS_BASE = "https://api.adanos.org"


def fetch_adanos_sentiment(ticker: str = "QBTS") -> "dict | None":
    """Reddit retail buzz + sentiment for `ticker` from Adanos.

    Verified response is flat top-level: buzz_score 0-100 (attention/velocity),
    sentiment_score -1..+1, trend rising/falling/stable, mentions, bullish_pct/
    bearish_pct, period_days. Returns {buzz_score, sentiment_score, trend,
    mentions, bullish_pct, bearish_pct, signal(-1/0/1), note} or None when no
    ADANOS_API_KEY is set or the lookup fails (informational, not a trade
    trigger — graded by the ledger like every other signal).
    """
    key = _os.getenv("ADANOS_API_KEY")
    if not key:
        return None
    url = f"{_ADANOS_BASE}/reddit/stocks/v1/stock/{ticker.upper()}"
    try:
        req = urllib.request.Request(url, headers={
            "X-API-Key": key, "Accept-Encoding": "gzip, deflate"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                import gzip
                raw = gzip.decompress(raw)
        data = _json.loads(raw)
    except Exception as e:
        logging.warning(f"adanos fetch failed for {ticker}: {e}")
        return None

    def _num(k):
        v = data.get(k)
        return float(v) if isinstance(v, (int, float)) else None
    buzz, sent = _num("buzz_score"), _num("sentiment_score")
    mentions   = data.get("mentions")
    bull, bear = data.get("bullish_pct"), data.get("bearish_pct")
    trend      = data.get("trend")

    # Mild directional tilt: sentiment sign gated by real attention (buzz), so a
    # near-zero-buzz reading doesn't vote. Thresholds intentionally conservative.
    signal = 0
    if sent is not None and (buzz is None or buzz >= 20):
        if sent >= 0.15:
            signal = 1
        elif sent <= -0.15:
            signal = -1
    bp = f"（多{bull}%/空{bear}%，{mentions}提及）" if bull is not None else ""
    note = (f"散户情绪 {sent:+.2f}{bp}" if sent is not None else "情绪缺失") + \
           (f" · 热度 {buzz:.0f}/100" if buzz is not None else "") + \
           (f" · {trend}" if isinstance(trend, str) else "")
    return {"buzz_score": buzz, "sentiment_score": sent, "trend": trend,
            "mentions": mentions, "bullish_pct": bull, "bearish_pct": bear,
            "signal": signal, "note": note}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    status = altdata_health_check()
    for src, info in status.items():
        flag = "✓" if info["ok"] else "✗"
        print(f"  {flag} {src:10s}: {info['rows']} rows")
