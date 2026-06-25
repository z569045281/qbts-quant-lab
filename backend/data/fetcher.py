"""
QBTS Data Pipeline — Phase 1
Fetches 2 years of hourly + daily OHLCV data via yfinance.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TICKER = "QBTS"
DATA_DIR = Path(__file__).parent / "cache"
DATA_DIR.mkdir(exist_ok=True)


def _clean_ohlcv(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Normalize and clean raw yfinance DataFrame."""
    df = df.copy()

    # Flatten MultiIndex columns (yfinance sometimes returns them)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Lowercase columns
    df.columns = [c.lower() for c in df.columns]

    # Keep only OHLCV
    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")
    df = df[required]

    # Ensure DatetimeIndex with UTC → strip tz for uniform handling
    if df.index.tz is not None:
        df.index = df.index.tz_convert("America/New_York").tz_localize(None)

    df.index.name = "datetime"

    # Drop rows where all OHLCV are NaN
    df.dropna(how="all", inplace=True)

    # Forward-fill isolated gaps (max 3 periods) — common in hourly data
    df.ffill(limit=3, inplace=True)

    # Still-missing volume → 0 (halted sessions)
    df["volume"] = df["volume"].fillna(0)

    # Drop any remaining NaN rows
    df.dropna(inplace=True)

    # Sanity: high >= low, close within [low, high]
    bad_mask = (df["high"] < df["low"]) | (df["close"] < df["low"]) | (df["close"] > df["high"])
    n_bad = bad_mask.sum()
    if n_bad:
        logger.warning(f"Dropping {n_bad} rows with invalid OHLC relationships ({freq})")
        df = df[~bad_mask]

    # Ensure no negative prices
    price_cols = ["open", "high", "low", "close"]
    df = df[(df[price_cols] > 0).all(axis=1)]

    logger.info(f"[{freq}] Cleaned: {len(df)} rows, {df.index[0]} → {df.index[-1]}")
    return df


def fetch_hourly(ticker: str = TICKER, years: int = 2) -> pd.DataFrame:
    """
    yfinance caps 1h data at 730 days, so we fetch in 60-day windows
    and concatenate to avoid hitting the limit silently.
    """
    end = datetime.today() + timedelta(days=1)   # `end` is exclusive — +1d to include today
    start = end - timedelta(days=365 * years)

    chunks = []
    window_start = start
    while window_start < end:
        window_end = min(window_start + timedelta(days=59), end)
        logger.info(f"Fetching hourly {window_start.date()} → {window_end.date()}")
        chunk = yf.download(
            ticker,
            start=window_start.strftime("%Y-%m-%d"),
            end=window_end.strftime("%Y-%m-%d"),
            interval="1h",
            auto_adjust=True,
            progress=False,
        )
        if not chunk.empty:
            chunks.append(chunk)
        window_start = window_end + timedelta(days=1)

    if not chunks:
        raise RuntimeError(f"No hourly data returned for {ticker}")

    raw = pd.concat(chunks)
    raw = raw[~raw.index.duplicated(keep="first")]
    raw.sort_index(inplace=True)
    return _clean_ohlcv(raw, "1h")


def fetch_daily(ticker: str = TICKER, years: int = 2) -> pd.DataFrame:
    # yfinance `end` is EXCLUSIVE, so end=today drops today's (and, for a user ahead
    # of US time in AEST, the just-closed US) session — leaving as_of a day stale.
    # +1 day makes the latest available bar (live partial, or just-closed) show up.
    end = datetime.today() + timedelta(days=1)
    start = end - timedelta(days=365 * years)
    logger.info(f"Fetching daily {start.date()} → {end.date()}")
    raw = yf.download(
        ticker,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    if raw.empty:
        raise RuntimeError(f"No daily data returned for {ticker}")
    return _clean_ohlcv(raw, "1d")


def load_or_fetch(ticker: str = TICKER, force_refresh: bool = False):
    """
    Returns (hourly_df, daily_df).
    Caches to Parquet; re-fetches if cache missing or force_refresh=True.
    """
    h_path = DATA_DIR / f"{ticker}_1h.parquet"
    d_path = DATA_DIR / f"{ticker}_1d.parquet"

    cache_stale = False
    if h_path.exists() and d_path.exists():
        oldest_mtime = min(h_path.stat().st_mtime, d_path.stat().st_mtime)
        age_hours = (datetime.now() - datetime.fromtimestamp(oldest_mtime)).total_seconds() / 3600
        if age_hours > 24:
            logger.info(f"Cache is {age_hours:.1f}h old — refreshing")
            cache_stale = True

    if not force_refresh and not cache_stale and h_path.exists() and d_path.exists():
        logger.info("Loading from cache…")
        df_h = pd.read_parquet(h_path)
        df_d = pd.read_parquet(d_path)
    else:
        logger.info("Fetching fresh data from Yahoo Finance…")
        df_h = fetch_hourly(ticker)
        df_d = fetch_daily(ticker)
        df_h.to_parquet(h_path)
        df_d.to_parquet(d_path)
        logger.info(f"Saved to {DATA_DIR}")

    return df_h, df_d


def summary(df: pd.DataFrame, label: str) -> None:
    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")
    print(f"  Rows     : {len(df):,}")
    print(f"  Date range: {df.index[0]}  →  {df.index[-1]}")
    print(f"  Columns  : {list(df.columns)}")
    print(f"  NaN total: {df.isna().sum().sum()}")
    print(df.describe().round(4))


if __name__ == "__main__":
    df_hourly, df_daily = load_or_fetch(force_refresh=True)
    summary(df_hourly, "QBTS — Hourly (1h)")
    summary(df_daily,  "QBTS — Daily  (1d)")
