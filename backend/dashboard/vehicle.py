"""
载具选择(2026-08-24,mining 第四十二轮 建议① 落地)。

## 为什么有这个模块

执行军规原本只写「QBTX 持有 ≤5 天、QBTZ 只做 1-3 天」—— 它教你**怎么少受伤**,
但从没说过**其实有不受这个伤的东西**。第四十二轮把代价量化出来了:

| 2025-04-25(QBTX 上市)→ 2026-08-21 | 倍数 | 最大回撤 |
|---|---|---|
| QBTS 正股 | **+171%** | −71% |
| QBTX 2× | **+16%** | **−95%** |

期间实现波动率 112% → 日再平衡方差拖累 **年化 ≈126%**。逐季杠杆缺口(实际 − 2×标的):
−25.8 / −12.6 / −38.6 / **+18.1** / −39.5 / −10.1 pp —— 六个季度只有暴跌那季杠杆帮了忙。

**这个损耗量级大于 42 轮挖矿在找的所有 edge。** 换载具比换信号值钱。

## 替代品:深度实值长期 call

同样的杠杆,但**没有每日再平衡**。你付的是一次性「房租」(时间价值),
金额事先锁死,不随波动放大。

**选择标准(写死在代码里,不是每次现编)**:
  - `DTE ≥ 120`     —— 太短就要频繁续租,房租吃掉优势
  - `delta ≥ 0.75`  —— 必须**跟得住正股**。delta 低 = 彩票不是替代品
  - **`有效杠杆 ∈ [1.6, 2.6]`** —— 目标是**替代 2× 的 QBTX**。
    ⚠️ 这一条是 2026-08-24 第一版跑完才加的:只按房租排序会选出 $2C/$3C 这种
    超深度实值 —— 房租确实只有年化 2%,但**有效杠杆只有 1.09×**,每张还要 $1,850。
    那等于把现金全押进去却没有杠杆,根本没解决用户的问题。**便宜的房租不是目标,
    同等敞口下的便宜房租才是。**
  - `未平仓 ≥ 200` 且 `半边价差 ≤ 10%` —— 流动性闸。QBTS 深虚 call 价差能到 32%,
                       一进一出就吃掉三分之一,再便宜的房租也补不回来
  - 幸存者里按 **年化房租** 排序,取最低

⚠️ **和 QBTX 最大的不同,必须写在推荐里**:call 到期时若正股低于行权价,
**权利金归零**。QBTX 跌一半还剩一半。这是用「确定的上限」换「不确定的流血」,
不是无风险改进。

⚠️ **本模块只给建议,不代下单**(四条铁律之一)。金额是否超 10% 总闸,用户自己核。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_CACHE = Path(__file__).parent.parent / "data" / "cache" / "vehicle_reco.json"
_CACHE.parent.mkdir(parents=True, exist_ok=True)
_TTL = 6 * 3600            # LEAP 推荐变化很慢,6 小时足够

MIN_DTE = 120
MIN_DELTA = 0.75
MIN_OI = 200
MAX_HALF_SPREAD = 0.10
LEV_LO, LEV_HI = 1.6, 2.6      # 有效杠杆窗口 —— 目标是替代 2× 的 QBTX(见模块 docstring)
QBTX_DRAG_ANNUAL = 1.26    # 第四十二轮实测(112% 实现波动率下的日再平衡方差拖累)


def _delta(spot: float, strike: float, dte: int, iv: float, r: float = 0.039) -> float:
    """BS delta。iv 用期权链自带的隐含波动率。"""
    from scipy.stats import norm
    T = max(dte, 1) / 365.0
    if spot <= 0 or strike <= 0 or iv <= 0:
        return float("nan")
    d1 = (np.log(spot / strike) + (r + iv * iv / 2) * T) / (iv * np.sqrt(T))
    return float(norm.cdf(d1))


def _scan(ticker: str, spot: float) -> list[dict]:
    import yfinance as yf

    t = yf.Ticker(ticker)
    today = pd.Timestamp.today().normalize()
    out = []
    for exp in (t.options or []):
        dte = (pd.Timestamp(exp) - today).days
        if dte < MIN_DTE:
            continue
        try:
            calls = t.option_chain(exp).calls
        except Exception:
            continue
        if calls is None or calls.empty:
            continue
        for _, row in calls.iterrows():
            try:
                k = float(row["strike"]); bid = float(row["bid"]); ask = float(row["ask"])
                oi = float(row.get("openInterest") or 0)
                iv = float(row.get("impliedVolatility") or 0)
            except (TypeError, ValueError):
                continue
            if bid <= 0 or ask <= bid or oi < MIN_OI or not (0.05 < iv < 6):
                continue
            mid = (bid + ask) / 2
            half = (ask - mid) / mid
            if half > MAX_HALF_SPREAD:
                continue
            intrinsic = max(0.0, spot - k)
            rent = mid - intrinsic                      # 时间价值 = 房租
            if rent < 0:
                continue
            dl = _delta(spot, k, dte, iv)
            if not np.isfinite(dl) or dl < MIN_DELTA:
                continue
            lev = dl * 100 * spot / (mid * 100)
            if not (LEV_LO <= lev <= LEV_HI):     # 没杠杆 = 没解决问题(见 docstring)
                continue
            out.append(dict(
                expiration=str(exp), dte=dte, strike=round(k, 2),
                bid=round(bid, 2), ask=round(ask, 2), mid=round(mid, 2),
                cost_per_contract=round(mid * 100),
                intrinsic=round(intrinsic, 2), time_value=round(rent, 2),
                rent_share=round(rent / mid, 4),
                rent_annual=round((rent / mid) * (365 / dte), 4),
                delta=round(dl, 3),
                shares_equiv=round(dl * 100),           # 一张 ≈ 多少股正股敞口
                leverage=round(lev, 2),
                breakeven=round(k + mid, 2),
                breakeven_move=round((k + mid) / spot - 1, 4),
                half_spread=round(half, 4), open_interest=int(oi),
                iv=round(iv, 3),
            ))
    out.sort(key=lambda d: d["rent_annual"])
    return out


def recommend_vehicle(spot: float | None = None, ticker: str = "QBTS",
                      force_refresh: bool = False) -> dict:
    """返回 QBTX 的替代合约推荐(前 3),失败返回 {} —— 绝不让决策卡挂掉。"""
    if not force_refresh and _CACHE.exists():
        try:
            c = json.loads(_CACHE.read_text())
            if time.time() - c.get("_ts", 0) < _TTL:
                return c["payload"]
        except Exception:
            pass
    try:
        import yfinance as yf
        if not spot or spot <= 0:
            spot = float(yf.Ticker(ticker).history(period="1d")["Close"].iloc[-1])
        cands = _scan(ticker, spot)
        payload = {
            "spot": round(spot, 2),
            "candidates": cands[:3],
            "qbtx_drag_annual": QBTX_DRAG_ANNUAL,
            "filters": {"min_dte": MIN_DTE, "min_delta": MIN_DELTA,
                        "min_oi": MIN_OI, "max_half_spread": MAX_HALF_SPREAD,
                        "leverage_window": [LEV_LO, LEV_HI]},
            "warning": ("到期时正股若低于行权价,权利金归零(QBTX 跌一半还剩一半)。"
                        "一张合约 = 100 股,金额跳跃。只给建议不代下单;"
                        "是否超 10% 总闸请自行核对。"),
        }
        if not cands:
            payload["note"] = "当前没有同时满足 DTE/delta/杠杆/流动性五道闸的合约 —— 不推荐勉强换。"
    except Exception as e:
        logger.warning("vehicle scan failed: %s", str(e)[:100])
        return {}
    try:
        _CACHE.write_text(json.dumps({"_ts": time.time(), "payload": payload},
                                     ensure_ascii=False))
    except Exception:
        pass
    return payload


def render_for_prompt(v: dict, qbtx_shares: float | None = None,
                      qbtx_price: float | None = None) -> str:
    """决策提示词里的载具段。"""
    if not v or not v.get("candidates"):
        return ""
    L = ["## 载具选择（执行军规的一部分；实测,不是观点）",
         f"  同窗实测(2025-04-25→2026-08-21)：QBTS 正股 **+171%**，QBTX 2× 只 **+16%**，"
         f"回撤 −95%。日再平衡方差拖累年化 ≈{v['qbtx_drag_annual']*100:.0f}%。",
         "  → **QBTX 不是长持工具**。军规「持有≤5天」是止血,不是解法;解法是换掉它。",
         "  无衰减替代品（深度实值长期 call，已过 DTE≥120 / delta≥0.75 / 有效杠杆 1.6-2.6× / 未平仓≥200 / 半边价差≤10% 五道闸）："]
    for c in v["candidates"]:
        L.append(
            f"    · {c['expiration']} ${c['strike']:g}C — 每张 ${c['cost_per_contract']:,}"
            f"（买{c['bid']}/卖{c['ask']}），delta {c['delta']}（≈{c['shares_equiv']} 股正股敞口，"
            f"有效杠杆 {c['leverage']}×），房租 {c['rent_share']*100:.0f}%"
            f"（**年化 {c['rent_annual']*100:.0f}%** vs QBTX 的 {v['qbtx_drag_annual']*100:.0f}%），"
            f"盈亏平衡 ${c['breakeven']}（需涨 {c['breakeven_move']*100:+.0f}%），"
            f"未平仓 {c['open_interest']:,}")
    if qbtx_shares and qbtx_price:
        eq = qbtx_shares * qbtx_price * 2 / v["spot"]
        L.append(f"  用户当前 QBTX {qbtx_shares:g} 股 × ${qbtx_price} = ${qbtx_shares*qbtx_price:,.0f}"
                 f"，2× 杠杆 ≈ **{eq:.0f} 股正股敞口** —— 换算成上面哪张、几张，"
                 f"在 position_advice 里说清楚。")
    L.append(f"  ⚠️ {v['warning']}")
    L.append("  ⚠️ 这是**载具**建议（同等敞口平移），不是**加仓**建议 —— "
             "不与「验证期不加真金」冲突;但也不得据此劝用户放大敞口。")
    return "\n".join(L)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    v = recommend_vehicle(force_refresh=True)
    print(json.dumps(v, ensure_ascii=False, indent=2))
    print()
    print(render_for_prompt(v, qbtx_shares=90, qbtx_price=9.18))
