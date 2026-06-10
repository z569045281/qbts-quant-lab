"""
DataFrame enricher — adds pre-computed technical features and peer-relative columns.

Columns added to df:
  Technical (always available):
    atr_14        - Average True Range (14-bar), normalized by close
    rsi_14        - RSI (14-bar), range 0-100
    bb_width      - Bollinger Band width = (upper-lower)/mid (20-bar, 2σ)
    bb_pct        - %B: where close sits within the Bollinger Bands
    vwap_dev      - Deviation of close from rolling 20-bar VWAP (%)
    vol_ratio     - Current volume vs 20-bar avg volume
    vol_ratio_5   - Current volume vs 5-bar avg volume
    momentum_5    - 5-bar price return
    momentum_10   - 10-bar price return
    momentum_20   - 20-bar price return
    hl_pct        - (high - low) / close — intrabar range
    gap           - open / prev_close - 1 (gap up/down at open)

  Peer relative strength (daily only, zeros for hourly if peers unavailable):
    ionq_ret_1    - IONQ 1-day return (quantum peer)
    rgti_ret_1    - Rigetti 1-day return (quantum peer)
    qqq_ret_1     - QQQ 1-day return (tech proxy)
    vix           - VIX closing level (fear gauge)
    rel_ionq      - QBTS 1d return minus IONQ 1d return (relative strength)
    rel_qqq       - QBTS 1d return minus QQQ 1d return

  SEC EDGAR event features:
    days_since_8k - calendar days since last 8-K filing (capped at 60)
    news_flag     - 1 if an 8-K was filed on this day or yesterday, else 0

  Alt-data features (Phase 3a):
    etf_long_share   - QBTX_vol / (QBTX+QBTZ vol), [0,1]; 0.7+ = retail FOMO bullish
    etf_flow_z       - z-score of total ETF volume vs 20d avg; signals unusual retail attention
    days_to_earnings - signed days to next earnings (capped ±60)
    earnings_window  - 1 if within ±3 days of earnings, else 0
    short_ratio      - FINRA daily short volume / total volume; high = short pressure
    short_ratio_5d   - 5-day smoothed short ratio (regime indicator)
    short_pressure_z - z-score of short_ratio vs 60-day window (anomaly detector)
"""

import numpy as np
import pandas as pd
import yfinance as yf
import logging
from pathlib import Path
from datetime import datetime, timedelta

from data.news    import add_news_features
from data.altdata import add_all_altdata_features
from data.kalman  import kalman_local_linear_trend, kalman_hedge_ratio, rolling_zscore

logger = logging.getLogger(__name__)

_PEER_CACHE = Path(__file__).parent / "cache" / "peers_1d.parquet"
_PEER_TICKERS = ["IONQ", "RGTI", "QQQ", "^VIX"]


# ── Technical features ────────────────────────────────────────────────────────

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def add_technical_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # ATR (14)
    hl   = df["high"] - df["low"]
    hc   = (df["high"] - df["close"].shift(1)).abs()
    lc   = (df["low"]  - df["close"].shift(1)).abs()
    tr   = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr  = tr.ewm(span=14, adjust=False).mean()
    df["atr_14"] = (atr / df["close"]).round(4)

    # RSI (14)
    df["rsi_14"] = _rsi(df["close"], 14).round(2)

    # Bollinger Bands (20, 2σ)
    mid      = df["close"].rolling(20).mean()
    std      = df["close"].rolling(20).std()
    upper    = mid + 2 * std
    lower    = mid - 2 * std
    bb_width = (upper - lower) / mid
    bb_pct   = (df["close"] - lower) / (upper - lower)
    df["bb_width"] = bb_width.round(4)
    df["bb_pct"]   = bb_pct.clip(0, 1).round(4)

    # VWAP deviation (rolling 20-bar)
    typical   = (df["high"] + df["low"] + df["close"]) / 3
    cum_tp_v  = (typical * df["volume"]).rolling(20).sum()
    cum_v     = df["volume"].rolling(20).sum().replace(0, np.nan)
    vwap      = cum_tp_v / cum_v
    df["vwap_dev"] = ((df["close"] - vwap) / vwap).round(4)

    # Volume ratios
    vol_ma20     = df["volume"].rolling(20).mean().replace(0, np.nan)
    vol_ma5      = df["volume"].rolling(5).mean().replace(0, np.nan)
    df["vol_ratio"]   = (df["volume"] / vol_ma20).round(3)
    df["vol_ratio_5"] = (df["volume"] / vol_ma5).round(3)

    # Momentum
    df["momentum_5"]  = df["close"].pct_change(5).round(4)
    df["momentum_10"] = df["close"].pct_change(10).round(4)
    df["momentum_20"] = df["close"].pct_change(20).round(4)

    # Intrabar range
    df["hl_pct"] = ((df["high"] - df["low"]) / df["close"]).round(4)

    # Gap at open
    df["gap"] = (df["open"] / df["close"].shift(1) - 1).round(4)

    # Fill any NaN introduced by rolling with 0 (safe default)
    new_cols = ["atr_14","rsi_14","bb_width","bb_pct","vwap_dev",
                "vol_ratio","vol_ratio_5","momentum_5","momentum_10",
                "momentum_20","hl_pct","gap"]
    df[new_cols] = df[new_cols].fillna(0)

    return df


# ── Peer data ─────────────────────────────────────────────────────────────────

