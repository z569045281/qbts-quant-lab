"""
空头动向(原「挤空燃料」,2026-07-04 依第五轮实证整体翻转)。

旧版把 FINRA 空量比飙升当"挤空弹药"(偏多)。第五轮回测直接检验了方向:
QBTS 空量比 60 日 z>1(空头拥挤)之后 5 日均值 **+2.7%**,显著低于全样本
+5.2%;z<-1(空头撤退)之后 +7.7%。方向和 Diether, Lee & Werner (2009) 的
原始结论一致——短卖激增预示**负**超额收益,空头是聪明钱,不是燃料。
(证据强度:t≈1.1、FINRA 数据仅 ~368 天 → 风向参考,不当扳机;详见 mining.md 第五轮)

  signal +1 = 空头撤退(顺风) · 0 = 中性 · -1 = 空头拥挤(偏空,QBTZ 参考)

期权流 / 13F 只保留为上下文注脚,不再合成打分。与经典策略 Short Flow
(strategies.py,同一数据源同一方向)勿当两个独立确认。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SHORT_WIN = 60     # 空量比 z-score 窗口(与第五轮回测一致)


def _context_notes(opt_sig: dict | None, holdings_sig: dict | None) -> str:
    notes = []
    s = (opt_sig or {}).get("snapshot") or {}
    call_oi, put_oi = int(s.get("call_oi", 0)), int(s.get("put_oi", 0))
    if call_oi >= 50 and put_oi >= 50:
        notes.append(f"期权 PCR_OI={put_oi / call_oi:.2f}")
    h = (holdings_sig or {}).get("snapshot") or {}
    if h.get("active_avg_change") is not None:
        notes.append(f"13F 主动管理人净变化 {float(h['active_avg_change'])*100:+.0f}%")
    return " · ".join(notes)


def analyze_squeeze(opt_sig: dict | None, holdings_sig: dict | None) -> dict:
    try:
        from data.altdata import fetch_short_volume
        sv = fetch_short_volume(allow_network=False)
    except Exception as e:
        logger.warning(f"short data unavailable: {e}")
        sv = None
    if sv is None or sv.empty or "short_ratio" not in sv.columns:
        return {"signal": 0, "label": "HOLD", "stance": "neutral", "stance_cn": "数据缺失",
                "short_ratio": None, "short_z": None, "context": None,
                "rationale": "FINRA 短卖数据缺失,空头动向不可读。"}

    srs = sv["short_ratio"].dropna()
    sr = float(srs.iloc[-1])
    win = srs.tail(_SHORT_WIN)
    if len(win) < 30 or float(win.std()) < 1e-9:
        return {"signal": 0, "label": "HOLD", "stance": "neutral", "stance_cn": "样本不足",
                "short_ratio": round(sr, 4), "short_z": None, "context": None,
                "rationale": f"FINRA 空量比 {sr*100:.0f}%,历史样本不足以算 60 日 z。"}
    z = float((sr - win.mean()) / win.std())

    if z > 1.0:
        signal, stance, stance_cn = -1, "crowded", "空头拥挤 · 偏空"
        tail = ("空头在集中加注。实测:此后 5 日均值 +2.7%,明显差于平时的 +5.2% —— "
                "QBTS 的空头历史上是聪明钱,这是偏空风向(QBTZ 方向参考),不是挤空燃料。")
    elif z < -1.0:
        signal, stance, stance_cn = 1, "retreat", "空头撤退 · 顺风"
        tail = "空头在撤退。实测:此后 5 日均值 +7.7%,好于平时的 +5.2% —— 偏多顺风。"
    else:
        signal, stance, stance_cn = 0, "neutral", "中性"
        tail = "空头动向平稳,无方向信息。"

    ctx = _context_notes(opt_sig, holdings_sig)
    return {
        "signal":      signal,
        "label":       {1: "BUY", 0: "HOLD", -1: "SELL"}[signal],
        "stance":      stance,
        "stance_cn":   stance_cn,
        "short_ratio": round(sr, 4),
        "short_z":     round(z, 2),
        "context":     ctx or None,
        "rationale":   (f"FINRA 空量比 {sr*100:.0f}%(60日 z={z:+.1f})。{tail} "
                        f"证据强度低(t≈1.1,数据仅 ~1.5 年),只当风向不当扳机。"),
    }


if __name__ == "__main__":
    import sys, json
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from dashboard.options import get_options_signal
    from dashboard.holdings import get_holdings_signal
    print(json.dumps(
        analyze_squeeze(get_options_signal(), get_holdings_signal()),
        ensure_ascii=False, indent=2))
