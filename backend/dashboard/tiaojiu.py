"""
「Qbts特调」信号(用户自改版 %R 系统,第十轮审判过关的两条腿)。

快%R(22,不平滑) + 慢%R(112,SMA3),经典刻度(−100..0):
  抄底建仓  = 快上穿 −80 且 慢 < −50 → 第十轮:后3/5/10天 +12.7/+17.4/+25.5%
             (基线 +3.2/+5.2/+10.6),n=15 —— 十轮 254 套里最强单一进场信号
  止盈减仓  = 快下穿 −20 且 慢 ≥ −20 → 后10/20天 −4.4/−10.0%(基线 +10.6/+24.9)
             —— 日线上真正能标顶的离场信号
  破位清仓  = 快下穿 −50 且 慢 < −20 → 不预测(≈基线),纯保险丝,只用于台账离场

参数稳健性 12 组扰动全正(mining.md 第十轮)。信号在日线收盘确认。
"""

from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_signals(df_d: pd.DataFrame) -> dict | None:
    """最后一根日线 bar 上的三腿状态 + 当前 %R 读数。df_d 需含 OHLC(大小写均可)。"""
    try:
        d = df_d.rename(columns=str.lower)
        if len(d) < 130 or not {"high", "low", "close"}.issubset(d.columns):
            return None
        c, h, l = d["close"].astype(float), d["high"].astype(float), d["low"].astype(float)

        def wpr(n):
            hh, ll = h.rolling(n).max(), l.rolling(n).min()
            return (hh - c) / (hh - ll).replace(0, np.nan) * -100

        f = wpr(22)
        s = wpr(112).rolling(3).mean()
        up = lambda x, lv: (x.iloc[-1] > lv) and (x.iloc[-2] <= lv)
        dn = lambda x, lv: (x.iloc[-1] < lv) and (x.iloc[-2] >= lv)
        return {
            "fast": round(float(f.iloc[-1]), 1),
            "slow": round(float(s.iloc[-1]), 1),
            "buy_base":   bool(up(f, -80) and s.iloc[-1] < -50),
            "sell_trim":  bool(dn(f, -20) and s.iloc[-1] >= -20),
            "sell_clear": bool(dn(f, -50) and s.iloc[-1] < -20),
            "bar_date": str(pd.Timestamp(d.index[-1]).date()),
        }
    except Exception as e:
        logger.warning(f"tiaojiu compute failed: {e}")
        return None


def maybe_tiaojiu_push(prev: dict | None, now_et: datetime) -> dict | None:
    """收盘后(16:05–19:59 ET,交易日)每日一算;有信号腿触发则 ntfy 一次。
    返回写进 live_quote 的状态 dict(pushed_date 去重);非窗口返回 prev 原样。"""
    if now_et.weekday() >= 5 or not (16 <= now_et.hour <= 19) or \
            (now_et.hour == 16 and now_et.minute < 5):
        return prev
    today = now_et.date().isoformat()
    if prev and prev.get("date") == today:
        return prev                      # 今天已算过(含已推送)

    try:
        import yfinance as yf
        df = yf.download("QBTS", period="1y", interval="1d", progress=False,
                         auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        sig = compute_signals(df)
    except Exception as e:
        logger.warning(f"tiaojiu push fetch failed: {e}")
        return prev
    if sig is None:
        return prev
    out = {"date": today, **sig, "pushed": False}

    closes = df.rename(columns=str.lower)["close"]
    px, chg = float(closes.iloc[-1]), float(closes.iloc[-1] / closes.iloc[-2] - 1)

    # 每日必推一条(心跳):无信号=低优先级不响铃;有信号=高优先级。
    # 哪天 22:05(墨尔本冬令时,16:05 ET)后没收到任何推送 = 系统挂了,来找我。
    from dashboard.intraday_smc import _ntfy
    if sig["buy_base"]:
        out["pushed"] = _ntfy("QBTS TeDiao BUY signal", (
            f"特调·抄底建仓 触发(今日收盘确认)\n"
            f"收盘 ${px:.2f}({chg:+.1%}) · 快%R {sig['fast']} 上穿-80,慢%R {sig['slow']} 仍弱\n"
            f"回测:触发后5天平均 +17.4%(基线+5.2%),n=15\n"
            f"(验证期信号,小仓;≤5天可用QBTX)"), tags="dart", priority="high")
    elif sig["sell_trim"]:
        out["pushed"] = _ntfy("QBTS TeDiao TRIM signal", (
            f"特调·止盈减仓 触发(今日收盘确认)\n"
            f"收盘 ${px:.2f}({chg:+.1%}) · 快%R {sig['fast']} 跌穿-20,慢%R {sig['slow']} 仍高\n"
            f"回测:触发后20天平均 −10.0%(基线+24.9%),n=15 —— 历史标顶信号\n"
            f"(持仓者考虑减半;验证期信号)"), tags="scissors", priority="high")
    else:
        out["pushed"] = _ntfy("QBTS daily check OK", (
            f"✓ 系统正常 · QBTS 收盘 ${px:.2f}({chg:+.1%})\n"
            f"特调无触发(快%R {sig['fast']} / 慢%R {sig['slow']})· 七马明晨结算"),
            tags="white_check_mark", priority="low")
    return out
