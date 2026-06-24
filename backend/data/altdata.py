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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    status = altdata_health_check()
    for src, info in status.items():
        flag = "✓" if info["ok"] else "✗"
        print(f"  {flag} {src:10s}: {info['rows']} rows")
