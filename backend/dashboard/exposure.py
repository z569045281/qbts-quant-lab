"""
敞口刻度(2026-08-24,mining 第四十二轮 建议③ 落地)。

## 为什么有这个模块

系统 91% 的日子输出「观望」。归因(2026-08-22)是 `conviction ≤4 → 强制 HOLD`
挡下了 86% 的决策。但闸门本身是对的 —— 方向确实不可预测(42 轮实证)。
**真正的毛病是出口只有一个**:BUY / SELL / HOLD 三选一,而 HOLD 会把
`suggested_position_pct` 直接写成 0。

于是「今天该不该开新仓」和「我手上这些该拿多大」被压成了同一个问题。
它们不是同一个问题:

  - **方向**(今天买不买)—— 不可预测。闸门保持原样,一个字不动。
  - **大小**(该拿几成)   —— **可预测**,而且是这套系统里唯一被反复验证过的东西。

本模块只回答第二个。它不产生方向观点,不解除任何闸门,不碰四条铁律。

## 刻度怎么算

`敞口 = clamp(0.60 / 波动率, 20%, 100%)`,单位是**投机仓的百分比**
(投机仓本身 ≤ 总资产 10%,总闸不动)。

**分母用 `max(20日已实现波动, ATM隐含波动)`** —— 2026-08-24 换的,理由:

| 分母 | 对未来 21 日实现波动的相关 | 平均绝对误差 |
|---|---|---|
| rv20(旧) | 0.384 | 0.524 |
| **隐含波动率(新)** | **0.610** | **0.354** |

换分母后(QBTS 2024-02→2026-07,费后 0.2%/边):

| | 倍数 | 最大回撤 | 夏普 |
|---|---|---|---|
| 买入持有 | 14.85x | −71% | 1.71 |
| ÷ rv20(旧) | 4.91x | −57% | 1.57 |
| **÷ 两者取大(本模块)** | 4.61x | **−46%** | **1.67** |

**分半稳健**:前半回撤 −22% vs −33%、后半 −46% vs −57% —— 两个半窗都改善。
取大(而非直接用隐含)是刻意的保守选择,且有一个工程好处:
**期权源挂掉时 `iv=None` → 自动退回 rv20 = 完全等于当前在产行为**,不会突然放大敞口。

## 为什么没有加倾斜项

试过三个(大盘红绿灯 / 60日过热 / 低波蓄势),四票 × 三窗口回测:
没有一个能同时在全期和近 1 年跑赢纯波动率目标,「低波蓄势」几乎每格都拖后腿。
**判死,别再加。** 详见 mining.md 第四十二轮。

## 地板为什么是 20% 而不是 0

第四十一轮:QBTS 近 3 年错过最好的 10 天(占 1.3% 交易日)= +1,531% 变 −29%,
且最好的 20 天里 8 天紧贴最差的 20 天。**刻度永不归零**,否则就是在赌那 1.3%。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

TARGET_VOL = 0.60        # 目标年化波动。第二十四轮标定,别乱动
FLOOR = 0.20             # 地板:永不归零(第四十一轮)
CEIL = 1.00              # 天花板:投机仓的 100%,不是总资产的 100%

# 档位名 —— 给用户一个能直接照做的词,而不是一个小数
_BANDS = [
    (0.85, "满档",  "波动低,这是刻度允许的上限"),
    (0.65, "偏重",  "波动偏低,可以拿多一点"),
    (0.45, "半仓",  "波动中性"),
    (0.30, "轻仓",  "波动偏高,刻度自动缩小"),
    (0.00, "底仓",  "波动很高,只留地板仓位 —— 但不清零"),
]


def _band(pct: float) -> tuple[str, str]:
    for lo, name, note in _BANDS:
        if pct >= lo:
            return name, note
    return _BANDS[-1][1], _BANDS[-1][2]


def compute_exposure(regime: dict | None, options_signal: dict | None) -> dict:
    """
    regime          —— `regime.analyze_regime()` 的返回(要 realized_vol_20d)
    options_signal  —— `options.get_options_signal()` 的返回(可选,要 atm_iv.atm_iv)

    任一缺失都安全降级,绝不抛异常 —— 这个数字每天都要出现在决策卡上。
    """
    rv = None
    if regime:
        try:
            rv = float(regime.get("realized_vol_20d") or 0) or None
        except (TypeError, ValueError):
            rv = None

    iv = None
    if options_signal:
        try:
            iv = float((options_signal.get("atm_iv") or {}).get("atm_iv") or 0) or None
        except (TypeError, ValueError, AttributeError):
            iv = None

    # 分母:两者取大。缺谁用谁;都缺则退到 50%(与 regime.py 原有兜底一致)
    if rv and iv:
        denom, src = max(rv, iv), ("隐含" if iv >= rv else "已实现")
    elif rv:
        denom, src = rv, "已实现(期权源缺失,已降级)"
    elif iv:
        denom, src = iv, "隐含(日线波动缺失)"
    else:
        return {
            "pct": 0.50, "band": "半仓", "degraded": True,
            "denominator": None, "denominator_source": None,
            "rv20": None, "atm_iv": None,
            "note": "波动率数据全缺 → 退回中性 50%,今天不要据此调仓。",
        }

    pct = max(FLOOR, min(CEIL, TARGET_VOL / denom))
    band, band_note = _band(pct)

    return {
        "pct": round(pct, 2),
        "band": band,
        "band_note": band_note,
        "degraded": iv is None,
        "denominator": round(denom, 3),
        "denominator_source": src,
        "rv20": round(rv, 3) if rv else None,
        "atm_iv": round(iv, 3) if iv else None,
        "floor": FLOOR,
        "ceiling": CEIL,
        "unit": "投机仓的百分比(投机仓本身 ≤ 总资产 10%,总闸不动)",
        "note": (
            f"敞口刻度 {pct*100:.0f}%({band}) —— "
            f"0.60 ÷ max(20日已实现 {rv*100:.0f}%, 隐含 {iv*100:.0f}%) = {TARGET_VOL/denom*100:.0f}%,"
            f"夹 {FLOOR*100:.0f}–{CEIL*100:.0f}%。"
            if (rv and iv) else
            f"敞口刻度 {pct*100:.0f}%({band}) —— 0.60 ÷ {src} {denom*100:.0f}%,"
            f"夹 {FLOOR*100:.0f}–{CEIL*100:.0f}%。"
        ),
        "discipline": (
            "这是【持仓刻度】不是【入场信号】:它只说「拿多大」,不说「往哪买」。"
            "方向由 action/conviction 那条链路管,本刻度不解除任何闸门。"
            "HOLD 日照样有刻度 —— 意思是「今天不开新仓,但已有的仓位按这个大小活着」。"
        ),
    }


def render_for_prompt(exp: dict) -> str:
    """决策提示词里的敞口段。取代旧的 `regime.vol_target` 那段(避免两个数字打架)。"""
    if not exp:
        return ""
    lines = [f"## 敞口刻度（回测验证过的唯一 sizing 规则；只管大小，不管方向）",
             f"  {exp.get('note','')}"]
    if exp.get("degraded"):
        lines.append("  ⚠️ 期权源缺失，已降级为纯已实现波动率口径（= 换分母之前的在产行为）。")
    lines.append(f"  {exp.get('discipline','')}")
    lines.append(
        "  纪律（代码强制，不是建议）：`suggested_position_pct`（占投机仓 0-100）的"
        f"天花板 = 本刻度 {exp.get('pct', 0)*100:.0f}%；conviction 5-6 档再减半。"
        "超了会被 `_sanitize_decision` 直接截断。\n"
        "  刻度按波动自动缩放，是回测验证过的仓位天花板，**不是方向观点** —— "
        "刻度高不等于该买，刻度低也不等于该卖。"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    import options
    from data.fetcher import load_or_fetch
    from regime import analyze_regime

    _, df_d = load_or_fetch()
    reg = analyze_regime(df_d)
    opt = options.get_options_signal()
    e = compute_exposure(reg, opt)
    print(json.dumps(e, ensure_ascii=False, indent=2))
    print()
    print(render_for_prompt(e))
