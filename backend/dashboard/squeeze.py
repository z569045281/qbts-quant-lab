"""
Squeeze-fuel composite — the catalyst QBTS is most prone to.

High-short small caps like QBTS squeeze violently, but high short interest ALONE
is not bullish — it's only fuel when something is lighting it (institutions
accumulating, bears crowded in puts, fresh aggressive call buying). This module
fuses the three ingredients the system already collects into one 0–100 fuel
gauge so the decision engine doesn't have to re-derive it every call:

  short   FINRA short-volume ratio level + its 60-day pressure z-score
  options PCR_OI (bears positioned) + call_churn (new bullish ignition)
  13F     active-manager net accumulation (the confirmation that makes short
          interest "squeeze fuel" rather than just a falling knife)

Fuel is AMMUNITION, not a trigger — signal only turns bullish when fuel is high
AND at least one igniter (accumulation or bullish options) is present. Price /
structure still has to confirm; that caveat is written into the rationale.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_SHORT_WIN = 60     # window for the short-ratio pressure z-score


def _short_component() -> tuple[float, float, float | None, str]:
    """(fuel 0-40, short_ratio, pressure_z, note) from the FINRA short cache."""
    try:
        from data.altdata import fetch_short_volume
        sv = fetch_short_volume(allow_network=False)
    except Exception as e:
        logger.warning(f"short data unavailable: {e}")
        return 0.0, 0.0, None, "短仓数据缺失"
    if sv is None or sv.empty or "short_ratio" not in sv.columns:
        return 0.0, 0.0, None, "短仓数据缺失"

    sr_series = sv["short_ratio"].dropna()
    sr = float(sr_series.iloc[-1])
    win = sr_series.tail(_SHORT_WIN)
    mu, sd = float(win.mean()), float(win.std())
    z = float((sr - mu) / sd) if sd > 1e-9 else 0.0

    # 静态"绝对空量比"降权、动态"拥挤度突刺"(60日 z)加权:慢性高空头(常数)不再
    # 锁死分数,而空头快速加仓(z 突刺)能真正把燃料拉高。总分仍 0-40。
    # level: short_ratio 0.40→0, 0.65→~20。 pressure: z 0→2 → 0→20。
    level = np.clip((sr - 0.40) / 0.25, 0, 1) * 20
    pressure = np.clip(z / 2.0, 0, 1) * 20
    fuel = float(level + pressure)
    note = f"FINRA 空量比 {sr*100:.0f}%（60日 z={z:+.1f}）"
    return fuel, sr, round(z, 2), note


def _options_component(opt_sig: dict | None) -> tuple[float, str]:
    """(fuel 0-35, note) — bears positioned in puts + fresh aggressive calls.

    yfinance OI for QBTS is frequently missing (call_oi≈0), which makes PCR_OI /
    call_churn garbage. Fall back to a volume-only read when OI is unreliable.
    """
    if not opt_sig or not opt_sig.get("snapshot"):
        return 0.0, "期权数据缺失"
    s = opt_sig["snapshot"]
    call_oi  = int(s.get("call_oi", 0))
    put_oi   = int(s.get("put_oi", 0))
    call_vol = int(s.get("call_vol", 0))
    put_vol  = int(s.get("put_vol", 0))

    # OI reliable → bears-positioned (PCR_OI) + new aggressive calls (churn)
    if call_oi >= 50 and put_oi >= 50:
        pcr_oi = put_oi / call_oi
        call_churn = call_vol / call_oi
        fuel = np.clip((pcr_oi - 0.8) / 0.7, 0, 1) * 20          # PCR_OI 0.8→0, 1.5→20
        fuel += np.clip(call_churn / 0.6, 0, 1) * 15             # churn 0→0, 0.6→15
        return float(fuel), f"PCR_OI={pcr_oi:.2f} · call换手 {min(call_churn,9.99):.0%}"

    # OI missing → volume fallback: heavy call volume vs puts = some ignition
    if call_vol + put_vol < 100:
        return 0.0, "期权 OI/成交量数据缺失"
    pcr_vol = put_vol / max(call_vol, 1)
    fuel = np.clip((0.8 - pcr_vol) / 0.6, 0, 1) * 12             # call-heavy → up to 12
    return float(fuel), f"OI 缺失，按成交量近似 PCR_VOL={pcr_vol:.2f}"


def _holdings_component(holdings_sig: dict | None) -> tuple[float, str]:
    """(fuel 0-25, note) — active-manager accumulation = the igniter/confirmation."""
    if not holdings_sig or not holdings_sig.get("snapshot"):
        return 0.0, "13F 数据缺失"
    s = holdings_sig["snapshot"]
    active_change = float(s.get("active_avg_change", 0))
    # 满分门槛 +15%→+50%:否则任何有吸筹的季度都顶格 25、变成常数锁死总分。
    # 13F 是季度滞后数据,这里只作"点火源在不在"的背景确认,不主导动态。
    fuel = np.clip(active_change / 0.50, 0, 1) * 25       # +50% net → full 25
    note = f"主动管理人净变化 {active_change*100:+.0f}%"
    return float(fuel), note


def analyze_squeeze(opt_sig: dict | None, holdings_sig: dict | None) -> dict:
    short_fuel, sr, z, short_note   = _short_component()
    opt_fuel, opt_note              = _options_component(opt_sig)
    hold_fuel, hold_note            = _holdings_component(holdings_sig)

    fuel_score = round(short_fuel + opt_fuel + hold_fuel, 1)
    label = "高" if fuel_score >= 65 else ("中" if fuel_score >= 40 else "低")

    # igniter present? bullish options or active accumulation
    igniter = opt_fuel >= 8 or hold_fuel >= 8
    signal = 1 if (fuel_score >= 65 and igniter) else 0

    if signal == 1:
        tail = "燃料充足且有点火源（机构吸筹/看涨期权）——挤空做多优先级提升，但仍需价格/结构确认触发"
    elif fuel_score >= 65:
        tail = "空头拥挤但缺点火源（无吸筹、无看涨期权）——是燃料不是信号，谨防价值陷阱"
    else:
        tail = "挤空燃料不足"

    return {
        "signal":     signal,
        "label":      {1: "BUY", 0: "HOLD"}[signal],
        "fuel_score": fuel_score,
        "fuel_label": label,
        "components": {
            "short":    round(short_fuel, 1),
            "options":  round(opt_fuel, 1),
            "holdings": round(hold_fuel, 1),
        },
        "short_ratio":    round(sr, 4),
        "short_pressure_z": z,
        "rationale":  f"挤空燃料 {fuel_score}/100（{label}）：{short_note}；{opt_note}；{hold_note}。{tail}",
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from dashboard.options import get_options_signal
    from dashboard.holdings import get_holdings_signal
    import json
    print(json.dumps(
        analyze_squeeze(get_options_signal(), get_holdings_signal()),
        ensure_ascii=False, indent=2))
