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

_MARKET_CLOSE_HOUR_ET = 16


def _last_session_close_et() -> datetime:
    """最近一次美股收盘时刻(ET,naive)。周末回退到周五。

    **不查节假日**是有意的:节假日会让这个时刻落在一个没有交易的日子上,后果只是
    缓存多刷一次(刷完文件时间就晚于它,之后照常命中),不会反复空刷。
    """
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    close = now.replace(hour=_MARKET_CLOSE_HOUR_ET, minute=0, second=0, microsecond=0)
    if now < close:
        close -= timedelta(days=1)
    while close.weekday() > 4:          # 周六/周日 → 回退到周五
        close -= timedelta(days=1)
    return close


# 上游给出坏 bar 时的记录(api.py 读它,让自检/决策看得见数据源出过问题)。
LAST_FETCH_ISSUES: list[str] = []


def _bad_ohlcv_rows(df: pd.DataFrame) -> pd.Index:
    """违反 OHLC 硬不变式的行。**这些不是"可疑",是数学上不可能的**:

        low ≤ min(open, close) ≤ max(open, close) ≤ high,  且 high ≥ low > 0

    所以零误报 —— 一只票连续两天收在同一价位是正常的,但收盘价掉到当日最低价
    **之下**永远不正常。

    2026-07-28 实例:yfinance 一度把 QBTS 07-28 这行给成
    `open 18.70 / high 18.89 / low 17.26 / close 16.21` —— 16.21 恰是 **07-24
    的收盘价**被贴了进来,比当日最低价还低 1.05。真实收盘 17.64(30m bar、
    盘后连续报价、Alpaca 夜盘盘口三方一致)。若这根被写进缓存,%R / RSI /
    SMC 折价区 / 200日线全部会基于一个不存在的价格,而且**没有任何下游能发现**。
    """
    o, h, l, c = (df[k].astype(float) for k in ("open", "high", "low", "close"))
    bad = (
        (h < l)
        | (c < l) | (c > h)
        | (o < l) | (o > h)
        | (l <= 0)
        | o.isna() | h.isna() | l.isna() | c.isna()
    )
    return df.index[bad]


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
    # ⚠️ 剔除本身是对的,但**不能静默** —— 被剔掉的如果是最新那根,as_of 会无声
    # 倒退一天,页面照常绿油油。2026-07-29 实例:yfinance 把 07-24 的收盘 16.21
    # 贴进 07-28 那行(低于当日 low 17.26),这里剔掉后 as_of 从 07-28 退回 07-27,
    # 而真实收盘 17.64 三方可证。所以记进 LAST_FETCH_ISSUES 交给上层处理。
    bad = _bad_ohlcv_rows(df)          # 不变式只此一处定义,别再写第二份
    if len(bad):
        det = ", ".join(
            f"{i:%Y-%m-%d %H:%M} O{df.at[i,'open']:.2f}/H{df.at[i,'high']:.2f}"
            f"/L{df.at[i,'low']:.2f}/C{df.at[i,'close']:.2f}" for i in bad[-3:])
        msg = f"{freq} 上游返回 {len(bad)} 根违反 OHLC 不变式的 bar,已剔除: {det}"
        logger.error(msg)
        LAST_FETCH_ISSUES.append(msg)
        df = df.drop(index=bad)

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


def fetch_15m(ticker: str = TICKER, days: int = 58) -> pd.DataFrame:
    """
    15-minute bars for the SMC 'trigger' timeframe (15m CHoCH + WaveTrend dot).
    yfinance caps intraday <1h at ~60 calendar days, so we clamp to 58.
    """
    days = min(days, 58)
    end = datetime.today() + timedelta(days=1)   # `end` exclusive — +1d to include today
    start = end - timedelta(days=days)
    logger.info(f"Fetching 15m {start.date()} → {end.date()}")
    raw = yf.download(
        ticker,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval="15m",
        auto_adjust=True,
        progress=False,
    )
    if raw.empty:
        raise RuntimeError(f"No 15m data returned for {ticker}")
    return _clean_ohlcv(raw, "15m")


