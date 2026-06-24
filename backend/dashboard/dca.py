"""
定投专区 (Dollar-Cost-Averaging zone) — for parking spare cash in broad ETFs.

This is NOT a trading signal. DCA's whole premise is "time in the market beats
timing the market", so the honest job here is small: tell the user *when a month
is a mildly better-than-average time to deploy extra cash*, and otherwise say
"just keep buying / leave it parked".

Two grounded inputs per ETF:
  1. Seasonality (the "Halloween effect" / "Sell in May" / September effect):
     historical average return by calendar month. Broad indices earn most of
     their return Nov–Apr; September is the worst month almost every year. So the
     seasonally best place to deploy a lump of spare cash is the Sep–Oct weakness.
  2. Dip / valuation: drawdown from the 52-week high + price vs the 200-day MA.
     A pullback or below-200dMA is a better-than-average DCA entry.

Combined into a gentle stance: 逢低加码 / 正常定投 / 偏高(照投或少投). Never "don't buy".
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Core broad-market DCA ETFs (one per "flavor"; user named QQQ/VOO/IOO).
DCA_ETFS = ["VOO", "QQQ", "VTI", "IOO"]
NAME = {
    "VOO": "标普500", "QQQ": "纳指100", "VTI": "美股全市场",
    "IOO": "全球100", "SPY": "标普500", "SCHD": "美股高股息",
}
_WINTER = {11, 12, 1, 2, 3, 4}   # the historically strong half


def _compute_etf(ticker: str) -> dict:
    base = {"ticker": ticker, "name": NAME.get(ticker, ticker)}
    try:
        d = yf.download(ticker, period="1y", interval="1d", auto_adjust=True, progress=False)
        m = yf.download(ticker, period="max", interval="1mo", auto_adjust=True, progress=False)
        close = d["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        mclose = m["Close"]
        if isinstance(mclose, pd.DataFrame):
            mclose = mclose.iloc[:, 0]

        price = float(close.iloc[-1])
        prev = float(close.iloc[-2])
        today_change = (price / prev - 1) if prev > 0 else 0.0
        high_52w = float(close.max())
        drawdown = (price / high_52w - 1) if high_52w > 0 else 0.0          # ≤ 0
        sma200 = float(close.rolling(200, min_periods=100).mean().iloc[-1])
        below_200 = price < sma200
        vs_200 = (price / sma200 - 1) if sma200 > 0 else 0.0

        # seasonality
        mret = mclose.pct_change().dropna()
        by_month = mret.groupby(mret.index.month).mean()
        best_m = int(by_month.idxmax()); worst_m = int(by_month.idxmin())
        cur_m = datetime.now().month
        cur_avg = float(by_month.get(cur_m, np.nan))
        winter = float(mret[mret.index.month.isin(_WINTER)].mean())
        summer = float(mret[~mret.index.month.isin(_WINTER)].mean())

        # DCA stance: buy more on weakness, never "don't buy"
        if drawdown <= -0.10 or below_200:
            stance, emoji = "逢低加码", "🟢"
            hint = (f"已从高点回调 {abs(drawdown)*100:.0f}%"
                    + ("、且跌破200日均线" if below_200 else "")
                    + " —— 闲钱可以适当多投一点。")
        elif drawdown >= -0.03 and not below_200:
            stance, emoji = "偏高·照投或少投", "🔵"
            hint = (f"接近52周高点(仅回调 {abs(drawdown)*100:.0f}%)—— 照常定投即可,别追高加码;"
                    f"想等更好的点,历史上 9–10 月常有回调。")
        else:
            stance, emoji = "正常定投", "🟡"
            hint = "处于正常区间 —— 按计划定投就好。"

        base.update({
            "price": round(price, 2),
            "today_change": round(today_change, 4),
            "drawdown_pct": round(drawdown, 4),
            "vs_200dma_pct": round(vs_200, 4),
            "below_200": below_200,
            "stance": stance, "stance_emoji": emoji, "hint": hint,
            "best_month": best_m, "best_month_avg": round(float(by_month[best_m]), 4),
            "worst_month": worst_m, "worst_month_avg": round(float(by_month[worst_m]), 4),
            "cur_month": cur_m,
            "cur_month_avg": round(cur_avg, 4) if not np.isnan(cur_avg) else None,
            "winter_avg": round(winter, 4), "summer_avg": round(summer, 4),
            "error": None,
        })
    except Exception as e:
        logger.warning(f"dca {ticker} failed: {e}")
        base.update({"error": f"{type(e).__name__}: {str(e)[:80]}", "stance": "—", "stance_emoji": "⚠️"})
    return base


def compute_dca(tickers: list[str] | None = None) -> dict:
    tickers = tickers or DCA_ETFS
    results = [_compute_etf(t) for t in tickers]
    cur_m = datetime.now().month
    in_strong = cur_m in _WINTER
    if cur_m in (9, 10):
        season_note = "现在是 9–10 月 —— 历史上全年最弱、最适合布局的窗口,有闲钱优先在此投入。"
    elif in_strong:
        season_note = f"现在是 {cur_m} 月 —— 处于历史强势半年(11–4月),保持定投、不必空等。"
    else:
        season_note = f"现在是 {cur_m} 月 —— 历史偏弱半年(5–10月),正常定投即可,大跌再加码。"
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "etfs": tickers,
        "season": {"month": cur_m, "in_strong_window": in_strong, "note": season_note},
        "results": results,
        "principle": ("定投的核心是『待在市场里』,不是择时。下面的提示只是『有闲钱时哪个月更划算』"
                      "的微调——别为了等买点而空仓,长期看持续投入胜过精准择时。"),
    }


def publish_dca() -> dict:
    """Compute the DCA read and upsert it to dca_state. Shared by daily publish."""
    payload = compute_dca()
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if url and key:
        try:
            from supabase import create_client
            sb = create_client(url, key)
            safe = json.loads(json.dumps(payload, default=str), parse_constant=lambda _c: None)
            sb.table("dca_state").upsert({"id": "current", "data": safe}).execute()
        except Exception as e:
            logger.warning(f"publish_dca write failed: {e}")
    return payload


if __name__ == "__main__":
    out = compute_dca()
    print(out["season"]["note"])
    for r in out["results"]:
        if r.get("error"):
            print(f"  ⚠️ {r['ticker']}: {r['error']}"); continue
        print(f"  {r['stance_emoji']} {r['ticker']:4s}{r['name']:8s} ${r['price']:>7.2f} "
              f"回调{r['drawdown_pct']*100:+5.1f}% 200MA{r['vs_200dma_pct']*100:+5.1f}% "
              f"| 最强{r['best_month']}月 最弱{r['worst_month']}月 | {r['stance']}")
