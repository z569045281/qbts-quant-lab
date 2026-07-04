"""
周一开盘·周末BTC 信号(第七轮回测,mining.md 核心事实 #9)。

BTC 周末照常交易、美股歇着 —— 周末(周五收→周日 UTC 收)的 BTC 方向对周一
QBTS 有强分辨力,且肥肉在**开盘后仍可买到的日内段**(开→收 +2.57%/−2.97%,
t=3.57;近1年 +2.90/−1.45)。诚实核算(开盘买/收盘卖,0.2%/边):现货 2 年
+175%、近1年 +98%,单日胜率 60%;QBTX 执行 1 天衰减可忽略。n=55,验证期信号。

运行:每分钟 QuoteFunction 里调 maybe_btc_weekend —— 仅周一(ET)返回数据
(其余日子 None → 前端横幅自动消失);周一首个运行分钟算一次并随 live_quote
carry;08:00 ET 起推一次 ntfy(涨→开盘买提醒 / 跌→回避提醒),用信号里的
pushed 标记去重(live_quote 读回)。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_PUSH_HOUR_ET = 8   # 08:00 ET 起推送(开盘前 ~1.5h;悉尼/墨尔本晚间)


def _compute(now_et: datetime) -> dict | None:
    """周末 BTC 方向:上周五 UTC 日收 → 最近一根已完成 UTC 日收(周日)。"""
    import yfinance as yf
    b = yf.download("BTC-USD", period="10d", interval="1d", progress=False)["Close"].squeeze()
    if b is None or len(b) < 3:
        return None
    dates = [i.date() for i in b.index]
    friday = (now_et - timedelta(days=3)).date()          # 周一 ET − 3 天 = 上周五
    sunday = friday + timedelta(days=2)
    base = [v for d, v in zip(dates, b) if d <= friday]
    last = [(d, v) for d, v in zip(dates, b) if friday < d <= sunday]
    if not base or not last:
        return None
    wret = float(last[-1][1]) / float(base[-1]) - 1
    return {
        "date": now_et.date().isoformat(),
        "weekend_ret": round(wret, 4),
        "green": bool(wret > 0),
        "last_utc_day": last[-1][0].isoformat(),
        "pushed": False,
    }


def maybe_btc_weekend(prev: dict | None, now_et: datetime) -> dict | None:
    """周一(ET)返回信号 dict(其余日子 None);算一次后经 live_quote carry,
    08:00 ET 后未推送则推一次 ntfy。"""
    if now_et.weekday() != 0:
        return None
    today = now_et.date().isoformat()
    bw = prev if (prev and prev.get("date") == today) else None
    if bw is None:
        try:
            bw = _compute(now_et)
        except Exception as e:
            logger.warning(f"btc_weekend compute failed: {e}")
            return prev if prev and prev.get("date") == today else None
        if bw is None:
            return None

    if not bw.get("pushed") and now_et.hour >= _PUSH_HOUR_ET:
        from dashboard.intraday_smc import _ntfy
        pct = bw["weekend_ret"] * 100
        if bw["green"]:
            ok = _ntfy(
                "QBTS Monday BTC signal",
                f"周末 BTC {pct:+.1f}% 🟢\n"
                f"→ 今天开盘买、收盘卖(QBTX 亦可,1天衰减忽略)\n"
                f"回测:近1年此信号周一日内均值 +2.9%,单日胜率 60%(n=55,验证期,小仓)",
                tags="chart_with_upwards_trend", priority="high")
        else:
            ok = _ntfy(
                "QBTS Monday BTC signal",
                f"周末 BTC {pct:+.1f}% 🔴\n"
                f"→ 今天开盘不做多(历史此情形周一日内均值 −3.0%)",
                tags="no_entry", priority="default")
        if ok:
            bw["pushed"] = True
    return bw


if __name__ == "__main__":
    import sys, json
    from pathlib import Path
    from zoneinfo import ZoneInfo
    sys.path.insert(0, str(Path(__file__).parent.parent))
    fake_monday = datetime.now(ZoneInfo("America/New_York"))
    print(json.dumps(_compute(fake_monday), ensure_ascii=False, indent=2))
