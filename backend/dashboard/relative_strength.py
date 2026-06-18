"""
Relative strength — QBTS vs the quantum peer basket + risk regime.

QBTS almost never moves alone; it trades as a high-beta member of the quantum
basket (IONQ, RGTI) and breathes with the broad tape (QQQ) and risk appetite
(VIX). Whether it's LEADING or LAGGING that basket is one of the highest-signal,
least-redundant reads available — a name that leads its sector on up days and
resists on down days is being accumulated; a chronic laggard is distribution.

The codebase already has peer features ([strategy_peer_lead_lag], ML rel_*), but
only as a single lead-lag rule. This promotes it to a first-class leadership +
risk-regime read fed to the decision prompt.

Inputs: QBTS daily bars + the cached peers_1d parquet (ionq/rgti/qqq/vix).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_PEER_CACHE = Path(__file__).parent.parent / "data" / "cache" / "peers_1d.parquet"


def _ret(series: pd.Series, n: int) -> float:
    if len(series) <= n:
        return 0.0
    return float(series.iloc[-1] / series.iloc[-1 - n] - 1)


def analyze_relative_strength(df_d: pd.DataFrame) -> dict:
    if not _PEER_CACHE.exists():
        return {"signal": 0, "label": "HOLD", "rationale": "同行数据缺失（peers_1d 未生成）"}
    try:
        peers = pd.read_parquet(_PEER_CACHE)
    except Exception as e:
        return {"signal": 0, "label": "HOLD", "rationale": f"同行数据读取失败: {str(e)[:60]}"}

    # align peers onto QBTS trading days
    qbts = df_d["close"]
    peers = peers.reindex(pd.DatetimeIndex(qbts.index).normalize(), method="ffill")
    basket_cols = [c for c in ("ionq", "rgti") if c in peers.columns]
    if not basket_cols:
        return {"signal": 0, "label": "HOLD", "rationale": "同行篮子列缺失"}
    basket = peers[basket_cols].mean(axis=1)

    rel, qr, br = {}, {}, {}
    for n, key in ((1, "1d"), (5, "5d"), (20, "20d")):
        qr[key] = _ret(qbts, n)
        br[key] = _ret(basket, n)
        rel[key] = round(qr[key] - br[key], 4)

    # 20-day beta of QBTS to the basket (sensitivity, not direction)
    qret = qbts.pct_change().tail(20)
    bret = basket.pct_change().tail(20)
    aligned = pd.concat([qret, bret], axis=1).dropna()
    beta = float(np.polyfit(aligned.iloc[:, 1], aligned.iloc[:, 0], 1)[0]) if len(aligned) >= 5 else None

    # leadership over the 5d+20d horizon
    if rel["5d"] > 0.01 and rel["20d"] > 0:
        leadership = "leader"
    elif rel["5d"] < -0.01 and rel["20d"] < 0:
        leadership = "laggard"
    elif beta is not None and abs(beta) < 0.3:
        leadership = "decoupled"
    else:
        leadership = "inline"

    # risk regime from VIX
    vix = float(peers["vix"].iloc[-1]) if "vix" in peers.columns else None
    vix_chg = _ret(peers["vix"], 5) if "vix" in peers.columns else 0.0
    if vix is not None and vix >= 22 and vix_chg > 0.10:
        risk = "off"
    elif vix is not None and vix <= 16 and vix_chg < 0:
        risk = "on"
    else:
        risk = "neutral"

    signal = 1 if leadership == "leader" else (-1 if leadership == "laggard" else 0)
    lead_cn = {"leader": "领先", "laggard": "落后", "decoupled": "脱钩", "inline": "同步"}[leadership]
    risk_cn = {"on": "risk-on", "off": "risk-off", "neutral": "中性"}[risk]

    rationale = (f"QBTS 相对量子篮子(IONQ/RGTI)：5日 {rel['5d']*100:+.1f}%、"
                 f"20日 {rel['20d']*100:+.1f}% → {lead_cn}；")
    if beta is not None:
        rationale += f"对篮子 beta≈{beta:.2f}；"
    if vix is not None:
        rationale += f"VIX {vix:.1f}（5日 {vix_chg*100:+.0f}%）→ {risk_cn}"

    return {
        "signal":     signal,
        "label":      {1: "BUY", -1: "SELL", 0: "HOLD"}[signal],
        "leadership": leadership,
        "rel":        rel,
        "qbts_ret":   {k: round(v, 4) for k, v in qr.items()},
        "basket_ret": {k: round(v, 4) for k, v in br.items()},
        "beta_20d":   round(beta, 2) if beta is not None else None,
        "vix":        round(vix, 1) if vix is not None else None,
        "vix_chg_5d": round(vix_chg, 3),
        "risk":       risk,
        "rationale":  rationale,
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from data.fetcher import load_or_fetch
    import json
    _, df_d = load_or_fetch()
    print(json.dumps(analyze_relative_strength(df_d), ensure_ascii=False, indent=2))