def _fetch_peers(force_refresh: bool = False) -> pd.DataFrame | None:
    if not force_refresh and _PEER_CACHE.exists():
        age_hours = (datetime.now() - datetime.fromtimestamp(_PEER_CACHE.stat().st_mtime)).total_seconds() / 3600
        if age_hours < 8:
            return pd.read_parquet(_PEER_CACHE)

    try:
        end   = datetime.today()
        start = end - timedelta(days=365 * 2)
        raw   = yf.download(
            _PEER_TICKERS,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
        if raw.empty:
            return None

        # Extract close prices
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw.xs("Close", level=0, axis=1)
        else:
            close = raw[["Close"]]

        close.columns = [c.lower().replace("^", "") for c in close.columns]
        if close.index.tz is not None:
            close.index = close.index.tz_convert("America/New_York").tz_localize(None)
        close.index.name = "datetime"
        close.ffill(inplace=True)

        _PEER_CACHE.parent.mkdir(exist_ok=True)
        close.to_parquet(_PEER_CACHE)
        logger.info(f"Peer data fetched: {list(close.columns)}, {len(close)} rows")
        return close
    except Exception as e:
        logger.warning(f"Peer fetch failed: {e}")
        return None


def add_peer_features(df: pd.DataFrame, freq: str = "1d") -> pd.DataFrame:
    """
    Merge peer relative-strength columns into df.
    For hourly data, daily peer values are forward-filled to each hour of that day.
    """
    df = df.copy()

    peer_cols = ["ionq_ret_1", "rgti_ret_1", "qqq_ret_1", "vix", "rel_ionq", "rel_qqq"]
    for c in peer_cols:
        df[c] = 0.0

    peers = _fetch_peers()
    if peers is None:
        return df

    peer_ret = peers.pct_change()

    if freq == "1d":
        qbts_ret = df["close"].pct_change()
        aligned  = peer_ret.reindex(df.index, method="ffill")
        vix_lvl  = peers.get("vix", pd.Series(dtype=float)).reindex(df.index, method="ffill")
    else:
        # Hourly: map each hour to its trading date, then pull daily peer values
        dates = df.index.normalize()                        # floor to midnight
        qbts_daily = df["close"].resample("1D").last().pct_change()
        qbts_ret   = qbts_daily.reindex(dates).values      # align by position

        # Shift by 1 day to avoid look-ahead: hourly bars at 10am must not see
        # the full same-day peer return (which isn't known until market close).
        peer_ret_lagged = peer_ret.shift(1)
        aligned = pd.DataFrame(index=df.index)
        for col in peer_ret.columns:
            daily_vals = peer_ret_lagged[col].reindex(dates, method="ffill")
            aligned[col] = daily_vals.values

        if "vix" in peers.columns:
            vix_lvl = pd.Series(
                peers["vix"].reindex(dates, method="ffill").values,
                index=df.index,
            )
        else:
            vix_lvl = pd.Series(0.0, index=df.index)

        qbts_ret = pd.Series(
            qbts_daily.reindex(dates, method="ffill").values,
            index=df.index,
        )

    if "ionq" in aligned.columns:
        df["ionq_ret_1"] = aligned["ionq"].values
        df["rel_ionq"]   = (qbts_ret.values - aligned["ionq"].values).round(4)
    if "rgti" in aligned.columns:
        df["rgti_ret_1"] = aligned["rgti"].values
    if "qqq" in aligned.columns:
        df["qqq_ret_1"] = aligned["qqq"].values
        df["rel_qqq"]   = (qbts_ret.values - aligned["qqq"].values).round(4)

    df["vix"] = vix_lvl.values if hasattr(vix_lvl, "values") else vix_lvl

    for c in peer_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).round(4)

    logger.info(f"Peer features added ({freq}): {peer_cols}")
    return df


# ── Main entry point ──────────────────────────────────────────────────────────

def add_kalman_features(df: pd.DataFrame, freq: str = "1d") -> pd.DataFrame:
    """
    Kalman-filter features (causal, no look-ahead):
      kf_velocity  - denoised fractional momentum (LLT velocity / close)
      kf_residual  - (close - KF level) / close; price vs KF fair value (mean-reversion)
      kf_beta      - dynamic hedge ratio QBTS~IONQ (random-walk Kalman); 0 if peer N/A
      kf_spread_z  - z-score of the QBTS~IONQ Kalman spread (pairs mean-reversion)
    """
    df = df.copy()

    # 1) Local-linear-trend on QBTS close — works for both daily & hourly
    level, vel = kalman_local_linear_trend(df["close"].values)
    close = df["close"].values
    df["kf_velocity"] = np.where(close > 0, vel / close, 0.0).round(5)
    df["kf_residual"] = np.where(close > 0, (close - level) / close, 0.0).round(5)

    # 2) Dynamic hedge ratio vs IONQ — needs aligned peer prices (daily basis)
    df["kf_beta"]     = 0.0
    df["kf_spread_z"] = 0.0
    try:
        peers = _fetch_peers()
        if peers is not None and "ionq" in peers.columns:
            dates = df.index.normalize()
            ionq  = peers["ionq"].reindex(dates, method="ffill").values
            if np.isfinite(ionq).sum() > 30:
                _, beta, spread = kalman_hedge_ratio(close, ionq)
                df["kf_beta"]     = np.nan_to_num(beta).round(4)
                df["kf_spread_z"] = rolling_zscore(spread, window=20).round(3)
    except Exception as e:
        logger.warning(f"Kalman pairs feature failed: {e}")

    return df


def enrich(df: pd.DataFrame, freq: str = "1d") -> pd.DataFrame:
    """Add all technical + peer + SEC news + alt-data + Kalman features."""
    df = add_technical_features(df)
    df = add_peer_features(df, freq=freq)
    df = add_news_features(df)
    df = add_all_altdata_features(df)
    df = add_kalman_features(df, freq=freq)
    return df
