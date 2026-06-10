"""
SEC EDGAR 8-K filing dates for QBTS (D-Wave Quantum Inc.).

Adds two features to the enriched DataFrame:
  days_since_8k  - calendar days since the last 8-K filing (capped at 60)
  news_flag      - 1 if an 8-K was filed within 3 calendar days, else 0
"""

import json
import logging
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_EDGAR_CIK  = "0001907982"   # D-Wave Quantum Inc. (QBTS) — verified via EDGAR search
_CACHE_PATH = Path(__file__).parent / "cache" / "edgar_8k.parquet"
_CACHE_HOURS = 24


def _fetch_edgar_filings() -> list[str]:
    """Pull all 8-K filing dates from EDGAR submissions JSON."""
    url = f"https://data.sec.gov/submissions/CIK{_EDGAR_CIK}.json"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "QBTS-Miner research@qbts-miner.local"},
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode())

    recent   = data.get("filings", {}).get("recent", {})
    forms    = recent.get("form", [])
    dates    = recent.get("filingDate", [])
    return [d for f, d in zip(forms, dates) if f == "8-K"]


def get_8k_dates(force_refresh: bool = False) -> list[datetime]:
    """Return sorted list of 8-K filing datetimes for QBTS."""
    if not force_refresh and _CACHE_PATH.exists():
        age_h = (datetime.now() - datetime.fromtimestamp(_CACHE_PATH.stat().st_mtime)).total_seconds() / 3600
        if age_h < _CACHE_HOURS:
            try:
                df = pd.read_parquet(_CACHE_PATH)
                return sorted(pd.to_datetime(df["date"]).tolist())
            except Exception:
                pass

    try:
        date_strs = _fetch_edgar_filings()
        dates     = sorted(pd.to_datetime(date_strs).tolist())
        if not dates:
            logger.error(
                f"EDGAR returned 0 8-K filings for CIK {_EDGAR_CIK} — "
                "check CIK is correct at https://www.sec.gov/cgi-bin/browse-edgar"
                "?action=getcompany&CIK=0001816898&type=8-K"
            )
        else:
            logger.info(f"EDGAR 8-K fetched: {len(dates)} filings, latest={dates[-1].date()}")
        _CACHE_PATH.parent.mkdir(exist_ok=True)
        pd.DataFrame({"date": dates}).to_parquet(_CACHE_PATH)
        return dates
    except Exception as e:
        logger.error(f"EDGAR fetch failed: {e} — news_flag will be 0 for all bars")
        if _CACHE_PATH.exists():
            try:
                df = pd.read_parquet(_CACHE_PATH)
                return sorted(pd.to_datetime(df["date"]).tolist())
            except Exception:
                pass
        return []


def add_news_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add 8-K event features to df (works for both daily and hourly).
    days_since_8k is computed based on calendar days to filing date.
    """
    df = df.copy()
    dates_8k = get_8k_dates()

    if not dates_8k:
        df["days_since_8k"] = 60
        df["news_flag"]     = 0
        return df

    filing_ts = pd.DatetimeIndex(dates_8k).normalize()
    bar_dates  = df.index.normalize()

    days_since = []
    for d in bar_dates:
        past = filing_ts[filing_ts <= d]
        if len(past) == 0:
            days_since.append(60)
        else:
            days_since.append(min(int((d - past[-1]).days), 60))

    df["days_since_8k"] = days_since
    df["news_flag"]     = (df["days_since_8k"] <= 1).astype(int)

    return df


if __name__ == "__main__":
    dates = get_8k_dates(force_refresh=True)
    print(f"Fetched {len(dates)} 8-K dates for QBTS")
    for d in dates[-10:]:
        print(f"  {d.date()}")
