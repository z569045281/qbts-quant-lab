"""夜盘 15m bar —— 自己采样、自己聚合(2026-08-05,用户点单)。

起因:用户有券商夜盘权限(周日 20:00 ET 起可交易),而 SMC 卡在 20:00–04:00 ET
整段**冻结不动** —— `lambda_handlers.py` 的 `recompute` 闸门只放行
pre/regular/post。查下来这个闸门当时是对的:那段时间**根本没有任何 15m 数据源**。

已核实的三条死路(别再重试):
  · yfinance 15m       → 最后一根停在 15:45 ET
  · Alpaca `feed=iex`  → 同样停在 15:45 ET
  · Alpaca `feed=sip`  → 403,需付费订阅;且 SIP 本来也不覆盖 Blue Ocean 夜盘场
  · Alpaca `feed=overnight` → **只对 `/quotes/latest` 和 `/trades/latest` 有效**;
    `/bars?feed=overnight` 与 `/trades?feed=overnight` 都 400 `invalid feed`

所以唯一可行的是:QuoteFunction 每分钟本来就在拉夜盘 NBBO 中间价
(`quote_pusher.fetch_overnight`),把它**存下来自己聚合成 15m**。

━━ ⚠️ 它是合成 bar,不是真 bar ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ① 每分钟 1 个采样 → 分钟内的高低点丢失,**影线被削平**。真实 15m 的
     high/low 一定比这个宽,所以基于影线的判据(扫流动性/长下影)在夜盘不可信。
  ② 用的是 **NBBO 中间价**,不是成交价。夜盘价差很宽(实测 QBTS bid 22.00 /
     ask 22.11 ≈ 0.5%),中间价是最诚实的"当前标价",但它不等于你能成交的价。
  ③ **没有成交量** —— 报价不带 size。所以只有纯 OHLC 的模块能吃它;
     成交量画像/日内画像这类必须继续回退到日盘数据。

因此本模块产出的 bar 一律带 `synthetic=True`,`attach_overnight()` 会把这个标记
一路传到 SMC 读数里,让前端和推送能区别对待 —— **合成 bar 上的 15m CHoCH
默认不推 ntfy**(见 `intraday_smc`),先记账、够样本了再决定要不要给它开枪权。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_TABLE = "overnight_ticks"
_KEEP_DAYS = 3          # 15m 扳机只回看 ~12 根,留 3 天足够
_MIN_TICKS_PER_BAR = 5  # 一根 15m 至少要 5 个采样才算数(不足 1/3 覆盖 = 噪音)
_SB = None
_SB_INIT = False


def _supabase():
    global _SB, _SB_INIT
    if _SB_INIT:
        return _SB
    _SB_INIT = True
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if url and key:
        try:
            from supabase import create_client
            _SB = create_client(url, key)
        except Exception as e:
            logger.warning("overnight_bars: Supabase init failed — %s", e)
            _SB = None
    return _SB


def record_tick(ticker: str, price: float | None,
                bid: float | None = None, ask: float | None = None) -> bool:
    """存一个夜盘采样点。分钟对齐 —— 同一分钟重复调用不会重复写(表上有唯一约束)。

    返回是否真的落库。**不许静默失败**:这张表是空的话,聚合出来的 bar 也是空的,
    而 SMC 会安静地退回日盘数据 —— 那正是 08-05 之前的行为,查了半天才发现。
    """
    sb = _supabase()
    if sb is None or price is None:
        return False
    ts = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    row = {"ticker": ticker, "ts": ts.isoformat(), "price": float(price)}
    if bid is not None:
        row["bid"] = float(bid)
    if ask is not None:
        row["ask"] = float(ask)
    try:
        sb.table(_TABLE).upsert(row, on_conflict="ticker,ts").execute()
        return True
    except Exception as e:
        logger.warning("overnight_bars: record failed — %s", e)
        return False


def prune(days: int = _KEEP_DAYS) -> int:
    """删掉保留窗口之外的采样。没有 pg_cron,所以由写入端顺手做。"""
    sb = _supabase()
    if sb is None:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        sb.table(_TABLE).delete().lt("ts", cutoff).execute()
        return 1
    except Exception as e:
        logger.warning("overnight_bars: prune failed — %s", e)
        return 0


def build_15m(ticker: str, days: int = _KEEP_DAYS):
    """把采样点聚合成 15m OHLC。返回 DataFrame(UTC 索引)或 None。

    只保留采样数 ≥ `_MIN_TICKS_PER_BAR` 的 bar —— 覆盖不足 1/3 的"bar"是噪音,
    宁可缺一根也不要一根编出来的。volume 一律 0(见文件头限制③)。
    """
    import pandas as pd
    sb = _supabase()
    if sb is None:
        return None
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        rows = (sb.table(_TABLE).select("ts,price")
                .eq("ticker", ticker).gte("ts", since)
                .order("ts").limit(10000).execute().data) or []
    except Exception as e:
        logger.warning("overnight_bars: load failed — %s", e)
        return None
    if len(rows) < _MIN_TICKS_PER_BAR:
        return None
    s = pd.Series({pd.Timestamp(r["ts"]).tz_convert("UTC"): float(r["price"]) for r in rows})
    s = s.sort_index()
    g = s.resample("15min")
    df = pd.DataFrame({
        "open": g.first(), "high": g.max(), "low": g.min(), "close": g.last(),
        "volume": 0.0, "_n": g.count(),
    }).dropna(subset=["close"])
    df = df[df["_n"] >= _MIN_TICKS_PER_BAR].drop(columns=["_n"])
    return df if len(df) else None


def attach_overnight(df_15m, ticker: str):
    """把合成的夜盘 bar 接到日盘 15m 序列后面。

    返回 `(df, n_synthetic)`。只追加**比现有最后一根更晚**的 bar —— 绝不改写
    日盘的真实 bar(那是有成交量的真数据,合成 bar 不配覆盖它)。
    """
    import pandas as pd
    ov = build_15m(ticker)
    if ov is None or not len(ov):
        return df_15m, 0
    if df_15m is None or not len(df_15m):
        return ov, len(ov)
    last = pd.Timestamp(df_15m.index[-1])
    if last.tzinfo is None:
        last = last.tz_localize("UTC")
        idx = df_15m.index.tz_localize("UTC")
    else:
        idx = df_15m.index.tz_convert("UTC")
    base = df_15m.copy()
    base.index = idx
    add = ov[ov.index > last]
    if not len(add):
        return df_15m, 0
    cols = [c for c in base.columns if c in add.columns]
    out = pd.concat([base, add[cols]]).sort_index()
    return out, len(add)
