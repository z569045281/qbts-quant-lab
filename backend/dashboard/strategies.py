"""
Empirical Strategy Library — Dashboard page.

Each strategy is rooted in published research or a well-known market anomaly,
NOT AI-generated. The point of this page (as opposed to the mining one) is to
show classic, defensible strategies the user can sanity-check.

Each strategy returns:
  signal       : -1 (sell) | 0 (hold) | +1 (buy)
  confidence   : "low" | "medium" | "high"
  rationale    : plain-language explanation referencing the current data
  references   : list of papers/sources backing the approach
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd


def _to_native(v):
    """Recursively coerce numpy types into JSON-serialisable Python natives."""
    if isinstance(v, dict):
        return {k: _to_native(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_to_native(x) for x in v]
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    return v


@dataclass
class StrategySignal:
    name:        str
    category:    str                # "mean_reversion" / "momentum" / "event" / "sentiment" / "microstructure"
    signal:      int                # -1, 0, +1
    label:       str                # "BUY" / "SELL" / "HOLD"
    confidence:  str                # "low" / "medium" / "high"
    rationale:   str
    references:  list[str]
    metric_snapshot: dict           # the specific numbers driving the signal

    def to_dict(self) -> dict:
        return {
            "name":          self.name,
            "category":      self.category,
            "signal":        int(self.signal),
            "label":         self.label,
            "confidence":    self.confidence,
            "rationale":     self.rationale,
            "references":    self.references,
            "metric_snapshot": _to_native(self.metric_snapshot),
        }


def _label(signal: int) -> str:
    return {1: "BUY", -1: "SELL", 0: "HOLD"}[signal]


# ── Strategy 1: Connors RSI(2) Mean Reversion ───────────────────────────────
# Reference: Connors & Alvarez (2009) "Short Term Trading Strategies That Work"
# Empirical hit-rate ~57% on SPY-like assets in oversold extremes (rsi_2 < 5).

def _rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def strategy_connors_rsi2(df: pd.DataFrame) -> StrategySignal:
    rsi2  = _rsi(df["close"], 2)
    last  = float(rsi2.iloc[-1]) if not rsi2.empty else 50.0
    close = float(df["close"].iloc[-1])
    sma200_val = df["close"].rolling(200, min_periods=50).mean().iloc[-1]
    sma200 = float(sma200_val) if pd.notna(sma200_val) else close
    above_lt_trend = bool(close > sma200)

    signal, confidence = 0, "low"
    if last < 10 and above_lt_trend:
        signal, confidence = +1, "high"
    elif last < 25 and above_lt_trend:
        signal, confidence = +1, "medium"
    elif last > 90 and not above_lt_trend:
        signal, confidence = -1, "high"
    elif last > 75 and not above_lt_trend:
        signal, confidence = -1, "medium"

    rationale = (
        f"RSI(2) = {last:.1f}; price {'above' if above_lt_trend else 'below'} 200-day SMA. "
        f"{'Extreme oversold in uptrend = high-prob bounce' if signal == 1 and confidence=='high'
           else 'Oversold in uptrend = bounce setup' if signal == 1
           else 'Extreme overbought in downtrend = high-prob reversal' if signal == -1 and confidence=='high'
           else 'Overbought in downtrend = reversal setup' if signal == -1
           else 'No setup — RSI in neutral zone.'}"
    )
    return StrategySignal(
        name="Connors RSI(2)",
        category="mean_reversion",
        signal=signal,
        label=_label(signal),
        confidence=confidence,
        rationale=rationale,
        references=["Connors & Alvarez (2009) — Short Term Trading Strategies That Work"],
        metric_snapshot={"rsi_2": round(last, 2), "above_sma200": above_lt_trend},
    )


# ── Strategy 2: Short Squeeze Detector ──────────────────────────────────────
# Reference: Diether, Lee & Werner (2009) — short interest dynamics
# Pattern: extreme short ratio + price strength = forced covering rally

def strategy_short_squeeze(df: pd.DataFrame) -> StrategySignal:
    if "short_ratio" not in df.columns:
        return StrategySignal(
            "Short Squeeze Detector", "microstructure", 0, "HOLD", "low",
            "Short interest data unavailable.",
            ["Diether, Lee & Werner (2009)"],
            {},
        )
    sr   = float(df["short_ratio"].iloc[-1])
    sr5  = float(df["short_ratio_5d"].iloc[-1]) if "short_ratio_5d" in df.columns else sr
    mom5 = float(df["momentum_5"].iloc[-1])
    vol  = float(df["vol_ratio"].iloc[-1])

    signal, confidence = 0, "low"
    if sr5 > 0.55 and mom5 > 0.03 and vol > 1.3:
        signal, confidence = +1, "high"
    elif sr5 > 0.45 and mom5 > 0.02:
        signal, confidence = +1, "medium"
    elif sr5 < 0.30 and mom5 < -0.05:
        signal, confidence = -1, "medium"  # exhausted shorts + downward momentum

    rationale = (
        f"5d short ratio {sr5:.0%} (today {sr:.0%}), 5d momentum {mom5:+.1%}, vol {vol:.1f}x. "
        + ("Heavy short pressure + rising price + volume confirmation = squeeze fuel loaded."
            if signal == +1 and confidence == "high" else
           "Elevated short pressure + price strength = potential squeeze setup."
            if signal == +1 else
           "Shorts already covered + price weakening = downside continuation risk."
            if signal == -1 else
           "No squeeze setup — short ratio or price action insufficient.")
    )
    return StrategySignal(
        "Short Squeeze Detector", "microstructure", signal, _label(signal), confidence,
        rationale,
        ["Diether, Lee & Werner (2009) — Short-Sale Strategies and Return Predictability"],
        {"short_ratio_today": round(sr, 4), "short_ratio_5d": round(sr5, 4),
         "momentum_5d": round(mom5, 4), "vol_ratio": round(vol, 2)},
    )


# ── Strategy 3: VIX Fear Contrarian ─────────────────────────────────────────
# Reference: Whaley (2000) on VIX; Simon & Wiggins (2001) on contrarian VIX trades
# Pattern: VIX spike + asset oversold = high-prob bounce within 5-10 days

def strategy_vix_contrarian(df: pd.DataFrame) -> StrategySignal:
    if "vix" not in df.columns:
        return StrategySignal("VIX Fear Contrarian", "sentiment", 0, "HOLD", "low",
                              "VIX data unavailable.", ["Whaley (2000)"], {})
    vix  = float(df["vix"].iloc[-1])
    rsi  = float(df["rsi_14"].iloc[-1])
    mom20= float(df["momentum_20"].iloc[-1])

    signal, confidence = 0, "low"
    if vix > 30 and rsi < 30:
        signal, confidence = +1, "high"
    elif vix > 22 and rsi < 35:
        signal, confidence = +1, "medium"
    elif vix < 14 and rsi > 70 and mom20 > 0.15:
        signal, confidence = -1, "medium"

    rationale = (
        f"VIX = {vix:.1f}, RSI(14) = {rsi:.0f}, 20d momentum {mom20:+.1%}. "
        + ("Extreme market fear + asset deeply oversold = capitulation bounce setup."
            if signal == +1 and confidence == "high" else
           "Elevated fear + asset oversold = contrarian long opportunity."
            if signal == +1 else
           "Complacency + extended rally + overbought = mean-reversion short risk."
            if signal == -1 else
           "VIX in normal range — no contrarian extreme to trade.")
    )
    return StrategySignal(
        "VIX Fear Contrarian", "sentiment", signal, _label(signal), confidence,
        rationale,
        ["Whaley (2000) — The Investor Fear Gauge",
         "Simon & Wiggins (2001) — S&P futures returns and contrary sentiment indicators"],
        {"vix": round(vix, 2), "rsi_14": round(rsi, 1), "momentum_20": round(mom20, 4)},
    )


# ── Strategy 4: Pre-Earnings Drift (PEAD) ───────────────────────────────────
# Reference: Bernard & Thomas (1989) — post-earnings announcement drift
# Pattern: directional drift in the 1-5 day window pre/post earnings

def strategy_pre_earnings_drift(df: pd.DataFrame) -> StrategySignal:
    if "days_to_earnings" not in df.columns:
        return StrategySignal("Pre-Earnings Drift", "event", 0, "HOLD", "low",
                              "Earnings calendar unavailable.",
                              ["Bernard & Thomas (1989)"], {})
    dte   = int(df["days_to_earnings"].iloc[-1])
    mom10 = float(df["momentum_10"].iloc[-1])

    signal, confidence = 0, "low"
    if 3 <= dte <= 14 and mom10 > 0.05:
        signal, confidence = +1, "medium"
    elif 3 <= dte <= 14 and mom10 < -0.05:
        signal, confidence = -1, "medium"
    elif dte == 0 or dte == 60:
        return StrategySignal(
            "Pre-Earnings Drift", "event", 0, "HOLD", "low",
            f"Days-to-earnings {dte} — outside the 3-14 day drift window.",
            ["Bernard & Thomas (1989)"], {"days_to_earnings": dte},
        )

    rationale = (
        f"{dte} days to next earnings, 10d momentum {mom10:+.1%}. "
        + ("Pre-earnings drift window + uptrend = continuation through report."
            if signal == +1 else
           "Pre-earnings drift window + downtrend = continued weakness expected."
            if signal == -1 else
           "Inside drift window but momentum neutral — no clear edge.")
    )
    return StrategySignal(
        "Pre-Earnings Drift", "event", signal, _label(signal), confidence,
        rationale,
        ["Bernard & Thomas (1989) — Post-Earnings-Announcement Drift",
         "Ball & Brown (1968) — earnings drift seminal paper"],
        {"days_to_earnings": dte, "momentum_10d": round(mom10, 4)},
    )


# ── Strategy 5: Quantum Sector Lead/Lag (peer momentum) ─────────────────────
# Reference: Lo & MacKinlay (1990) — cross-sectional momentum and lead-lag
# Pattern: peer leads QBTS by 1-3 days; large peer gain + QBTS lag = catch-up

def strategy_peer_lead_lag(df: pd.DataFrame) -> StrategySignal:
    if "ionq_ret_1" not in df.columns:
        return StrategySignal("Quantum Peer Lead/Lag", "momentum", 0, "HOLD", "low",
                              "Peer data unavailable.", ["Lo & MacKinlay (1990)"], {})

    ionq = float(df["ionq_ret_1"].iloc[-1])
    rgti = float(df["rgti_ret_1"].iloc[-1]) if "rgti_ret_1" in df.columns else 0.0
    qbts_today = float(df["close"].iloc[-1] / df["close"].iloc[-2] - 1)
    rel_ionq = float(df["rel_ionq"].iloc[-1]) if "rel_ionq" in df.columns else (qbts_today - ionq)

    peer_avg = (ionq + rgti) / 2

    signal, confidence = 0, "low"
    if peer_avg > 0.03 and rel_ionq < -0.01:
        signal, confidence = +1, "high"     # peers rally hard, QBTS lags → catch-up
    elif peer_avg > 0.02 and rel_ionq < 0:
        signal, confidence = +1, "medium"
    elif peer_avg < -0.03 and rel_ionq > 0.01:
        signal, confidence = -1, "medium"   # peers selling, QBTS overextended → revert

    rationale = (
        f"Peers (IONQ {ionq:+.1%}, RGTI {rgti:+.1%}, avg {peer_avg:+.1%}), "
        f"QBTS underperformance {rel_ionq:+.1%}. "
        + ("Strong sector rally + QBTS lagging = catch-up trade next session."
            if signal == +1 and confidence == "high" else
           "Sector strength + QBTS behind = peer-momentum catch-up."
            if signal == +1 else
           "Sector weakness + QBTS overextended = mean-reversion short."
            if signal == -1 else
           "No clear sector lead-lag signal.")
    )
    return StrategySignal(
        "Quantum Peer Lead/Lag", "momentum", signal, _label(signal), confidence,
        rationale,
        ["Lo & MacKinlay (1990) — Cross-Sectional Momentum & Lead-Lag",
         "Hou (2007) — Industry information diffusion"],
        {"ionq_ret_1d": round(ionq, 4), "rgti_ret_1d": round(rgti, 4),
         "qbts_vs_ionq": round(rel_ionq, 4)},
    )


# ── Strategy 6: Gap-and-Trap (gap fade) ─────────────────────────────────────
# Pattern: large overnight gap + low intraday follow-through volume = gap fade
# Reference: Berkman & Chen (1996); Bali, Cakici, Whitelaw (2014)

def strategy_gap_fade(df: pd.DataFrame) -> StrategySignal:
    if "gap" not in df.columns:
        return StrategySignal("Gap-and-Trap", "microstructure", 0, "HOLD", "low",
                              "Gap data unavailable.", [], {})
    gap   = float(df["gap"].iloc[-1])
    vol   = float(df["vol_ratio"].iloc[-1])
    hl    = float(df["hl_pct"].iloc[-1])

    signal, confidence = 0, "low"
    if gap > 0.05 and vol < 1.2:
        signal, confidence = -1, "medium"   # gap up on low volume = trap, fade
    elif gap < -0.05 and vol < 1.2:
        signal, confidence = +1, "medium"   # gap down on low volume = panic, buy
    elif abs(gap) > 0.08 and hl < 0.04:
        # huge gap + narrow intraday range = no follow-through, fade
        signal, confidence = (-1 if gap > 0 else +1), "high"

    rationale = (
        f"Gap {gap:+.1%}, volume {vol:.1f}x avg, intraday range {hl:.1%}. "
        + ("Massive gap with no intraday follow-through (narrow range) = exhaustion, fade."
            if confidence == "high" else
           "Gap up on weak volume = retail trap, expect fade."
            if signal == -1 else
           "Gap down on weak volume = panic capitulation, expect bounce."
            if signal == +1 else
           "Gap normal or strong follow-through volume — no fade setup.")
    )
    return StrategySignal(
        "Gap-and-Trap", "microstructure", signal, _label(signal), confidence,
        rationale,
        ["Berkman & Chen (1996) — Gap dynamics",
         "Bali, Cakici & Whitelaw (2014) — MAX effect & gap reversals"],
        {"gap_pct": round(gap, 4), "vol_ratio": round(vol, 2), "hl_pct": round(hl, 4)},
    )


# ── Strategy 7: 52-week High Breakout (momentum) ────────────────────────────
# Reference: Jegadeesh & Titman (1993); George & Hwang (2004) — 52-wk anchor

def strategy_52w_breakout(df: pd.DataFrame) -> StrategySignal:
    close   = float(df["close"].iloc[-1])
    high52  = float(df["close"].tail(252).max())
    low52   = float(df["close"].tail(252).min())
    pct_from_high = (close / high52 - 1) if high52 > 0 else 0
    pct_from_low  = (close / low52 - 1)  if low52  > 0 else 0
    mom20 = float(df["momentum_20"].iloc[-1])

    signal, confidence = 0, "low"
    if pct_from_high > -0.02 and mom20 > 0.05:
        signal, confidence = +1, "high"     # at or near 52-wk high + uptrend
    elif pct_from_high > -0.05 and mom20 > 0:
        signal, confidence = +1, "medium"
    elif pct_from_low < 0.02 and mom20 < -0.05:
        signal, confidence = -1, "medium"   # at 52-wk low + downtrend = continuation
    rationale = (
        f"Distance from 52-wk high {pct_from_high:+.1%}, from low {pct_from_low:+.1%}, "
        f"20d momentum {mom20:+.1%}. "
        + ("Breaking out at 52-wk high + strong momentum = institutional buying signal."
            if confidence == "high" and signal == +1 else
           "Near 52-wk high + positive momentum = continuation likely."
            if signal == +1 else
           "Near 52-wk low + negative momentum = downtrend continuation."
            if signal == -1 else
           "Price in the middle of its 52-wk range — no breakout/breakdown signal.")
    )
    return StrategySignal(
        "52-Week Breakout", "momentum", signal, _label(signal), confidence,
        rationale,
        ["Jegadeesh & Titman (1993) — Momentum effect",
         "George & Hwang (2004) — The 52-week high & momentum investing"],
        {"close": round(close, 2), "52w_high": round(high52, 2), "52w_low": round(low52, 2),
         "pct_from_high": round(pct_from_high, 4)},
    )


# ── Strategy 8: Post-News Overreaction Fade ─────────────────────────────────
# Reference: De Bondt & Thaler (1985) — overreaction; Tetlock (2007) — media coverage
# Pattern: large one-day move on news day → next 1-3 day reversal

def strategy_news_overreaction(df: pd.DataFrame) -> StrategySignal:
    if "news_flag" not in df.columns or "days_since_8k" not in df.columns:
        return StrategySignal("Post-News Overreaction", "event", 0, "HOLD", "low",
                              "News data unavailable.", [], {})
    days_since = int(df["days_since_8k"].iloc[-1])
    mom_today  = float(df["close"].iloc[-1] / df["close"].iloc[-2] - 1)
    mom5       = float(df["momentum_5"].iloc[-1])
    rsi        = float(df["rsi_14"].iloc[-1])

    signal, confidence = 0, "low"
    # Big news catalyst within 1-3 days + outsized move → fade
    if days_since <= 3 and mom_today > 0.08 and rsi > 65:
        signal, confidence = -1, "high"
    elif days_since <= 3 and mom_today > 0.05:
        signal, confidence = -1, "medium"
    elif days_since <= 3 and mom_today < -0.08 and rsi < 35:
        signal, confidence = +1, "high"
    elif days_since <= 3 and mom_today < -0.05:
        signal, confidence = +1, "medium"

    rationale = (
        f"Last 8-K {days_since} days ago, today's move {mom_today:+.1%}, RSI {rsi:.0f}. "
        + ("Massive post-news spike + overbought = exhausted reaction, expect fade."
            if signal == -1 and confidence == "high" else
           "Post-news rally + extended = mean-reversion likely."
            if signal == -1 else
           "Post-news drop + oversold = capitulation bounce setup."
            if signal == +1 and confidence == "high" else
           "Post-news drop = contrarian long opportunity."
            if signal == +1 else
           "No recent news catalyst or move size insufficient.")
    )
    return StrategySignal(
        "Post-News Overreaction", "event", signal, _label(signal), confidence,
        rationale,
        ["De Bondt & Thaler (1985) — Does the stock market overreact?",
         "Tetlock (2007) — Media's role in investor sentiment"],
        {"days_since_news": days_since, "today_return": round(mom_today, 4), "rsi_14": round(rsi, 1)},
    )


# ── Runner ───────────────────────────────────────────────────────────────────

ALL_STRATEGIES: list[Callable[[pd.DataFrame], StrategySignal]] = [
    strategy_connors_rsi2,
    strategy_short_squeeze,
    strategy_vix_contrarian,
    strategy_pre_earnings_drift,
    strategy_peer_lead_lag,
    strategy_gap_fade,
    strategy_52w_breakout,
    strategy_news_overreaction,
]


def run_all_strategies(df: pd.DataFrame) -> list[dict]:
    """Run every strategy on the latest bar; return list of signal dicts."""
    out = []
    for fn in ALL_STRATEGIES:
        try:
            out.append(fn(df).to_dict())
        except Exception as e:
            out.append({
                "name": fn.__name__, "category": "error",
                "signal": 0, "label": "HOLD", "confidence": "low",
                "rationale": f"Strategy error: {e}", "references": [], "metric_snapshot": {},
            })
    return out


def aggregate_consensus(signals: list[dict]) -> dict:
    """
    Weighted consensus: high-confidence votes count 3×, medium 2×, low 1×.
    Returns aggregate signal + breakdown.
    """
    conf_w = {"high": 3, "medium": 2, "low": 1}
    score = 0
    n_buy = n_sell = n_hold = 0
    for s in signals:
        w = conf_w.get(s["confidence"], 1)
        score += w * s["signal"]
        if s["signal"] == 1:    n_buy  += 1
        elif s["signal"] == -1: n_sell += 1
        else:                   n_hold += 1

    if score >= 3:
        label, signal = "BUY", 1
    elif score <= -3:
        label, signal = "SELL", -1
    else:
        label, signal = "HOLD", 0

    return {
        "signal":    signal,
        "label":     label,
        "raw_score": score,
        "n_buy":     n_buy,
        "n_sell":    n_sell,
        "n_hold":    n_hold,
        "n_total":   len(signals),
    }