def load_15m(ticker: str = TICKER, force_refresh: bool = False) -> pd.DataFrame | None:
    """
    15m bars, cached to its own Parquet (separate from the (1h,1d) tuple so the
    widely-used load_or_fetch contract is untouched). Returns None on failure —
    the SMC trigger gracefully degrades to 'cannot confirm' rather than erroring.
    """
    m_path = DATA_DIR / f"{ticker}_15m.parquet"
    try:
        cache_stale = False
        if m_path.exists():
            age_hours = (datetime.now() - datetime.fromtimestamp(m_path.stat().st_mtime)).total_seconds() / 3600
            if age_hours > 24:
                logger.info(f"15m cache is {age_hours:.1f}h old — refreshing")
                cache_stale = True
        if not force_refresh and not cache_stale and m_path.exists():
            return pd.read_parquet(m_path)
        df_m = fetch_15m(ticker)
        df_m.to_parquet(m_path)
        return df_m
    except Exception as e:
        logger.warning(f"load_15m failed ({e}); 15m trigger will be unavailable")
        if m_path.exists():
            try:
                return pd.read_parquet(m_path)   # fall back to stale cache if present
            except Exception:
                return None
        return None


_REBUILD_MIN_BARS = 4      # 一个常规交易日 6.5 小时 → 至少 4 根才认为覆盖够
_REBUILD_MAX_DAYS = 5      # 只补最近几天;更早的缺口交给缓存,别改写历史


def _rebuild_daily_from_hourly(df_d: pd.DataFrame, df_h: pd.DataFrame) -> pd.DataFrame:
    """日线缺了某天、而小时线有那天 → 用小时线聚合出这根日线。

    只补**最近 `_REBUILD_MAX_DAYS` 天**内的缺口(更早的缺口可能是真实停牌/假期,
    改写历史比缺一天更危险),且要求当天至少 `_REBUILD_MIN_BARS` 根小时线
    —— 半天数据聚出来的"收盘"不是收盘。重建结果**必须自己通过同一套 OHLC
    不变式**,否则宁可继续缺着(坏数据进缓存后没有任何下游能发现)。

    重建的 volume 是当日小时线之和:盘前盘后不在 1h 常规序列里,所以它会略低于
    官方日成交量。**量能类读数据此会偏小**,已在 LAST_FETCH_ISSUES 里写明。
    """
    if df_d is None or df_h is None or not len(df_d) or not len(df_h):
        return df_d
    try:
        h_days = pd.DatetimeIndex(df_h.index).normalize()
        d_days = set(pd.DatetimeIndex(df_d.index).normalize())
        recent = sorted({d for d in h_days if d not in d_days})[-_REBUILD_MAX_DAYS:]
        if not recent:
            return df_d
        # 只补不早于现有日线最后一根的缺口 —— 往前补历史不是本函数的职责
        last_d = pd.DatetimeIndex(df_d.index).normalize()[-1]
        rows = {}
        for day in recent:
            if day < last_d:
                continue
            chunk = df_h[h_days == day]
            if len(chunk) < _REBUILD_MIN_BARS:
                continue
            bar = {
                "open":   float(chunk["open"].iloc[0]),
                "high":   float(chunk["high"].max()),
                "low":    float(chunk["low"].min()),
                "close":  float(chunk["close"].iloc[-1]),
                "volume": float(chunk["volume"].sum()) if "volume" in chunk else 0.0,
            }
            probe = pd.DataFrame([bar], index=[day])
            if len(_bad_ohlcv_rows(probe)):        # 重建的也得过同一道闸
                continue
            rows[day] = bar
        if not rows:
            return df_d
        add = pd.DataFrame.from_dict(rows, orient="index")
        add = add.reindex(columns=df_d.columns, fill_value=0.0)
        out = pd.concat([df_d, add]).sort_index()
        det = ", ".join(f"{d:%m-%d} 收{rows[d]['close']:.2f}" for d in rows)
        msg = (f"日线缺 {len(rows)} 天(上游坏 bar 已剔),已用小时线重建: {det}"
               f" —— 成交量为 1h 之和,不含盘前盘后,量能读数偏小")
        logger.warning(msg)
        LAST_FETCH_ISSUES.append(msg)
        return out
    except Exception as e:                          # 重建失败 = 维持原样,绝不弄坏
        logger.warning(f"daily rebuild from hourly failed: {e}")
        return df_d


