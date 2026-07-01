"""
定投专区 (DCA zone) — parking spare cash in a globally-diversified, valuation-tilted
core of index ETFs. NOT a trading signal. Rebuilt around what actually drives long-run
ETF outcomes (savings rate > time-in-market > fees > not panic-selling > diversification);
entry timing is near noise, so the honest job here is small and twofold:

  1. Pick the right *baskets* — a 4-ETF menu spanning the global valuation spectrum, so
     you can tilt toward what's cheap (CAPE has real predictive power ACROSS REGIONS, not
     across US sectors):
        VTI  美股全市场      — US core (expensive: CAPE ~40)
        VEA  发达除美        — Europe/Japan/etc (cheaper)
        VWO  新兴市场        — emerging (cheapest)
        AVUV 美股小盘价值     — the one cheap corner of US
  2. Say *when to deploy extra* — using the evidence (real SPY/QQQ/IOO history): the
     −5~10% pullback above the 200-day is the best return+win-rate blend; only a −20%+
     capitulation justifies the reserve; the −10~20% middle is the worst ("falling knife"),
     NOT a bargain; and buying near highs is fine — don't wait.

Valuation per ETF uses trailing P/E + earnings yield (1/PE ≈ rough long-run real return)
as a CAPE proxy (true 10-yr CAPE isn't available per-ETF from yfinance).
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

# Global valuation menu (one ETF per distinct region/valuation bucket). Target weights
# are a *moderate* valuation tilt vs the ~60/40 US/ex-US cap-weighted baseline.
META = {
    "VTI":  {"name": "美股全市场",   "role": "美国核心",        "target": 40},
    "VEA":  {"name": "发达除美",     "role": "欧洲+日本等",     "target": 30},
    "VWO":  {"name": "新兴市场",     "role": "新兴·最便宜",     "target": 20},
    "AVUV": {"name": "美股小盘价值", "role": "美股便宜角落",     "target": 10},
}
DCA_ETFS = list(META.keys())

# 择机观察名单 —— 不进核心配置(不占 40/30/20/10 权重),只显示估值,便宜了再择机加。
# 故意独立于 META:加进 META 会污染 DCA_ETFS 和 allocation 权重条。
WATCH = {
    "QQQ": {"name": "纳指100", "role": "美国大科技·择机(现贵,等便宜)"},
}
WATCH_ETFS = list(WATCH.keys())
_META_ALL = {**META, **WATCH}   # 仅用于 _compute_etf 取名字/角色

_WINTER = {11, 12, 1, 2, 3, 4}   # historically strong half (kept as a minor detail)


def _valuation(ey: float | None) -> tuple[str, str]:
    """Cheap/neutral/rich tag from earnings yield (1/PE). Absolute, honest thresholds."""
    if ey is None:
        return "—", "⚪"
    if ey >= 0.06:   return "便宜", "🟢"   # PE ≲ 16.7
    if ey >= 0.04:   return "中性", "🟡"   # PE 16.7–25
    return "偏贵", "🔴"                     # PE ≳ 25


def _deploy(drawdown: float, below_200: bool) -> dict:
    """Evidence-based 'when to put extra in', from real SPY/QQQ/IOO drawdown→fwd-return
    history. drawdown ≤ 0 (distance from 52w high)."""
    dd = abs(drawdown) * 100
    if drawdown <= -0.20:
        return {"tag": "深跌·可动用预备金", "emoji": "🟢",
                "text": f"已深跌 {dd:.0f}% —— 历史上深跌后 1 年回报最高;有预备金可加码,"
                        f"但要扛得住继续跌(深跌也可能再深)。"}
    if drawdown <= -0.10:
        return {"tag": "中段回调·别抄底", "emoji": "⚪",
                "text": f"中段回调 {dd:.0f}% —— 这是历史上最坑的区间(常是下跌中继),"
                        f"别当便宜货抄底,照常定投即可。"}
    if drawdown <= -0.05:
        if not below_200:
            return {"tag": "小回调·可多投", "emoji": "🟡",
                    "text": f"小回调 {dd:.0f}% 且仍在 200 日线上方 —— 历史上收益+胜率最佳区,"
                            f"有闲钱可适度多投一点。"}
        return {"tag": "小回调·谨慎", "emoji": "🟡",
                "text": f"小回调 {dd:.0f}% 但已跌破 200 日线 —— 谨慎,照常定投为主。"}
    return {"tag": "照投·别怕新高", "emoji": "✅",
            "text": "接近高点 —— 照常定投、别怕新高(历史上高点买入 1 年也有 ~+13%)。"}


def _compute_etf(ticker: str) -> dict:
    meta = _META_ALL.get(ticker, {})
    base = {"ticker": ticker, "name": meta.get("name", ticker),
            "role": meta.get("role", ""), "target_weight": meta.get("target")}
    try:
        d = yf.download(ticker, period="1y", interval="1d", auto_adjust=True, progress=False)
        m = yf.download(ticker, period="max", interval="1mo", auto_adjust=True, progress=False)
        close = d["Close"]
        if isinstance(close, pd.DataFrame):  close = close.iloc[:, 0]
        mclose = m["Close"]
        if isinstance(mclose, pd.DataFrame): mclose = mclose.iloc[:, 0]

        price = float(close.iloc[-1])
        prev = float(close.iloc[-2])
        today_change = (price / prev - 1) if prev > 0 else 0.0
        high_52w = float(close.max())
        drawdown = (price / high_52w - 1) if high_52w > 0 else 0.0
        sma200 = float(close.rolling(200, min_periods=100).mean().iloc[-1])
        below_200 = price < sma200
        vs_200 = (price / sma200 - 1) if sma200 > 0 else 0.0

        # valuation (CAPE proxy): trailing P/E + earnings yield
        pe = None
        try:
            pe = yf.Ticker(ticker).info.get("trailingPE")
        except Exception:
            pe = None
        ey = (1.0 / pe) if (isinstance(pe, (int, float)) and pe and pe > 0) else None
        val, val_emoji = _valuation(ey)

        # 完整历史复合年化(CAGR，含分红——mclose 已是 auto_adjust 总回报)。
        # 这才是诚实的"平均年回报率":复合、非算术平均。数据已下载，零额外成本。
        cagr = cagr_years = None
        try:
            yrs = (mclose.index[-1] - mclose.index[0]).days / 365.25
            if yrs > 0.5 and float(mclose.iloc[0]) > 0:
                cagr = (float(mclose.iloc[-1]) / float(mclose.iloc[0])) ** (1.0 / yrs) - 1.0
                cagr_years = round(yrs, 1)
        except Exception:
            cagr = cagr_years = None

        # seasonality (kept as a minor secondary detail)
        mret = mclose.pct_change().dropna()
        by_month = mret.groupby(mret.index.month).mean()
        best_m = int(by_month.idxmax()); worst_m = int(by_month.idxmin())
        winter = float(mret[mret.index.month.isin(_WINTER)].mean())
        summer = float(mret[~mret.index.month.isin(_WINTER)].mean())

        base.update({
            "price": round(price, 2),
            "today_change": round(today_change, 4),
            "pe": round(pe, 1) if isinstance(pe, (int, float)) else None,
            "earnings_yield": round(ey, 4) if ey is not None else None,
            "valuation": val, "valuation_emoji": val_emoji,
            "cagr": round(cagr, 4) if cagr is not None else None,
            "cagr_years": cagr_years,
            "drawdown_pct": round(drawdown, 4),
            "vs_200dma_pct": round(vs_200, 4),
            "below_200": below_200,
            "deploy": _deploy(drawdown, below_200),
            "best_month": best_m, "best_month_avg": round(float(by_month[best_m]), 4),
            "worst_month": worst_m, "worst_month_avg": round(float(by_month[worst_m]), 4),
            "winter_avg": round(winter, 4), "summer_avg": round(summer, 4),
            "error": None,
        })
    except Exception as e:
        logger.warning(f"dca {ticker} failed: {e}")
        base.update({"error": f"{type(e).__name__}: {str(e)[:80]}",
                     "valuation": "—", "valuation_emoji": "⚠️"})
    return base


def compute_dca(tickers: list[str] | None = None) -> dict:
    tickers = tickers or DCA_ETFS
    results = [_compute_etf(t) for t in tickers]
    watch = [_compute_etf(t) for t in WATCH_ETFS]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "etfs": tickers,
        "results": results,
        # 择机观察(不进核心配置):便宜了再买
        "watch": watch,
        "watch_note": "这些不进上面的核心配置、不占权重。只看估值:🔴偏贵就等、"
                      "转🟡中性/🟢便宜再考虑择机小仓加(卫星仓,不是压舱石)。",
        # recommended valuation-tilted allocation (moderate; rebalance annually)
        "allocation": {
            "weights": {t: META[t]["target"] for t in tickers if t in META},
            "note": "市值中性约 60%美/40%外;这里按估值往非美+新兴温和倾斜。每年再平衡一次"
                    "(把涨多的卖一点、补给跌的,本身就是高抛低吸)。",
        },
        # macro valuation backdrop (CAPE — re-verify periodically; cross-country CAPE
        # should be judged vs each market's OWN history, not compared absolutely)
        "macro": {
            "us_cape": 40, "global_cape": 27.7, "as_of": "2026-06",
            "note": "美股 Shiller CAPE ≈40(近互联网泡沫极值,Shiller 模型预期未来十年年化仅 ~1–2%);"
                    "全球整体 ≈27.7。便宜在非美/新兴。这是 7–10 年的弱倾斜信号、不是择时,数据需定期复核。",
        },
        "ballast": "这 4 只全是股票(100% 权益),崩盘会一起腰斩。十年不用 + 扛得住 → 可全股;"
                   "否则加 10~30% 债券(BND)当压舱石。暴跌预备金 / 应急金放短债(如 SGOV)生息,别躺着。",
        "principle": "决定结果的顺序:多投 > 早投 > 低费 > 不割肉 > 全球分散,买点择时接近噪声。"
                     "主力资金按节奏自动投、别怕新高;下面只帮你『选对篮子 + 什么时候多投一点』。",
        "separation": "⚠️ 这是躺平核心仓 —— 请和 QBTS / 自选扫描的投机仓彻底分开;后者要小到亏光也不影响生活。",
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
    print(out["macro"]["note"], "\n")
    for r in out["results"]:
        if r.get("error"):
            print(f"  ⚠️ {r['ticker']}: {r['error']}"); continue
        print(f"  {r['valuation_emoji']} {r['ticker']:4s}{r['name']:9s} ${r['price']:>7.2f} "
              f"P/E {r['pe']} 预期~{(r['earnings_yield'] or 0)*100:.1f}% | {r['valuation']:4s} "
              f"目标{r['target_weight']}% | 回撤{r['drawdown_pct']*100:+.0f}% → {r['deploy']['tag']}")
