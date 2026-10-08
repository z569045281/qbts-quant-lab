"""
买入扳机总检(2026-08-24,用户点单「其它指标让我买入了也说一声」)。

## 为什么有这个模块

收盘心跳(`tiaojiu.maybe_tiaojiu_push`)此前只报**特调**两条腿 + 同行追赶。
在册排行榜里另外几条**同样有买入扳机的腿**从来没进过推送 ——
用户得自己上仪表盘翻,而他问的恰恰是「什么时候能买,到了跟我说一声」。

## 覆盖哪些腿(**只收在册的,不新造信号**)

| 腿 | 出处 | 闸门 |
|---|---|---|
| 特调·抄底建仓 | 第十轮,254 套里最强单一进场信号 | 慢%R < −50 |
| 5日swing(5日新低买) | 排行榜 #6,72% 胜率(23/32) | **× QQQ50 大盘红绿灯** |
| 深坑抄底(跌20%于20日高) | 排行榜 #8,64%@25 | — |
| 同行落后追赶 | 观察组最硬正腿,后5天 +11.7% | 在 relative_strength |

⚠️ **5日swing 必须带 QQQ50 闸**。裸腿和在册版本是两回事:排行榜上的是
`5日swing×QQQ50`。红灯时裸腿亮了**不算买入信号**,只能报「亮了但被挡住」——
把裸腿当信号推,等于偷偷把一个没验证过的变体塞进产品。

## 本模块只报状态,不做决策

- 不改任何闸门、不碰四条铁律、不产生仓位建议
- **触发 ≠ 该买**:全是验证期信号(UNPROVEN),推送里必须带这句
- 没触发的腿一律报**「还差多少」**(距离/触发价)—— 这才是「什么时候」的答案
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DIP_DRAW = 0.20        # 深坑抄底:跌 20% 于 20 日高(排行榜 #8 口径)
DIP_EXIT = 0.95        # 深坑抄底出场:回到进场时 20 日高的 95%
DIP_MAX = 15           # 深坑抄底最多拿 15 天
SWING_LB = 5           # 5日swing 回看(第七轮参数扫:5-7 天甜区,3 天是噪声悬崖)
SWING_MAX = 10         # 5日swing 最多拿 10 天(破 5 日新高先出)
LIVE_FROM = "2026-07-10"   # 在册定型日:之后的成交才算实盘(样本外)


# ── 持仓状态机(2026-10-08 推送体检)────────────────────────────────────
# 两条腿在 mining.md 里的定义都是**一次一笔**:进场 → 出场条件或满天数 → 才能再进。
# 而 check() 原来是无状态的:每天只看「今天收盘是不是又创新低」。下跌途中天天创新低,
# 于是 09-28 进场后,09-29 / 10-02 / 10-05 / 10-07 又各推了一条「🔔 触发 → 买」,
# 8 个交易日 5 条 —— 按推送下单 = 在跌势里加仓 4 次,规则本身从没这么做过。
# 状态只由收盘价决定,所以每次从日线重放一遍就能还原,不用另外存。

def _sim_swing(c: pd.Series, green: pd.Series) -> tuple[list[dict], dict | None]:
    """5日swing×QQQ50:绿灯 + 收盘 < 前5日最低 → 收盘进;收盘 > 前5日最高 或 满 10 天 → 收盘出。"""
    lo, hi = c.shift(1).rolling(SWING_LB).min(), c.shift(1).rolling(SWING_LB).max()
    g = green.reindex(c.index).ffill()
    trades, pos = [], None
    for i in range(len(c)):
        px = float(c.iloc[i])
        if pos is None:
            if np.isfinite(lo.iloc[i]) and px < lo.iloc[i] and bool(g.iloc[i]):
                pos = {"i": i, "date": c.index[i], "px": px}
        elif px > hi.iloc[i] or i - pos["i"] >= SWING_MAX:
            trades.append({**pos, "ret": px / pos["px"] - 1})
            pos = None
    return trades, pos


def _sim_dip(c: pd.Series) -> tuple[list[dict], dict | None]:
    """深坑抄底:收盘 ≤ 20日高×0.8 → 收盘进;回到进场时 20日高的 95% 或满 15 天 → 收盘出。"""
    hi20 = c.rolling(20).max()
    trades, pos = [], None
    for i in range(len(c)):
        px = float(c.iloc[i])
        if pos is None:
            if np.isfinite(hi20.iloc[i]) and px <= hi20.iloc[i] * (1 - DIP_DRAW):
                pos = {"i": i, "date": c.index[i], "px": px, "exit_px": float(hi20.iloc[i]) * DIP_EXIT}
        elif px >= pos["exit_px"] or i - pos["i"] >= DIP_MAX:
            trades.append({**pos, "ret": px / pos["px"] - 1})
            pos = None
    return trades, pos


def _live_record(trades: list[dict]) -> str:
    """定型后(样本外)的成绩。推送原来只引回测胜率 —— 5日swing 回测 72%,
    而 07-10 定型后完成的 2 笔全亏(−19% / −15%)。两个数必须并排出现。"""
    live = [t for t in trades if str(pd.Timestamp(t["date"]).date()) >= LIVE_FROM]
    if not live:
        return "定型后实盘 0 笔"
    w = sum(t["ret"] > 0 for t in live)
    return f"定型后实盘 {w}/{len(live)} 赚"


def _date(ts) -> str:
    return pd.Timestamp(ts).strftime("%m-%d")


def _qqq_green() -> pd.Series | None:
    """大盘红绿灯整条序列:QQQ vs 50 日线(True=绿)。取不到返回 None(不猜)。
    要整条而不只今天:状态机得知道**过去每一天**能不能进场。"""
    try:
        import yfinance as yf
        q = yf.download("QQQ", period="2y", interval="1d",
                        auto_adjust=True, progress=False)
        if isinstance(q.columns, pd.MultiIndex):
            q.columns = q.columns.get_level_values(0)
        c = q["Close"].dropna()
        if len(c) < 50:
            return None
        g = (c > c.rolling(50).mean())
        g.index = pd.DatetimeIndex(g.index).tz_localize(None).normalize()
        return g
    except Exception as e:
        logger.warning("qqq light failed: %s", str(e)[:80])
        return None


def _qqq_risk_on() -> bool | None:
    """今天的大盘红绿灯。取不到返回 None(不猜)。"""
    g = _qqq_green()
    return None if g is None else bool(g.iloc[-1])


def check(df_d: pd.DataFrame, risk_on: bool | None = None,
          green: pd.Series | None = None) -> dict:
    """
    df_d —— QBTS 日线(含 OHLC,大小写均可)。green —— QQQ>50日线 的整条序列(不给就现拉)。
    返回 {fired: [...], pending: [...], lines: [...]}。任何异常都吞掉返回空,
    因为它挂在每日心跳上 —— 宁可少报一条,不能让整条推送死掉。
    """
    out = {"fired": [], "pending": [], "lines": []}
    try:
        d = df_d.rename(columns=str.lower)
        c = d["close"].astype(float)
        c.index = pd.DatetimeIndex(c.index).tz_localize(None).normalize() \
            if getattr(c.index, "tz", None) is not None else pd.DatetimeIndex(c.index).normalize()
        if len(c) < 30:
            return out
        px = float(c.iloc[-1])
        last = len(c) - 1
        # NaN 闸:坏 bar / 全空数据会一路算出 nan,渲染成「$nan」推给用户。
        # 这个仓库 2026-07-30 就被上游坏 bar 坑过一次(见 options.py spot 那段注释)。
        if not np.isfinite(px) or px <= 0:
            return out
        if green is None:
            green = _qqq_green()
        if risk_on is None and green is not None:
            risk_on = bool(green.reindex(c.index).ffill().iloc[-1])

        # ── ① 5日swing(5日新低买)× QQQ50 ────────────────────────────
        prior_low = float(c.iloc[-(SWING_LB + 1):-1].min())
        prior_high = float(c.iloc[-(SWING_LB + 1):-1].max())
        bare = px < prior_low
        sw_trades, sw_pos = _sim_swing(c, green) if green is not None else ([], None)
        if sw_pos is not None and sw_pos["i"] < last:
            n = last - sw_pos["i"]
            out["lines"].append(
                f"· 5日swing:规则内已在场({_date(sw_pos['date'])} ${sw_pos['px']:.2f} 进,"
                f"第 {n} 天,{px / sw_pos['px'] - 1:+.1%})· 出场:收盘 > ${prior_high:.2f} 或第 {SWING_MAX} 天"
                + ("。今天又创新低 —— **不是新买点**,规则一次只拿一笔" if bare else ""))
        elif bare and risk_on:
            out["fired"].append({
                "key": "swing", "name": "5日swing(5日新低买)",
                "detail": f"收盘 ${px:.2f} < 前5日最低 ${prior_low:.2f},且大盘绿灯",
                "backtest": f"回测 72% 胜率(23/32) · {_live_record(sw_trades)}"})
        elif bare and risk_on is False:
            out["lines"].append(
                f"· 5日swing 裸腿亮了(${px:.2f} < 前5日低 ${prior_low:.2f}),"
                f"但**大盘红灯挡住** —— 在册版本是 5日swing×QQQ50,不算买入信号")
        else:
            if np.isfinite(prior_low):
                out["pending"].append({
                    "key": "swing", "name": "5日swing",
                    "trigger_px": round(prior_low, 2),
                    "distance": round(prior_low / px - 1, 4),
                    "gate": ("绿灯✅" if risk_on else
                             "红灯🔴" if risk_on is False else "闸门未知")})

        # ── ② 深坑抄底(跌 20% 于 20 日高)───────────────────────────
        hi20 = float(c.rolling(20).max().iloc[-1])
        dd = px / hi20 - 1
        trig_px = hi20 * (1 - DIP_DRAW)
        dp_trades, dp_pos = _sim_dip(c)
        if dp_pos is not None and dp_pos["i"] < last:
            n = last - dp_pos["i"]
            out["lines"].append(
                f"· 深坑抄底:规则内已在场({_date(dp_pos['date'])} ${dp_pos['px']:.2f} 进,"
                f"第 {n} 天,{px / dp_pos['px'] - 1:+.1%})· 出场:收盘 ≥ ${dp_pos['exit_px']:.2f} 或第 {DIP_MAX} 天"
                + ("。今天仍在坑里 —— **不是新买点**" if dd <= -DIP_DRAW else ""))
        elif dd <= -DIP_DRAW:
            out["fired"].append({
                "key": "dip", "name": "深坑抄底(跌20%于20日高)",
                "detail": f"20日高 ${hi20:.2f} → 现价回撤 {dd*100:.1f}%",
                "backtest": f"回测 64%@25 · {_live_record(dp_trades)}"})
        elif np.isfinite(trig_px):
            out["pending"].append({
                "key": "dip", "name": "深坑抄底",
                "trigger_px": round(trig_px, 2),
                "distance": round(trig_px / px - 1, 4), "gate": "—"})
    except Exception as e:
        logger.warning("buy_triggers check failed: %s", str(e)[:100])
    return out


def render_lines(res: dict, tj_pending_px: float | None = None) -> str:
    """拼进心跳正文的几行。没内容返回空串。"""
    if not res:
        return ""
    L = []
    for f in res.get("fired", []):
        L.append(f"🔔 {f['name']} 触发 —— {f['detail']}（{f['backtest']}）")
    L.extend(res.get("lines", []))
    pend = res.get("pending", [])
    if tj_pending_px:
        pend = [{"name": "特调抄底腿", "trigger_px": tj_pending_px,
                 "distance": None, "gate": "需先跌破再收回"}] + pend
    if pend:
        bits = []
        for p in pend:
            dist = f"{p['distance']*100:+.1f}%" if p.get("distance") is not None else "—"
            bits.append(f"{p['name']} ${p['trigger_px']}({dist})")
        L.append("· 还没到的: " + " | ".join(bits))
    return "\n".join(L)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    logging.basicConfig(level=logging.INFO)
    sys.path.insert(0, str(Path(__file__).parent.parent))
    import yfinance as yf

    df = yf.download("QBTS", period="1y", interval="1d",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    r = check(df)
    import json
    print(json.dumps(r, ensure_ascii=False, indent=2))
    print()
    print(render_lines(r))