def load_or_fetch(ticker: str = TICKER, force_refresh: bool = False):
    """
    Returns (hourly_df, daily_df).
    Caches to Parquet; re-fetches if cache missing or force_refresh=True.
    """
    h_path = DATA_DIR / f"{ticker}_1h.parquet"
    d_path = DATA_DIR / f"{ticker}_1d.parquet"

    cache_stale = False
    if h_path.exists() and d_path.exists():
        # 判"新鲜"要按【日线的更新节奏】,不是按挂钟走了多久。旧实现用 age>24h,
        # 与"每交易日 16:00 ET 出一根新 bar"错配:周一 09:02 的定时发布写下缓存
        # (里面最新的 bar 是上周五),周一 21:33 再发布时它才 12.5 小时"新",于是
        # 整晚发出的 as_of 仍停在周五 —— 漏掉一整个交易日(2026-07-29 查实,
        # 线上 id 123/124 中招)。改成:缓存写入时刻早于最近一次收盘 → 过期。
        # ⚠️ 盘中不因此而刷新:日线最后一根是活的部分 bar,非强制调用方整天沿用
        # 写入时的快照(与旧行为一致);当前价由 api 的 _live_price_for_snapshot 负责。
        from zoneinfo import ZoneInfo
        oldest_mtime = min(h_path.stat().st_mtime, d_path.stat().st_mtime)
        written = (datetime.fromtimestamp(oldest_mtime, ZoneInfo("America/New_York"))
                   .replace(tzinfo=None))
        last_close = _last_session_close_et()
        if written < last_close:
            logger.info(f"Cache written {written:%Y-%m-%d %H:%M} ET, before last close "
                        f"{last_close:%Y-%m-%d %H:%M} ET — refreshing")
            cache_stale = True

    if not force_refresh and not cache_stale and h_path.exists() and d_path.exists():
        logger.info("Loading from cache…")
        df_h = pd.read_parquet(h_path)
        df_d = pd.read_parquet(d_path)
    else:
        logger.info("Fetching fresh data from Yahoo Finance…")
        LAST_FETCH_ISSUES.clear()      # 每次抓取重新计,别把上一轮的问题带过来
        df_h = fetch_hourly(ticker)
        df_d = fetch_daily(ticker)

        # ── 坏日线用小时线重建(2026-07-31)────────────────────────────
        # 剔掉坏 bar 是对的,但**剔掉 = 那一天整天消失**。2026-07-30 实测:
        # yfinance 又一次把一个陈旧收盘(16.21)贴进当日行,低于当日最低 16.71 →
        # 被剔 → 日线序列停在 07-29,而那天真实收盘 17.97、涨了 11%。
        # 后果是所有日线派生读数(%R / RSI / SMC / 均线 / 特调扳机)全部少看一天。
        # 我们**手上就有**同一天的小时线,重建比丢弃诚实得多。
        df_d = _rebuild_daily_from_hourly(df_d, df_h)

        # ── 不许倒退(2026-07-29)──────────────────────────────────────
        # 坏 bar 已被 _clean_ohlcv 剔掉,但剔掉最新那根 = as_of 无声退回前一天。
        # 缓存里的 bar 是**写入时通过了同一套不变式的**,所以它比"没有"更可信:
        # 新抓的最后一根若比缓存还旧,就把缓存里多出来的那几根补回去。
        merged = {}
        for label, fresh, path in (("日线", df_d, d_path), ("小时线", df_h, h_path)):
            merged[label] = fresh
            if not path.exists() or not len(fresh):
                continue
            try:
                cached = pd.read_parquet(path)
            except Exception:
                continue
            if not len(cached) or cached.index[-1] <= fresh.index[-1]:
                continue
            keep = cached[cached.index > fresh.index[-1]]
            msg = (f"{label}上游最后一根退回到 {fresh.index[-1]:%m-%d},比缓存的 "
                   f"{cached.index[-1]:%m-%d} 还旧 → 补回缓存里的 {len(keep)} 根")
            logger.error(msg)
            LAST_FETCH_ISSUES.append(msg)
            merged[label] = pd.concat([fresh, keep]).sort_index()
        df_d, df_h = merged["日线"], merged["小时线"]

        df_h.to_parquet(h_path)
        df_d.to_parquet(d_path)
        logger.info("Saved to %s%s", DATA_DIR,
                    "" if not LAST_FETCH_ISSUES else f"  ⚠️ {len(LAST_FETCH_ISSUES)} 条数据源问题")

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
