"""
Meta-Model Edge — the single decision-grade output of the system.

Combines ALL signal sources into a probabilistic edge:
  - Mined ML/rule factors (weighted by OOS Sharpe — REAL track record)
  - 8 classic academic strategies (weighted by confidence; future: hit-rate)
  - News aggregate sentiment (small tilt, mostly already priced)

Output:
  p_up                  P(QBTS up over next ~5 bars | all signals)
  expected_return_pct   E[fractional return] (ATR-scaled)
  kelly_fraction        Optimal capital fraction by Kelly (capped at half-Kelly)
  log_odds              Pre-sigmoid combined log-odds (sign = direction, |·| = strength)
  contributions         Sorted list of which signals contributed how much

Why log-odds combination (not voting):
  log-odds is the right scale for combining independent Bayesian evidence.
  Each signal source converts to "how much it shifts P(up) from 50%".
  Strong sources with track record shift more; weak sources shift less.
  Sigmoid at the end gives a calibrated probability.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from dashboard.calibration import load_learned_weights


@dataclass
class Contribution:
    source:   str
    kind:     str        # "mined" / "classic" / "news" / "regime"(v2 实测机制门)
    signal:   int        # -1 / 0 / +1
    weight:   float      # max log-odds magnitude (always >= 0)
    log_odds: float      # signal × weight (signed)
    detail:   str        # short rationale string

    def to_dict(self) -> dict:
        return {
            "source":   self.source,
            "kind":     self.kind,
            "signal":   int(self.signal),
            "weight":   round(float(self.weight), 3),
            "log_odds": round(float(self.log_odds), 3),
            "detail":   self.detail,
        }


# Weight calibration: each constant is the MAX log-odds a single signal of
# that kind can move the meta-model.
_MINED_WEIGHT_PER_SHARPE = 0.8     # a Sharpe-1.5 mined factor contributes ~1.2 log-odds
_CLASSIC_WEIGHT_BASE     = {"high": 0.40, "medium": 0.20, "low": 0.08}
_NEWS_WEIGHT             = 0.15    # news barely moves p_up — usually already priced
_REL_STRENGTH_WEIGHT     = 0.20    # leading/lagging the peer basket — a dynamic, price-responsive tell
_SENTIMENT_WEIGHT        = 0.12    # retail Reddit sentiment (Adanos) — weak/laggy, small tilt only


def _build_contributions(
    snapshot: dict,
    today_signals: dict | None,
    options_signal: dict | None,
    intraday_signal: dict | None,
    holdings_signal: dict | None,
) -> list[Contribution]:
    """Per-source contribution list — IDENTICAL between v1 and v2, the two
    model generations only differ in how they're AGGREGATED (see compute_edge_v1
    vs compute_edge below). Extracted 2026-07-21 so the original v1 aggregation
    can be reconstructed exactly for the inverse-weight shadow track."""
    contributions: list[Contribution] = []

    # Load learned weight multipliers (Tier 3 self-learning).
    # Each source's weight is multiplied by mult ∈ [~0.45, ~2.0] based on its
    # historical hit rate. Defaults to 1.0 for sources without enough samples.
    learned = load_learned_weights()
    def _learn_mult(src: str) -> float:
        return float(learned.get(src, 1.0))

    # 1) Mined factors — validated alpha, dominant weight
    if today_signals and today_signals.get("factors"):
        for f in today_signals["factors"]:
            sig = int(f.get("signal", 0) or 0)
            if sig == 0:
                continue
            sharpe = float(f.get("oos_sharpe", 0.0) or 0.0)
            if sharpe <= 0:
                continue
            src = f.get("name", "?")
            base_w = sharpe * _MINED_WEIGHT_PER_SHARPE
            w  = base_w * _learn_mult(src)
            lo = sig * w
            mult = _learn_mult(src)
            extra = f" · 学习权重 ×{mult:.2f}" if mult != 1.0 else ""
            contributions.append(Contribution(
                source=src, kind="mined",
                signal=sig, weight=w, log_odds=lo,
                detail=f"OOS Sharpe {sharpe:.2f} · 命中率 {f.get('hit_rate', 0)*100:.0f}%{extra}",
            ))

    # 2) Classic strategies — confidence-weighted × learned multiplier
    for s in snapshot.get("strategies", []):
        sig = int(s.get("signal", 0) or 0)
        if sig == 0:
            continue
        src  = s.get("name", "?")
        conf = s.get("confidence", "low")
        base_w = _CLASSIC_WEIGHT_BASE.get(conf, 0.05)
        w  = base_w * _learn_mult(src)
        lo = sig * w
        mult = _learn_mult(src)
        extra = f" · 学习权重 ×{mult:.2f}" if mult != 1.0 else ""
        contributions.append(Contribution(
            source=src, kind="classic",
            signal=sig, weight=w, log_odds=lo,
            detail=f"{conf} · {s.get('rationale','')[:50]}{extra}",
        ))

    # 3) News aggregate — small tilt
    news_agg = snapshot.get("news", {}).get("aggregate", {})
    news_sig = int(news_agg.get("signal", 0) or 0)
    if news_sig != 0:
        net = news_agg.get("n_bull", 0) - news_agg.get("n_bear", 0)
        n_items = max(news_agg.get("n_items", 1), 1)
        intensity = abs(net) / n_items
        base_w = _NEWS_WEIGHT * (0.4 + 0.6 * intensity)
        w  = base_w * _learn_mult("新闻聚合情绪")
        lo = news_sig * w
        contributions.append(Contribution(
            source="新闻聚合情绪", kind="news",
            signal=news_sig, weight=w, log_odds=lo,
            detail=(f"看多 {news_agg.get('n_bull',0)} · "
                    f"看空 {news_agg.get('n_bear',0)} · "
                    f"中性 {news_agg.get('n_neutral',0)}"),
        ))

    # 4) Options flow (Tier 2a) — PCR + churn
    if options_signal and options_signal.get("signal", 0) != 0:
        sig = int(options_signal["signal"])
        base_w = float(options_signal.get("log_odds_magnitude", 0.0))
        w  = base_w * _learn_mult("期权流")
        lo = sig * w
        contributions.append(Contribution(
            source="期权流", kind="classic",
            signal=sig, weight=w, log_odds=lo,
            detail=options_signal.get("rationale", "")[:80],
        ))

    # 5) Intraday volume surge (Tier 2b) — last-hour vs daily avg
    if intraday_signal and intraday_signal.get("signal", 0) != 0:
        sig = int(intraday_signal["signal"])
        base_w = float(intraday_signal.get("log_odds_magnitude", 0.0))
        w  = base_w * _learn_mult("盘中量能")
        lo = sig * w
        contributions.append(Contribution(
            source="盘中量能", kind="classic",
            signal=sig, weight=w, log_odds=lo,
            detail=intraday_signal.get("rationale", "")[:80],
        ))

    # 6) Retail sentiment (Adanos Reddit buzz + sentiment) — a small, dynamic
    #    tilt off the snapshot; weak/laggy so low weight. Replaces the dead Reddit
    #    API signal (Reddit is approval-gated + bans AI use since 2026-06).
    st = snapshot.get("sentiment") or {}
    st_sig = int(st.get("signal", 0) or 0)
    if st_sig != 0:
        w  = _SENTIMENT_WEIGHT * _learn_mult("散户情绪")
        lo = st_sig * w
        contributions.append(Contribution(
            source="散户情绪", kind="news",
            signal=st_sig, weight=w, log_odds=lo,
            detail=st.get("note", "")[:80],
        ))

    # 7) 13F institutional holdings — "smart money" tracking
    if holdings_signal and holdings_signal.get("signal", 0) != 0:
        sig = int(holdings_signal["signal"])
        base_w = float(holdings_signal.get("log_odds_magnitude", 0.0))
        w  = base_w * _learn_mult("机构持仓 (13F)")
        lo = sig * w
        contributions.append(Contribution(
            source="机构持仓 (13F)", kind="classic",
            signal=sig, weight=w, log_odds=lo,
            detail=holdings_signal.get("rationale", "")[:80],
        ))

    # 8) Relative strength vs peer basket — leading/lagging the quantum peers is
    #    a genuinely price-RESPONSIVE directional tell (unlike the static quarterly
    #    13F). It shifts daily with QBTS's relative performance, adding a dynamic
    #    axis the meta-model otherwise lacks. Reads straight off the snapshot.
    rs = snapshot.get("relative_strength") or {}
    rs_sig = int(rs.get("signal", 0) or 0)
    if rs_sig != 0:
        w  = _REL_STRENGTH_WEIGHT * _learn_mult("相对强度")
        lo = rs_sig * w
        lead = {"leader": "领先", "laggard": "落后"}.get(rs.get("leadership", ""), rs.get("leadership", ""))
        contributions.append(Contribution(
            source="相对强度", kind="classic",
            signal=rs_sig, weight=w, log_odds=lo,
            detail=f"{lead}量子篮子 · {rs.get('rationale', '')[:60]}",
        ))

    return contributions


def _p_up_ev_kelly(log_odds: float, snapshot: dict) -> tuple[float, float, float]:
    """Shared sigmoid → EV → Kelly math, identical in v1 and v2 (only the
    log_odds fed in differs)."""
    p_up = 1.0 / (1.0 + math.exp(-log_odds))
    atr_abs = float(snapshot.get("chart", {}).get("atr_14", 0.0) or 0.0)
    price   = float(snapshot.get("price", 0.0) or 0.0)
    atr_pct = (atr_abs / price) if price > 0 else 0.05
    horizon_factor = 1.6    # ~5-bar forward, sqrt(5/2) ≈ 1.58
    expected_return = math.tanh(log_odds * 0.7) * atr_pct * horizon_factor
    var = (atr_pct * horizon_factor) ** 2
    raw_kelly = expected_return / var if var > 1e-9 else 0.0
    kelly = max(-0.5, min(0.5, 0.5 * raw_kelly))
    return p_up, expected_return, kelly


def compute_edge_v1(
    snapshot: dict,
    today_signals: dict | None = None,
    options_signal: dict | None = None,
    intraday_signal: dict | None = None,
    holdings_signal: dict | None = None,
) -> dict:
    """The ORIGINAL (pre-2026-07-17) meta-model, byte-for-byte reconstructed:
    raw uncapped log-odds sum, no regime term, EV±1% label threshold. This is
    the model that ran live for a month and graded 21%/24 hit rate (Wilson95%
    upper bound 38% < 50% — significantly worse than random).

    Exists ONLY to power the 2026-07-21 inverse-weight shadow track (user's
    idea, following the AI self-check's suggestion): if a model is reliably
    wrong, its exact opposite is a candidate edge — but that hypothesis is
    UNTESTED prospectively (the 19-21% could be small-sample noise, not a
    stable anti-correlation), so it is measured here as a zero-authority
    shadow call (mirrors shadow_ds/DeepSeek), never fed into the real decision
    or edge.py's compute_edge (v2, unchanged). Graded the same fwd5 way,
    judged 8/15 alongside everything else."""
    contributions = _build_contributions(
        snapshot, today_signals, options_signal, intraday_signal, holdings_signal)
    log_odds = sum(c.log_odds for c in contributions)   # no per-source cap, no soft cap
    p_up, expected_return, kelly = _p_up_ev_kelly(log_odds, snapshot)

    # v1 用 EV±1% 判(不是 v2 的 p_up 死区)—— 这正是 v1 的病根之一:54% 就敢喊 BUY
    if expected_return >= 0.01:
        label, signal = "BUY", 1
    elif expected_return <= -0.01:
        label, signal = "SELL", -1
    else:
        label, signal = "HOLD", 0

    contributions.sort(key=lambda c: abs(c.log_odds), reverse=True)
    return {
        "signal":               signal,
        "label":                label,
        "model":                "v1",      # 原始版,2026-07-17 起停用,仅供反向影子复现
        "p_up":                 round(p_up, 4),
        "expected_return_pct":  round(expected_return, 4),
        "kelly_fraction":       round(kelly, 4),
        "log_odds":             round(log_odds, 4),
        "n_signals":            len(contributions),
        "contributions":        [c.to_dict() for c in contributions[:10]],
    }


def compute_edge(
    snapshot: dict,
    today_signals: dict | None = None,
    options_signal: dict | None = None,
    intraday_signal: dict | None = None,
    holdings_signal: dict | None = None,
) -> dict:
    """
    Pure function. No I/O. Takes the dashboard snapshot + optional signal
    payloads and returns the meta-model verdict (v2 — see module docstring
    and mining.md 第二十四轮 for why the aggregation looks like this).
    """
    contributions = _build_contributions(
        snapshot, today_signals, options_signal, intraday_signal, holdings_signal)

    # ══ v2 聚合(2026-07-17 重设计;出身:v1 上线一个月 22 条 21% 命中的审判)══
    # v1 两个病根,都是结构性的:
    #  ① 相关信号当独立证据裸加 —— 单边下跌里新闻/情绪/超卖类集体看多,log-odds
    #     无上限堆叠(v1 在 07-02→07-16 −25% 一路上天天喊 BUY)。
    #     → 单源帽 ±0.35(13F 教训)+ 软信号合计帽 ±0.50(相关性收缩)。
    #  ② 模型没有任何趋势/机制项,感知不到"现在是下跌趋势"。
    #     → regime 项,常数为 2 年 walk-forward 实测(第二十四轮,2024-07~2026-07,
    #       产线同款锁引擎零前视):基准 P(5d up)=49.1%;日线锁 bull 52.6%/bear
    #       45.7%(相对 log-odds ±0.14);QQQ 50 日线上 52.5%(+0.13)/线下 41.9%
    #       (−0.29,n=160,全场最强单项)。
    _SRC_CAP, _SOFT_CAP = 0.35, 0.50
    soft = sum(max(-_SRC_CAP, min(_SRC_CAP, c.log_odds)) for c in contributions)
    soft = max(-_SOFT_CAP, min(_SOFT_CAP, soft))

    regime_lo = 0.0
    lock = (((snapshot.get("smc") or {}).get("playbook")) or {}).get("lock")
    if lock in ("bull", "bear"):
        lo_lock = 0.14 if lock == "bull" else -0.14
        regime_lo += lo_lock
        contributions.append(Contribution(
            source="日线方向锁", kind="regime", signal=1 if lock == "bull" else -1,
            weight=abs(lo_lock), log_odds=lo_lock,
            detail=f"lock={lock} · 实测 P(5d up)={'52.6%' if lock=='bull' else '45.7%'}(2年walk-forward)"))
    qqq_vs = ((snapshot.get("market_light") or {}).get("qqq_vs_50dma"))
    if isinstance(qqq_vs, (int, float)):
        lo_q = 0.13 if qqq_vs > 0 else -0.29
        regime_lo += lo_q
        contributions.append(Contribution(
            source="大盘机制(QQQ vs 50日线)", kind="regime", signal=1 if qqq_vs > 0 else -1,
            weight=abs(lo_q), log_odds=lo_q,
            detail=f"QQQ {'上方' if qqq_vs > 0 else '下方'}{abs(qqq_vs)*100:.1f}% · "
                   f"实测 P(5d up)={'52.5%' if qqq_vs > 0 else '41.9%'}"))

    log_odds = soft + regime_lo
    p_up, expected_return, kelly = _p_up_ev_kelly(log_odds, snapshot)

    # v2 死区:p_up 出 [42%, 58%] 才给方向(v1 用 EV±1% 判,54% 就敢喊 BUY —— 22 条
    # 21% 命中里一多半是这种弱信号;方向弱就承认没方向)
    if p_up >= 0.58:
        label, signal = "BUY", 1
    elif p_up <= 0.42:
        label, signal = "SELL", -1
    else:
        label, signal = "HOLD", 0

    contributions.sort(key=lambda c: abs(c.log_odds), reverse=True)

    return {
        "signal":               signal,
        "label":                label,
        "model":                "v2",     # 2026-07-17 重设计;校准/审判按代际分开
        "p_up":                 round(p_up, 4),
        "expected_return_pct":  round(expected_return, 4),
        "kelly_fraction":       round(kelly, 4),
        "log_odds":             round(log_odds, 4),
        "log_odds_soft":        round(soft, 4),
        "log_odds_regime":      round(regime_lo, 4),
        "n_signals":            len(contributions),
        "contributions":        [c.to_dict() for c in contributions[:10]],
    }
