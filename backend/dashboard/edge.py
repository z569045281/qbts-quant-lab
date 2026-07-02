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
    kind:     str        # "mined" / "classic" / "news"
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


def compute_edge(
    snapshot: dict,
    today_signals: dict | None = None,
    options_signal: dict | None = None,
    intraday_signal: dict | None = None,
    holdings_signal: dict | None = None,
) -> dict:
    """
    Pure function. No I/O. Takes the dashboard snapshot + optional signal
    payloads and returns the meta-model verdict.

    Self-learning: applies per-source weight multipliers learned from
    historical prediction-vs-outcome calibration (Tier 3).
    """
    log_odds = 0.0
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
            log_odds += lo
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
        log_odds += lo
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
        log_odds += lo
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
        log_odds += lo
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
        log_odds += lo
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
        log_odds += lo
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
        log_odds += lo
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
        log_odds += lo
        lead = {"leader": "领先", "laggard": "落后"}.get(rs.get("leadership", ""), rs.get("leadership", ""))
        contributions.append(Contribution(
            source="相对强度", kind="classic",
            signal=rs_sig, weight=w, log_odds=lo,
            detail=f"{lead}量子篮子 · {rs.get('rationale', '')[:60]}",
        ))

    # Probability and expected return
    p_up = 1.0 / (1.0 + math.exp(-log_odds))

    atr_abs = float(snapshot.get("chart", {}).get("atr_14", 0.0) or 0.0)
    price   = float(snapshot.get("price", 0.0) or 0.0)
    atr_pct = (atr_abs / price) if price > 0 else 0.05
    horizon_factor = 1.6    # ~5-bar forward, sqrt(5/2) ≈ 1.58
    expected_return = math.tanh(log_odds * 0.7) * atr_pct * horizon_factor

    # Kelly (half-Kelly capped at ±50%)
    var = (atr_pct * horizon_factor) ** 2
    raw_kelly = expected_return / var if var > 1e-9 else 0.0
    kelly = max(-0.5, min(0.5, 0.5 * raw_kelly))

    abs_ev = abs(expected_return)
    if abs_ev < 0.01:
        label, signal = "HOLD", 0
    elif expected_return > 0:
        label, signal = "BUY", 1
    else:
        label, signal = "SELL", -1

    contributions.sort(key=lambda c: abs(c.log_odds), reverse=True)

    return {
        "signal":               signal,
        "label":                label,
        "p_up":                 round(p_up, 4),
        "expected_return_pct":  round(expected_return, 4),
        "kelly_fraction":       round(kelly, 4),
        "log_odds":             round(log_odds, 4),
        "n_signals":            len(contributions),
        "contributions":        [c.to_dict() for c in contributions[:10]],
    }
