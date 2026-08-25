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
SWING_LB = 5           # 5日swing 回看(第七轮参数扫:5-7 天甜区,3 天是噪声悬崖)


def _qqq_risk_on() -> bool | None:
    """大盘红绿灯:QQQ vs 50 日线。取不到返回 None(不猜)。"""
    try:
        import yfinance as yf
        q = yf.download("QQQ", period="6mo", interval="1d",
                        auto_adjust=True, progress=False)
        if isinstance(q.columns, pd.MultiIndex):
            q.columns = q.columns.get_level_values(0)
        c = q["Close"].dropna()
        if len(c) < 50:
            return None
        return bool(c.iloc[-1] > c.rolling(50).mean().iloc[-1])
    except Exception as e:
        logger.warning("qqq light failed: %s", str(e)[:80])
        return None


def check(df_d: pd.DataFrame, risk_on: bool | None = None) -> dict:
    """
    df_d —— QBTS 日线(含 OHLC,大小写均可)。
    返回 {fired: [...], pending: [...], lines: [...]}。任何异常都吞掉返回空,
    因为它挂在每日心跳上 —— 宁可少报一条,不能让整条推送死掉。
    """
    out = {"fired": [], "pending": [], "lines": []}
    try:
        d = df_d.rename(columns=str.lower)
        c, h = d["close"].astype(float), d["high"].astype(float)
        if len(c) < 30:
            return out
        px = float(c.iloc[-1])
        # NaN 闸:坏 bar / 全空数据会一路算出 nan,渲染成「$nan」推给用户。
        # 这个仓库 2026-07-30 就被上游坏 bar 坑过一次(见 options.py spot 那段注释)。
        if not np.isfinite(px) or px <= 0:
            return out
        if risk_on is None:
            risk_on = _qqq_risk_on()

        # ── ① 5日swing(5日新低买)× QQQ50 ────────────────────────────
        prior_low = float(c.iloc[-(SWING_LB + 1):-1].min())
        bare = px < prior_low
        if bare and risk_on:
            out["fired"].append({
                "key": "swing", "name": "5日swing(5日新低买)",
                "detail": f"收盘 ${px:.2f} < 前5日最低 ${prior_low:.2f},且大盘绿灯",
                "backtest": "在册 72% 胜率(23/32),近1年 +75%"})
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
        if dd <= -DIP_DRAW:
            out["fired"].append({
                "key": "dip", "name": "深坑抄底(跌20%于20日高)",
                "detail": f"20日高 ${hi20:.2f} → 现价回撤 {dd*100:.1f}%",
                "backtest": "在册 64%@25,全期 +1914%"})
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
