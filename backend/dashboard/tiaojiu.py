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
        # 抄底腿预计触发价(AI 自检 07-16 建议):快%R 贴地(≤-80)时,反解"明日收盘
        # 高于多少 ⇒ %R 上穿 -80"。%R>-80 ⟺ C > HH-0.8×(HH-LL);明日窗口 = 最近
        # 21 根旧 bar + 明日 bar,近似假设明日不破 21 日极值(触发价在区间高处,破低
        # 概率小)。把"事后确认"变成可挂单的具体价位;慢腿 <-50 的过滤条件另列。
        buy_trigger_px = None
        if float(f.iloc[-1]) <= -80 and float(s.iloc[-1]) < -50:
            hh21, ll21 = float(h.tail(21).max()), float(l.tail(21).min())
            if hh21 > ll21:
                buy_trigger_px = round(hh21 - 0.80 * (hh21 - ll21), 2)
        return {
            "fast": round(float(f.iloc[-1]), 1),
            "slow": round(float(s.iloc[-1]), 1),
            "buy_base":   bool(up(f, -80) and s.iloc[-1] < -50),
            "sell_trim":  bool(dn(f, -20) and s.iloc[-1] >= -20),
            "sell_clear": bool(dn(f, -50) and s.iloc[-1] < -20),
            "buy_trigger_px": buy_trigger_px,   # None = 未贴地/慢腿不满足,不适用
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

    # 「同行落后追赶」当日盘后读数(2026-07-28 用户拍板,承 AI 自检③)。
    # 该腿 07-24 触发,却要等 07-27 09:00 的例行决策才被看见,收益整段被隔夜跳空吃掉。
    # 并进这条已有的收盘心跳,而不是新开一路 ntfy —— 一晚 20 条轰炸的前科在(见
    # geopolitics 的频控注释)。触发则把心跳整体升成 high 响铃,不触发只多一行文字。
    catchup = False
    catch_line = ""
    try:
        from dashboard.relative_strength import analyze_relative_strength
        rs = analyze_relative_strength(df.rename(columns=str.lower))
        catchup = bool(rs.get("catchup_triggered"))
        sis = rs.get("sisters_1d") or {}
        _fmt = lambda v: f"{v*100:+.1f}%" if isinstance(v, (int, float)) else "n/a"
        catch_line = (f"同行 IONQ {_fmt(sis.get('ionq'))}/RGTI {_fmt(sis.get('rgti'))} "
                      f"vs QBTS {chg:+.1%}")
    except Exception as e:
        logger.warning(f"catchup readout failed: {e}")
    out["catchup"] = catchup

    # 每日必推一条(心跳):无信号=低优先级不响铃;有信号=高优先级。
    # 哪天 22:05(墨尔本冬令时,16:05 ET)后没收到任何推送 = 系统挂了,来找我。
    from dashboard.intraday_smc import _ntfy
    # 追赶与特调可能同日触发,别让它被吞掉:同向(抄底)时加一行共振,反向(止盈)时
    # 明说两腿打架,让人自己判断,不替他消歧义。
    if sig["buy_base"]:
        out["pushed"] = _ntfy("QBTS TeDiao BUY signal", (
            f"特调·抄底建仓 触发(今日收盘确认)\n"
            f"收盘 ${px:.2f}({chg:+.1%}) · 快%R {sig['fast']} 上穿-80,慢%R {sig['slow']} 仍弱\n"
            f"回测:触发后5天平均 +17.4%(基线+5.2%),n=15\n"
            + (f"⚡ 同行落后追赶同日触发(后5天+11.7%)—— 两条一级正腿共振\n" if catchup else "")
            + f"(验证期信号,小仓;≤5天可用QBTX)"), tags="dart", priority="high")
    elif sig["sell_trim"]:
        out["pushed"] = _ntfy("QBTS TeDiao TRIM signal", (
            f"特调·止盈减仓 触发(今日收盘确认)\n"
            f"收盘 ${px:.2f}({chg:+.1%}) · 快%R {sig['fast']} 跌穿-20,慢%R {sig['slow']} 仍高\n"
            f"回测:触发后20天平均 −10.0%(基线+24.9%),n=15 —— 历史标顶信号\n"
            + (f"⚠️ 同行落后追赶同日也触发(多头腿)—— 两腿方向相反,不共振\n" if catchup else "")
            + f"(持仓者考虑减半;验证期信号)"), tags="scissors", priority="high")
    elif catchup:
        # 特调没触发但追赶触发 —— 这条腿单独值一次响铃(历史后5天 +11.7%,最硬正腿)
        out["pushed"] = _ntfy("QBTS peer catchup signal", (
            f"同行落后追赶 触发(今日收盘确认)\n"
            f"收盘 ${px:.2f}({chg:+.1%}) · {catch_line}\n"
            f"回测:触发后5天 +11.7%(基线+5.2%)—— 全系统最硬正腿\n"
            f"(口径:同行均涨>3% 且 QBTS 落后 IONQ >1pp;验证期信号,小仓)"),
            tags="dart", priority="high")
    else:
        extra = f"\n{catch_line} → 追赶未触发" if catch_line else ""
        out["pushed"] = _ntfy("QBTS daily check OK", (
            f"✓ 系统正常 · QBTS 收盘 ${px:.2f}({chg:+.1%})\n"
            f"特调无触发(快%R {sig['fast']} / 慢%R {sig['slow']})· 七马明晨结算"
            f"{extra}"),
            tags="white_check_mark", priority="low")
    return out
