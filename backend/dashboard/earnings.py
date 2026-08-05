"""📊 财报预期基准 —— 只有日期是不够的。

**出身(2026-08-05,决策 AI 自己在 system_notes 里提的、用户点单落地)**:
「财报仅 2 天后,系统应增加一段财报预期数据(营收/EPS 一致预期、历史财报日平均振幅),
当前只有日期没有预期基准,无法评估 surprise 空间。」

它说得对。以前 prompt 只有一行「下次财报: 2026-08-06(2 天后)」,于是 AI 只能说
"财报临近、波动放大、谨慎" —— 一句放之四海皆准的废话。**没有基准就没有 surprise**:
不知道市场预期多少,就不知道什么算超预期;不知道历史上这天平均跳多远,就不知道
"谨慎"到底该谨慎到什么程度(减半?清仓?还是根本无所谓)。

三块数据,全部免费:
  ① **一致预期** —— EPS / 营收的均值与高低区间(yfinance calendar)。
     区间本身就是信息:分析师之间分歧越大,越说明没人真的知道。
  ② **历史财报日实测** —— 当日 |涨跌| 与高低振幅的中位/均值/最大,以及方向胜率。
     ⚠️ 用**中位**当主口径:2025-05-08 那次 +51.2% 会把均值拉到没法用。
  ③ **历史 surprise 记录** —— 过去几次实际 EPS vs 预期,看这家公司是不是习惯性打脸。

**零决策权**:不进 edge、不产生买卖信号。它只是把"财报"这个已知最大波动源从
一个日期变成一组数字,让决策 AI 和用户各自去判断。方向不在这里 —— 本仓第三十二轮
已实测「财报前买入」判死,别拿这段当入场理由。
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_TICKER = "QBTS"
_MIN_HISTORY = 5          # 少于 5 次财报就不给统计(样本太小,给了会被当真)


def _consensus(t) -> dict:
    """分析师一致预期。任何一格拿不到就留 None,不猜。"""
    out: dict = {}
    try:
        cal = t.calendar or {}
    except Exception as e:
        logger.warning("earnings: calendar 拉取失败: %s", e)
        return out
    ed = cal.get("Earnings Date")
    if isinstance(ed, (list, tuple)) and ed:
        ed = ed[0]
    if isinstance(ed, (date, datetime)):
        out["date"] = ed.strftime("%Y-%m-%d") if not isinstance(ed, str) else ed
    for key, fld in (("Earnings Average", "eps_avg"), ("Earnings High", "eps_hi"),
                     ("Earnings Low", "eps_lo"), ("Revenue Average", "rev_avg"),
                     ("Revenue High", "rev_hi"), ("Revenue Low", "rev_lo")):
        v = cal.get(key)
        if isinstance(v, (int, float)) and not pd.isna(v):
            out[fld] = float(v)
    return out


def _history(t, closes: pd.Series) -> dict:
    """历史财报**当日**的实测振幅与方向。closes 需带 high/low → 传 DataFrame。"""
    try:
        raw = t.get_earnings_dates(limit=40)
    except Exception as e:
        logger.warning("earnings: 历史财报日拉取失败: %s", e)
        return {}
    if raw is None or raw.empty:
        return {}
    eds = sorted({x.date() for x in raw.index})
    idx = pd.DatetimeIndex(closes.index).normalize()
    chg, hl, surprises = [], [], []
    for ed in eds:
        ts = pd.Timestamp(ed)
        before, after = idx[idx < ts], idx[idx >= ts]
        if len(before) < 1 or len(after) < 1:
            continue
        p0 = float(closes.loc[before[-1], "close"])
        d0 = after[0]
        if p0 <= 0:
            continue
        chg.append(float(closes.loc[d0, "close"]) / p0 - 1)
        lo = float(closes.loc[d0, "low"])
        if lo > 0:
            hl.append(float(closes.loc[d0, "high"]) / lo - 1)
    # surprise 记录(最近 4 次有实际值的)
    try:
        s = raw.dropna(subset=["Reported EPS"]).head(4)
        for ts, row in s.iterrows():
            surprises.append({"date": ts.date().isoformat(),
                              "est": float(row["EPS Estimate"]),
                              "act": float(row["Reported EPS"]),
                              "surprise_pct": (float(row["Surprise(%)"])
                                               if not pd.isna(row.get("Surprise(%)")) else None)})
    except Exception:
        pass
    if len(chg) < _MIN_HISTORY:
        return {"n": len(chg), "too_few": True, "surprises": surprises}
    a = np.abs(np.array(chg))
    c = np.array(chg)
    h = np.array(hl) if hl else np.array([np.nan])
    return {
        "n": len(chg),
        "abs_median": round(float(np.median(a)), 4),
        "abs_mean": round(float(a.mean()), 4),
        "abs_max": round(float(a.max()), 4),
        "hl_median": round(float(np.nanmedian(h)), 4),
        "dir_median": round(float(np.median(c)), 4),
        "up_rate": round(float((c > 0).mean()), 3),
        "last8": [round(x, 4) for x in chg[-8:]],
        "surprises": surprises,
    }


def analyze_earnings(df_daily: pd.DataFrame | None = None) -> dict | None:
    """财报预期基准。拉不到 → None(段落显式说缺,不静默消失)。"""
    try:
        import yfinance as yf
        t = yf.Ticker(_TICKER)
        con = _consensus(t)
        if df_daily is None:
            df_daily = yf.download(_TICKER, period="max", interval="1d",
                                   auto_adjust=True, progress=False)
            if isinstance(df_daily.columns, pd.MultiIndex):
                df_daily.columns = df_daily.columns.get_level_values(0)
        d = df_daily.rename(columns=str.lower)[["high", "low", "close"]].dropna()
        d.index = pd.DatetimeIndex(d.index).normalize()
        hist = _history(t, d)
        if not con and not hist:
            return None
        out = {"ticker": _TICKER, "consensus": con, "history": hist}
        ed = con.get("date")
        if ed:
            try:
                out["days_to"] = (datetime.fromisoformat(ed).date() - date.today()).days
            except ValueError:
                pass
        return out
    except Exception as e:
        logger.warning("analyze_earnings failed: %s", e)
        return None


def prompt_block(e: dict | None) -> str:
    """决策 prompt 里的财报段。拉不到就显式说缺 —— 段落静默消失会让模型自己猜。"""
    if not e:
        return ("## 📊 财报预期基准\n  ⚠️ 未获取到(数据源失败)——若新闻提示财报临近,"
                "以新闻为准,并在 system_notes 标注此数据缺口。")
    con, hist = e.get("consensus") or {}, e.get("history") or {}
    L = ["## 📊 财报预期基准（一致预期 + 历史当日实测）"]
    ed, dt = con.get("date"), e.get("days_to")
    L.append(f"  下次财报: {ed or '?'}" + (f"（{dt} 天后）" if dt is not None else "")
             + " —— QBTS 单票最大的已知波动源,临近时权重高于任何宏观日。")
    if con.get("eps_avg") is not None:
        rng = (f"（区间 {con['eps_lo']:+.2f} ~ {con['eps_hi']:+.2f}）"
               if con.get("eps_lo") is not None and con.get("eps_hi") is not None else "")
        L.append(f"  EPS 一致预期 {con['eps_avg']:+.3f}{rng}")
    if con.get("rev_avg") is not None:
        rng = (f"（区间 ${con['rev_lo']/1e6:.2f}M ~ ${con['rev_hi']/1e6:.2f}M）"
               if con.get("rev_lo") is not None and con.get("rev_hi") is not None else "")
        L.append(f"  营收一致预期 ${con['rev_avg']/1e6:.2f}M{rng}"
                 "\n  （区间越宽 = 分析师分歧越大 = 越没人真的知道,别把一致预期当锚）")
    if hist.get("too_few"):
        L.append(f"  ⚠️ 历史财报仅 {hist.get('n', 0)} 次,样本太少不给统计。")
    elif hist.get("n"):
        L.append(
            f"  历史财报**当日**实测（n={hist['n']}）:\n"
            f"    |涨跌| 中位 {hist['abs_median']*100:.1f}% · 均值 {hist['abs_mean']*100:.1f}%"
            f" · 最大 {hist['abs_max']*100:.1f}%\n"
            f"    当日高低振幅 中位 {hist['hl_median']*100:.1f}%\n"
            f"    方向 中位 {hist['dir_median']*100:+.1f}% · 上涨率 {hist['up_rate']*100:.0f}%\n"
            f"    近 8 次: {', '.join(f'{x*100:+.1f}%' for x in hist.get('last8', []))}")
        L.append("  ⚠️ 用**中位**当主口径,均值被单次极端值拉偏(见最大值那一格)。"
                 "杠杆 ETF 口径 ≈ 上面数字 ×2。")
    sp = hist.get("surprises") or []
    if sp:
        L.append("  历史 surprise: " + " · ".join(
            f"{s['date'][:7]} 预期{s['est']:+.2f}/实际{s['act']:+.2f}"
            + (f"({s['surprise_pct']:+.0f}%)" if s.get("surprise_pct") is not None else "")
            for s in sp))
    L.append("  纪律:①**这段不产生方向** —— 第三十二轮已实测「财报前买入」判死"
             "(去掉最赚一笔即转负、姐妹票反向),不得拿它当入场理由。\n"
             "  ②它的正确用途是**定仓位与定时点**:用当日振幅中位判断该减多少、"
             "什么时候减,而不是判断涨还是跌。\n"
             "  ③财报是二元事件,系统对它**没有任何预测能力**,别在 summary 里假装有。")
    return "\n".join(L)
