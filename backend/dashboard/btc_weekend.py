"""
周一开盘·周末BTC 信号(第七轮回测,mining.md 核心事实 #9)。

BTC 周末照常交易、美股歇着 —— 周末(周五收→周日 UTC 收)的 BTC 方向对周一
QBTS 有强分辨力:开→收 +2.57%/−2.97%(t=3.57;近1年 +2.90/−1.45);收对收
含跳空更大(+3.92%,t=4.39),当年判"不可交易"是假设买不到开盘前 —— 但美股
夜盘(周日 20:00 ET 起)可以交易,而 BTC 周日 UTC 日线恰好在 20:00 ET(夏令时)
定案。所以信号在周日夜盘开门那一刻就能算完推送(墨尔本周一上午 ~10 点),
夜盘建仓还可能吃到部分跳空。n=55,验证期信号。

运行:QuoteFunction 里调 maybe_btc_weekend —— 周日 ≥20:00 ET 起算并立即推
ntfy(周日调度 cron(1/10 20-23 ? * SUN),分钟错开 %5 避免顺带触发 SMC 重算);
周一全天 carry(错过周日则周一首个运行分钟补算补推);其余日子 None → 前端
横幅自动消失。去重键 = 该周末的周五日期(friday),经 live_quote 读回。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_NIGHT_OPEN_HOUR_ET = 20   # 周日 20:00 ET = 美股夜盘开门 = BTC 周日 UTC 线定案


def _compute(now_et: datetime, friday, live_fallback: bool = False) -> dict | None:
    """周末 BTC 方向:friday 的 UTC 日收 → 最近一根 ≤ 周日的已完成 UTC 日收。
    live_fallback(周日夜盘用):yfinance 日线经常晚给周日行 —— 夜盘开门时刻
    的现价 ≈ 刚定案的周日收盘(只差几分钟),缺行时用现价顶上,别拖到周一。"""
    import yfinance as yf
    b = yf.download("BTC-USD", period="10d", interval="1d", progress=False)["Close"].squeeze()
    if b is None or len(b) < 3:
        return None
    dates = [i.date() for i in b.index]
    sunday = friday + timedelta(days=2)
    base = [v for d, v in zip(dates, b) if d <= friday]
    last = [(d, v) for d, v in zip(dates, b) if friday < d <= sunday]
    if not base or not last:
        return None
    px, last_day = float(last[-1][1]), last[-1][0]
    # 周日夜盘:行缺 → 用现价;现价也拿不到 → None(10分钟后重试)。
    # 周一补算:放宽,用最近一根(≤周日)照算。
    if live_fallback and last_day != sunday:
        try:
            live = float(yf.Ticker("BTC-USD").fast_info["lastPrice"])
        except Exception:
            return None
        if not live or live <= 0:
            return None
        px, last_day = live, sunday
    wret = px / float(base[-1]) - 1
    return {
        "date": now_et.date().isoformat(),
        "friday": friday.isoformat(),
        "weekend_ret": round(wret, 4),
        "green": bool(wret > 0),
        "last_utc_day": last_day.isoformat(),
        "pushed": False,
    }


def maybe_btc_weekend(prev: dict | None, now_et: datetime) -> dict | None:
    """周日 ≥20:00 ET 与周一返回信号 dict(其余 None);算一次后经 live_quote
    carry,算完立即推一次 ntfy(friday 键去重)。"""
    wd = now_et.weekday()
    if wd == 6:                                   # 周日:夜盘开门起
        if now_et.hour < _NIGHT_OPEN_HOUR_ET:
            return None
        friday = (now_et - timedelta(days=2)).date()
    elif wd == 0:                                 # 周一:carry / 补算
        friday = (now_et - timedelta(days=3)).date()
    else:
        return None

    key = friday.isoformat()
    bw = prev if (prev and prev.get("friday") == key) else None
    if bw is None:
        try:
            bw = _compute(now_et, friday, live_fallback=(wd == 6))
        except Exception as e:
            logger.warning(f"btc_weekend compute failed: {e}")
            return None
        if bw is None:
            return None

    if not bw.get("pushed"):
        from dashboard.intraday_smc import _ntfy
        pct = bw["weekend_ret"] * 100
        if bw["green"]:
            ok = _ntfy(
                "QBTS weekend BTC signal",
                f"周末 BTC {pct:+.1f}% 🟢\n"
                f"→ 夜盘/盘前可先建仓(QBTS 现货、限价单,点差大勿追),或开盘买 QBTX\n"
                f"→ 无论哪种:周一收盘前全部卖出,不过夜\n"
                f"回测:开→收 +2.9%、胜率 60%;收→收含跳空 +3.9%(n=55,验证期,小仓)",
                tags="chart_with_upwards_trend", priority="high")
        else:
            ok = _ntfy(
                "QBTS weekend BTC signal",
                f"周末 BTC {pct:+.1f}% 🔴\n"
                f"→ 周一不做多,夜盘也不(历史此情形周一日内均值 −3.0%)",
                tags="no_entry", priority="default")
        if ok:
            bw["pushed"] = True
    return bw


if __name__ == "__main__":
    import sys, json
    from pathlib import Path
    from zoneinfo import ZoneInfo
    sys.path.insert(0, str(Path(__file__).parent.parent))
    now = datetime.now(ZoneInfo("America/New_York"))
    friday = (now - timedelta(days=3 if now.weekday() == 0 else 2)).date()
    print(json.dumps(_compute(now, friday), ensure_ascii=False, indent=2))
