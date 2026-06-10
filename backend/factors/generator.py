"""
AI Factor Generator — Phase 2 (Enhanced)
Uses Claude to generate Python factor functions tailored for QBTS time-series.
"""

import os
import re
import textwrap
import traceback
import anthropic
import pandas as pd
import numpy as np
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM_PROMPT = textwrap.dedent("""
You are a senior quantitative researcher at a top-tier hedge fund, specializing in
single-stock alpha generation for hyper-volatile small-cap equities.

⚠️  COST WARNING (read first):
  Total round-trip cost = 0.4% (0.1% commission + 0.1% slippage, per side × 2).
  For HOURLY factors with 100+ trades, this compounds to 40%+ cost drag —
  the factor must have very strong edge (hit_rate ≥ 0.56) just to overcome costs.
  For DAILY factors with 20-50 trades, 8-20% cost drag is manageable.
  Prefer daily-frequency factors unless you see a strong intraday-specific pattern.

TARGET STOCK: QBTS (D-Wave Quantum Inc.)
  - Quantum computing pure-play, ~$15-30 price range
  - Extremely low float → prone to short squeezes and sudden 30-200% spikes
  - News-driven: FDA/DOE/government contracts, quantum computing milestones
  - Retail-heavy: WSB, StockTwits, Twitter drive intraday momentum
  - Mean-reverts violently after news spikes (exhaustion pattern)
  - Quantum sector peers: IONQ, RGTI — highly correlated on sector days

QBTS MARKET DYNAMICS — READ BEFORE DESIGNING ANY FACTOR:
  QBTS has TWO distinct regimes — your factor MUST handle both:

  REGIME A — Choppy/mean-reverting (most of the time):
    ✓ Fade overbought RSI, fade VWAP extensions, fade gap-ups
    ✓ Peer catch-up longs work when QBTS lags sector
    ✓ News fade after 8-K spike

  REGIME B — Strong trend (rare but brutal, e.g. 2024-2025 rally from $2→$47):
    ✗ Pure mean-reversion SHORTS get destroyed (-60% to -90% drawdown)
    ✓ Trend-following or flat positioning is the only safe choice

  CRITICAL RULE FOR MEAN-REVERSION FACTORS:
    Always add a regime guard before signaling short:
      ONLY fade / go short when momentum_20 < 0.10  (broad trend is not strongly up)
      If momentum_20 > 0.10, signal 0 (flat) instead of -1 (short)
    This prevents catastrophic losses during QBTS bull runs.
    Similarly, only fade down / go long when momentum_20 > -0.10.

  WHAT WORKS ACROSS BOTH REGIMES:
    ✓ Peer divergence catch-up (regime-neutral relative value)
    ✓ Volume climax detection (works in both trending and choppy)
    ✓ News-event momentum on filing day (event-driven, regime-independent)
    ✓ Fear + oversold dip-buy with regime filter (long-only, won't short bull)

SIGNAL SEMANTICS (CRITICAL — read carefully):
  This system is a MANUAL SIGNAL GENERATOR. The human trader watches for signals
  and executes manually via leveraged ETFs:
    +1  → BUY signal    → trader enters long via QBTX (2× long ETF) or spot QBTS
    -1  → SELL/SHORT signal → trader enters short via QBTZ (2× inverse ETF)
     0  → FLAT / hold   → trader does nothing or closes existing position

  The backtest engine models QBTS 1× returns directly — no leverage, no borrow cost.
  You MUST generate meaningful -1 short signals, not just +1 longs. A factor that
  only signals +1 and 0 is HALF a factor. Both directions are evaluated equally.

AVAILABLE DataFrame COLUMNS (already computed, use freely):
  Core OHLCV:
    open, high, low, close, volume

  Pre-computed technical features (use these instead of recomputing):
    atr_14        ATR(14) normalized by close — volatility level
    rsi_14        RSI(14) — 0-100, >70 overbought, <30 oversold
    bb_width      Bollinger Band width (20,2σ) — squeeze detection
    bb_pct        %B position within bands — 0=lower band, 1=upper band
    vwap_dev      Deviation from 20-bar VWAP — institutional price level
    vol_ratio     Volume / 20-bar avg volume — demand surge proxy
    vol_ratio_5   Volume / 5-bar avg volume — very short-term surge
    momentum_5    5-bar price return
    momentum_10   10-bar price return
    momentum_20   20-bar price return
    hl_pct        (high-low)/close — intrabar volatility
    gap           open/prev_close - 1 — gap at open

  Peer relative strength (daily df only; zeros in hourly):
    ionq_ret_1    IONQ 1-day return (quantum peer)
    rgti_ret_1    RGTI 1-day return (quantum peer)
    qqq_ret_1     QQQ 1-day return (tech sector)
    vix           VIX level (market fear gauge)
    rel_ionq      QBTS 1d return minus IONQ 1d return
    rel_qqq       QBTS 1d return minus QQQ return

  SEC EDGAR event features:
    days_since_8k calendar days since last 8-K SEC filing (capped at 60); low = recent news catalyst
    news_flag     1 if 8-K filed on this exact day or yesterday (tight window — D-Wave files ~3×/month so this is rare), else 0

  🆕 ALT-DATA features (Phase 3a — exploit these for novel edges):
    etf_long_share   QBTX_vol / (QBTX+QBTZ vol), range [0,1]
                       0.50 = neutral retail positioning
                       0.70+ = aggressive retail BULL leverage → fade target (overcrowded long)
                       0.30- = aggressive retail BEAR leverage → contrarian long (oversold panic)
                       This is a DIRECT read on leveraged-ETF flow.

    etf_flow_z       z-score of combined (QBTX+QBTZ) volume vs 20d mean
                       > 2.0 = unusual retail attention (signal-worthy regime)
                       Use as a CONDITION rather than a primary trigger.

    days_to_earnings signed days to next earnings; +14 = 2 weeks away; -3 = 3 days post
                       Pre-earnings (5-15 days out): vol expansion, drift continuation
                       Post-earnings (1-3 days after): post-earnings-drift in direction of surprise

    earnings_window  1 if within ±3 days of an earnings date (binary event flag)

    short_ratio      FINRA daily short volume / total volume; range [0,1]
                       > 0.50 = very heavy short pressure (squeeze fuel if price rises)
                       < 0.30 = light short pressure (no squeeze potential)

    short_ratio_5d   5-day smoothed short_ratio — regime indicator (less noisy)

    short_pressure_z z-score of short_ratio vs 60d mean
                       > 1.5 = abnormal short buildup → SQUEEZE SETUP if price strengthens
                       < -1.5 = abnormal short covering → momentum exhaustion risk

FACTOR ARCHETYPES — rotate between these, pick the ONE most promising idea:
  A. SQUEEZE SETUP      — bb_width near multi-period low + vol_ratio rising + rsi_14 neutralizing
  B. EXHAUSTION/REVERSAL — rsi_14 > 75 + vol_ratio > 2.5 + momentum_5 > 0.15 → mean-revert short
  C. VWAP RECLAIM       — close crossed above vwap_dev from below + vol_ratio > 1.3
  D. GAP FADE           — large gap up (gap > 0.05) with shrinking hl_pct → fade the gap
  E. QUANTUM SECTOR LEAD — rel_ionq > 0 AND rel_qqq > 0 → QBTS outperforming sector
  F. VOLATILITY REGIME   — atr_14 regime change: low→high vol breakout setup
  G. VOLUME CLIMAX       — vol_ratio_5 > 3 + hl_pct spike → capitulation / reversal
  H. PEER DIVERGENCE     — QBTS lags while IONQ+RGTI rally → catch-up long
  I. VIX FEAR SPIKE      — vix > 25 + qbts oversold (rsi_14 < 35) → fear-driven dip buy
  J. MOMENTUM CONTINUATION — momentum_5 > 0 + momentum_20 > 0 + vol_ratio > 1 + bb_pct > 0.5

EVALUATION TARGETS — your factor is judged by these (in order of importance):
  1. HIT RATE on active bars:
       Of the bars where your factor signals ±1, what fraction had a forward
       return in the predicted direction?
       Random = 0.50.  Pass gate = 0.52.  Goal = 0.55+.
       This is the PRIMARY alpha measure. A factor with hit_rate=0.55 over
       50 signals is far more valuable than one with IC=0.10 over 5 signals.

  2. SIGNAL COUNT (n_signals): CRITICAL HARD GATE — read carefully:
       Your factor MUST produce ≥ 20 active bars in the OOS evaluation window.
       In the IS window (~250 daily bars), the system requires ≥ 15 active bars
       at generation time — TOO-SPARSE factors are auto-rejected.

       Concrete density targets for IS window (~250 daily bars):
         ✗ <15 active bars  → AUTO-REJECT (you'll be asked to regenerate)
         ✓  30-80 active bars → IDEAL (one signal every 3-8 bars)
         ✗ >150 active bars → too dense, will be filtered as whipsaw

       Why factors fail this gate: stacking too many AND conditions, or
       using extreme thresholds (rsi>75, momentum>0.15, vol_ratio>3).

       Density recipe: pick ONE primary trigger condition, add ONE filter,
       and ONE regime guard. THREE conditions is the upper limit.

  3. RISK-ADJUSTED SHARPE (post stop-loss + vol-target):
       The system applies 5% per-trade stop-loss and vol-target sizing automatically.
       Your factor's reported Sharpe is AFTER these are applied. Sharpe > 1 is good.

  4. STOP RATIO (n_stops / n_trades):
       If stop-loss fires on > 40% of trades, the factor is whipsaw-noise.
       Strong factors trigger few stops because their directional calls are right.

DESIGN PRINCIPLES (follow these to maximise hit_rate AND density):
  ✓ TWO conditions joined by AND  (one signal source + one regime guard)
  ✓ Use rolling baselines (e.g. rsi_14 > rsi_14.rolling(20).mean()) over fixed cutoffs
  ✓ Use OR to combine alternative triggers (e.g. rsi>65 OR bb_pct>0.85)
  ✓ A factor firing 50 times at 55% hit rate >> firing 5 times at 80% hit rate
  ✗ AVOID: 4+ chained AND conditions — each AND halves the trigger rate

EXAMPLE of CORRECT density:
  # Two conditions + one regime guard = ~40 signals over 250 bars ✓
  short_trigger = (rsi_14 > 65) & (vwap_dev > 0.02)
  long_trigger  = (rsi_14 < 35) & (vwap_dev < -0.02)
  sig = np.where(short_trigger & (momentum_20 < 0.12), -1,
        np.where(long_trigger  & (momentum_20 > -0.12), 1, 0))

RULES (violation = output rejected):
  1. Output ONLY executable Python — no markdown, no comments, no explanations.
  2. Function signature must be exactly:
         def compute_factor(df: pd.DataFrame) -> pd.Series:
     where df has DatetimeIndex and ALL the columns listed above.
  3. The returned pd.Series must:
       - Same index as df
       - Values ONLY in {-1, 0, 1} as integers
       - No NaN values (fill with 0)
  4. Use ONLY: numpy as np, pandas as pd. No other imports.
  5. Keep function body under 50 lines. One clean idea beats a messy combination.
  6. Predict direction 1 period ahead. No look-ahead (use only past data, use .shift() correctly).
     BOTH long (+1) AND short (-1) signals are required. A factor with no -1 values FAILS review.
  7. Start with a docstring: first line = factor name (≤60 chars), second line = one-sentence logic.
  8. Do NOT recompute ATR/RSI/VWAP yourself — use the pre-computed columns.
  9. For peer columns: always guard with `.fillna(0)` in case daily columns are zero in hourly data.
""").strip()


# ── Factor idea pool — rotated to encourage diversity ────────────────────────

_IDEA_POOL = [
    "Design a SQUEEZE SETUP factor: detect when Bollinger Band width (bb_width) hits a multi-period low while volume ratio (vol_ratio) starts rising, signaling an impending breakout long.",
    "Design an EXHAUSTION REVERSAL factor: after a sharp spike (momentum_5 > 12%, rsi_14 > 72, vol_ratio > 2), predict mean-reversion short. QBTS spikes and dumps violently.",
    "Design a VWAP FADE factor: when vwap_dev > 0.02 (price extended >2% above VWAP) AND rsi_14 > 60, predict mean-reversion SHORT back to VWAP. When vwap_dev < -0.02 AND rsi_14 < 45, predict mean-reversion LONG. QBTS always reverts to VWAP.",
    "Design a GAP FADE factor: when QBTS gaps up more than 4% at open (gap > 0.04) but intraday range (hl_pct) starts narrowing, fade the gap with a short signal.",
    "Design a QUANTUM SECTOR LEAD factor: go long when QBTS outperforms both IONQ (rel_ionq > 0) and QQQ (rel_qqq > 0) simultaneously, indicating sector-specific alpha.",
    "Design a VOLUME CLIMAX REVERSAL factor: vol_ratio_5 > 3 (volume surge) + hl_pct spike + rsi_14 > 65 → predict reversal. Climax volume often marks short-term tops in QBTS.",
    "Design a PEER DIVERGENCE CATCH-UP factor: when IONQ (ionq_ret_1 > 2%) and RGTI (rgti_ret_1 > 2%) both rally but QBTS lags (momentum_5 < 0), predict QBTS catch-up long.",
    "Design a VIX FEAR DIP-BUY factor: when VIX spikes above 25 AND QBTS is oversold (rsi_14 < 35) AND momentum_20 is negative, signal a contrarian long for mean-reversion.",
    "Design a BOLLINGER BAND WALK factor: when bb_pct > 0.85 AND vol_ratio > 1.5 AND momentum_5 > 0, the stock is 'walking the upper band' — continuation long signal.",
    "Design a LOW-VOLATILITY BREAKOUT factor: when atr_14 drops below its 20-period median (low-vol regime) AND bb_width hits a 10-period low, anticipate a volatility expansion long.",
    "Design a INTRADAY RANGE EXPANSION factor: hl_pct expanding from a narrow base (hl_pct > 2x its 10-period median) + above-average volume = volatility regime shift, signal long if close in upper half.",
    "Design a MOMENTUM DIVERGENCE factor: momentum_5 positive but momentum_20 still negative (short-term recovery in downtrend) + rsi_14 crossing 40 from below = early trend reversal long.",
    "Design a NEWS CATALYST factor: use days_since_8k and news_flag — when news_flag=1 (8-K filed within 3 days) AND vol_ratio > 1.5 AND rsi_14 < 65, predict momentum continuation long (institutional accumulation after filings).",
    "Design a POST-NEWS FADE factor: when days_since_8k <= 5 AND momentum_5 > 0.08 AND rsi_14 > 68, the news-driven spike is exhausted — predict short-term reversal. QBTS overreacts to 8-K filings.",

    # ── High-frequency archetypes (target 15-25 signals/year) ──────────────────
    "Design a RSI EXTREME REVERSION factor with regime guard: short when rsi_14 > 68 AND momentum_20 < 0.10 (not in a bull run), long when rsi_14 < 32 AND momentum_20 > -0.10. The regime guard (momentum_20 threshold) is MANDATORY to avoid shorting QBTS during uptrends. Should fire 12-20 times per year.",
    "Design a MOMENTUM EXHAUSTION FADE factor with regime guard: fade large 5-day moves — short if momentum_5 > 0.08 AND momentum_20 < 0.15, long if momentum_5 < -0.08 AND momentum_20 > -0.15. The momentum_20 guard prevents shorting into a strong uptrend. Fires 15-25 times per year.",
    "Design a VWAP EXTENSION FADE factor with regime guard: short when vwap_dev > 0.03 AND momentum_20 < 0.10 (trending up? stay flat or long instead). Long when vwap_dev < -0.03. Without the regime guard, this factor loses 80%+ during QBTS bull runs.",
    "Design a VOLUME CLIMAX REVERSAL factor with regime guard: vol_ratio_5 > 2.5 AND hl_pct > 0.05 = climax bar. After a climax, short if close in upper half of range AND momentum_20 < 0.12; long if close in lower half. Volume climax = exhaustion signal in either direction.",
    "Design a COMPOSITE REVERSAL SCORE factor with regime guard: score = -sign(momentum_5) + (1 if rsi_14>65 else -1 if rsi_14<35 else 0). Short when score <= -1 AND momentum_20 < 0.10. Long when score >= 1 AND momentum_20 > -0.10. The momentum_20 guard is critical — skip shorting during uptrends.",
    "Design a ATR OVEREXTENSION FADE factor with regime guard: z = (close - close.rolling(10).mean()) / (atr_14 * close + 1e-9). Short when z > 1.5 AND momentum_20 < 0.12. Long when z < -1.5 AND momentum_20 > -0.12. Fade deviations only when not in a strong trend.",

    # ── 🆕 Phase-3a alt-data archetypes (novel edge sources) ──────────────────
    "Design a RETAIL FOMO FADE factor using ETF flow: when etf_long_share > 0.70 (aggressive retail long leverage) AND rsi_14 > 60, predict SHORT — retail is over-positioned, crowded longs unwind. When etf_long_share < 0.30 AND rsi_14 < 40, predict LONG (retail panic = capitulation low). Pure leveraged-ETF flow contrarian.",

    "Design a SHORT SQUEEZE SETUP factor: when short_pressure_z > 1.5 (abnormal short buildup) AND close > close.shift(5) (price rising despite shorts), predict LONG — squeeze fuel + price strength = forced covering. Short when short_pressure_z < -1.5 (covering pressure exhausted) AND rsi_14 > 65 (momentum exhaustion). Use FINRA short_ratio for confirmation: signal stronger when short_ratio > 0.45.",

    "Design a PRE-EARNINGS DRIFT factor: when days_to_earnings between 3 and 14 (pre-earnings window), follow the recent trend — long if momentum_10 > 0.05, short if momentum_10 < -0.05. Earnings drift in the direction of the prior move is a well-documented anomaly. Use earnings_window=0 to avoid the actual event volatility.",

    "Design a POST-EARNINGS REVERSAL factor: when days_to_earnings between -5 and -1 (recent earnings) AND |momentum_5| > 0.10 (big earnings move), FADE the move — short if momentum_5 > 0.10, long if momentum_5 < -0.10. Earnings overreactions are 60% mean-reverting in small-cap stocks.",

    "Design an ETF-FLOW DIVERGENCE factor: when etf_flow_z > 2.0 (unusual retail attention) AND etf_long_share diverges from QBTS price direction — i.e., price rising but etf_long_share falling (smart-money selling into retail strength) → SHORT. Or price falling but etf_long_share rising (retail buying the dip into weakness) → also SHORT (knife-catcher signal).",

    "Design a SHORT-RATIO MEAN REVERSION factor: when short_ratio > 0.55 (extreme bearish positioning, top 5% of historical) AND price hasn't broken down (close > close.rolling(20).mean()), predict LONG — bears are wrong, expect short-cover rally. Add regime guard: only signal when momentum_20 > -0.10 (not in active downtrend).",
]

import random as _random
_shuffled_pool: list[str] = []
_shuffle_pos: int = 0


def _next_idea() -> str:
    global _shuffled_pool, _shuffle_pos
    if _shuffle_pos >= len(_shuffled_pool):
        _shuffled_pool = _IDEA_POOL.copy()
        _random.shuffle(_shuffled_pool)
        _shuffle_pos = 0
    idea = _shuffled_pool[_shuffle_pos]
    _shuffle_pos += 1
    return idea


# ── Core generation ──────────────────────────────────────────────────────────

def generate_factor(idea: str | None = None, sentiment_context: str | None = None) -> dict:
    """
    Ask Claude to write a QBTS factor function.
    If no idea is given, cycles through the curated idea pool.
    """
    base_msg = idea if idea else _next_idea()
    user_msg = base_msg + (sentiment_context or "")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw_code = response.content[0].text.strip()

    # Strip accidental markdown fences
    raw_code = re.sub(r"^```(?:python)?\n?", "", raw_code)
    raw_code = re.sub(r"\n?```$", "", raw_code)

    # Extract name and description from docstring
    name_match = re.search(r'"""(.*?)"""', raw_code, re.DOTALL)
    if name_match:
        lines = [l.strip() for l in name_match.group(1).strip().split("\n") if l.strip()]
        name        = lines[0][:60] if lines else f"factor_{response.id[-6:]}"
        description = lines[1] if len(lines) > 1 else "AI-generated QBTS factor"
    else:
        name        = f"factor_{response.id[-6:]}"
        description = "AI-generated QBTS factor"

    return {"name": name, "description": description, "code": raw_code}


_MIN_ACTIVE_SIGNALS = 15   # minimum active bars across the IS slice (lower than the 20 OOS gate)


def validate_factor(factor_dict: dict, df: pd.DataFrame) -> tuple[bool, str, pd.Series | None]:
    """Compile and run the generated factor code against real enriched data."""
    code = factor_dict["code"]
    namespace: dict = {"pd": pd, "np": np}

    try:
        exec(compile(code, "<factor>", "exec"), namespace)
    except SyntaxError as e:
        return False, f"SyntaxError: {e}", None

    if "compute_factor" not in namespace:
        return False, "compute_factor() not found", None

    try:
        signal = namespace["compute_factor"](df.copy())
    except Exception:
        return False, f"Runtime error:\n{traceback.format_exc()}", None

    if not isinstance(signal, pd.Series):
        return False, f"Expected pd.Series, got {type(signal)}", None

    if not signal.index.equals(df.index):
        return False, "Signal index mismatch", None

    invalid_vals = set(signal.unique()) - {-1, 0, 1}
    if invalid_vals:
        return False, f"Invalid signal values: {invalid_vals}", None

    if signal.isna().any():
        return False, "Signal contains NaN", None

    # Density check — factor must fire on at least _MIN_ACTIVE_SIGNALS bars in IS
    n_active = int((signal != 0).sum())
    if n_active < _MIN_ACTIVE_SIGNALS:
        density_pct = n_active / max(len(signal), 1) * 100
        return False, (
            f"Signal too sparse — only {n_active} active bars across {len(signal)} IS bars "
            f"({density_pct:.1f}% density). System requires ≥{_MIN_ACTIVE_SIGNALS} active bars. "
            f"LOOSEN your conditions: use OR instead of AND, reduce the number of "
            f"simultaneous requirements, or relax thresholds (e.g. rsi>65 instead of rsi>72)."
        ), None

    # Both-sides check — must produce both long (+1) AND short (-1) signals
    has_long  = (signal == 1).any()
    has_short = (signal == -1).any()
    if not (has_long and has_short):
        missing = "long (+1)" if not has_long else "short (-1)"
        return False, (
            f"Signal is one-directional — missing {missing} bars. "
            f"A complete factor must produce BOTH +1 and -1 signals."
        ), None

    return True, "OK", signal


# Errors that mean Claude is fundamentally confused — retrying rarely fixes them.
# Saves 1-2 wasted Claude calls per failed round.
_UNRECOVERABLE_PATTERNS = (
    "SyntaxError",
    "compute_factor() not found",
    "engineer_features must define",
    "Expected pd.Series, got",
    "Signal index mismatch",
)


def _is_unrecoverable(msg: str) -> bool:
    return any(p in msg for p in _UNRECOVERABLE_PATTERNS)


def generate_and_validate(
    df: pd.DataFrame,
    idea: str | None = None,
    max_retries: int = 2,
    sentiment_context: str | None = None,
) -> dict:
    """Generate and validate; retry only on recoverable errors."""
    failures: list[str] = []
    for attempt in range(1, max_retries + 1):
        print(f"  [attempt {attempt}/{max_retries}] Generating factor…")
        factor = generate_factor(idea, sentiment_context=sentiment_context)
        ok, msg, signal = validate_factor(factor, df)
        if ok:
            factor["signal"] = signal
            factor["_n_attempts"] = attempt   # for cost telemetry
            print(f"  ✓ Factor valid: {factor['name']}")
            return factor

        failures.append(msg[:120])
        print(f"  ✗ Validation failed: {msg[:140]}")

        if _is_unrecoverable(msg):
            print("  ⚠ Unrecoverable error — skipping remaining retries to save tokens.")
            break

        if attempt < max_retries:
            idea = (idea or "") + f"\n\nPrevious attempt failed: {msg}. Fix this."

    detail = " | ".join(failures)
    raise RuntimeError(f"生成失败 ({len(failures)} 次尝试): {detail}")


# ─────────────────────────────────────────────────────────────────────────────
# ML MODE — Phase 3b
# Claude writes engineer_features(df) → DataFrame of new features.
# System trains LightGBM on (base + engineered) → forward direction.
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT_ML = textwrap.dedent("""
You are a senior quantitative researcher specialising in FEATURE ENGINEERING
for tree-based ML models on hyper-volatile small-cap equities.

YOUR JOB IS DIFFERENT FROM TRADITIONAL FACTOR DESIGN:
  You are NOT writing a rule-based buy/sell signal.
  You are writing engineer_features(df) -> pd.DataFrame that adds 5-15 NEW
  derived features. The system will train a LightGBM classifier on these
  features (combined with the 27 base features) to predict direction.

  Your edge: design features the model can EXPLOIT. The model will discover
  the interactions automatically. Your job is to PROVIDE GOOD RAW MATERIAL.

TARGET: QBTS (D-Wave Quantum Inc.) — low float, retail-driven, mean-reverting
  with occasional explosive trends. 32 base features available (see list below).

WHAT MAKES A GOOD FEATURE:
  1. Z-SCORES — normalize a raw value against its own rolling history
     e.g. rsi_z = (rsi_14 - rsi_14.rolling(60).mean()) / rsi_14.rolling(60).std()
     Tells the model whether *today's* RSI is unusually high *for QBTS specifically*.

  2. RATIOS — divide one quantity by another for scale-invariance
     e.g. vol_acceleration = vol_ratio / vol_ratio.rolling(5).mean()
          vwap_atr_norm   = vwap_dev / atr_14   (price extension in vol units)

  3. INTERACTIONS — multiply or subtract features to capture combined regimes
     e.g. squeeze_loaded = bb_pct * vol_ratio  (high band-pct AND high volume)
          momentum_div   = momentum_5 - momentum_20  (acceleration)

  4. LAGS — past values capture recent dynamics
     e.g. rsi_lag3 = rsi_14.shift(3)        (RSI 3 bars ago)
          close_3d_ago = df["close"].shift(3)

  5. ROLLING STATISTICS — moments over windows
     e.g. mom5_std = df["close"].pct_change().rolling(10).std()
          high_low_range = (df["high"].rolling(5).max() - df["low"].rolling(5).min()) / df["close"]

  6. ALT-DATA TRANSFORMS — combine the Phase-3a features in novel ways
     e.g. retail_vs_smart = etf_long_share - 0.5
          short_squeeze_potential = short_pressure_z * (close > close.shift(5))
          earnings_proximity_inv = 1 / (1 + days_to_earnings.abs())

  7. KALMAN STATE FEATURES — the kf_* columns are already denoised state estimates;
     combine them for regime/reversion signals (cleaner than raw momentum/SMA)
     e.g. trend_strength = kf_velocity * (1 - kf_residual.abs())   # strong + not overextended
          reversion_setup = kf_residual * (kf_spread_z.abs() > 1.5)  # KF says rich/cheap + pairs confirms
          pairs_dislocation = kf_spread_z * np.sign(kf_beta)

AVAILABLE BASE COLUMNS (you have these in df, do NOT recompute):
  OHLCV: open, high, low, close, volume
  Technical: atr_14, rsi_14, bb_width, bb_pct, vwap_dev, vol_ratio, vol_ratio_5,
             momentum_5, momentum_10, momentum_20, hl_pct, gap
  Peers: ionq_ret_1, rgti_ret_1, qqq_ret_1, vix, rel_ionq, rel_qqq
  News: days_since_8k, news_flag
  Alt-data: etf_long_share, etf_flow_z, days_to_earnings, earnings_window,
            short_ratio, short_ratio_5d, short_pressure_z
  Kalman:   kf_velocity (denoised momentum), kf_residual (price vs KF fair-value),
            kf_beta (dynamic QBTS~IONQ hedge ratio), kf_spread_z (pairs spread z-score)

RULES (violation = output rejected):
  1. Output ONLY executable Python — no markdown, no comments, no explanations.
  2. Function signature must be exactly:
         def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
  3. Returned DataFrame must:
       - Have the same index as df
       - Contain 5-15 new feature columns (NOT the base ones — the system adds those)
       - All values numeric (no strings, no bool)
       - Use .fillna() or appropriate handling — no infinite values
  4. Use ONLY numpy as np, pandas as pd. No other imports.
  5. Keep function body under 30 lines.
  6. NO LOOK-AHEAD: never use future data. df.rolling(N).mean() is fine;
     df.rolling(N).mean().shift(-1) is NOT.
  7. Start with a docstring: first line = strategy name (≤60 chars),
     second line = one-sentence summary of feature theme.

EXAMPLE (good ML feature set — momentum exhaustion + squeeze + retail flow):

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    \"\"\"Momentum Exhaustion + Squeeze + Retail Flow features
    Captures over-extension, volatility regime, and retail crowding.\"\"\"
    out = pd.DataFrame(index=df.index)
    out["rsi_z60"]        = (df["rsi_14"] - df["rsi_14"].rolling(60).mean()) / df["rsi_14"].rolling(60).std()
    out["vol_accel"]      = df["vol_ratio"] / df["vol_ratio"].rolling(10).mean()
    out["vwap_atr_norm"]  = df["vwap_dev"] / df["atr_14"]
    out["mom_div"]        = df["momentum_5"] - df["momentum_20"]
    out["squeeze_load"]   = df["bb_pct"] * df["vol_ratio"]
    out["bb_atr_ratio"]   = df["bb_width"] / df["atr_14"]
    out["retail_lean"]    = df["etf_long_share"] - 0.5
    out["short_x_mom"]    = df["short_pressure_z"] * np.sign(df["momentum_5"])
    out["earn_proximity"] = 1.0 / (1 + df["days_to_earnings"].abs())
    out["peer_lag"]       = df["rel_ionq"].rolling(3).mean()
    return out.fillna(0).replace([np.inf, -np.inf], 0)
""").strip()


_IDEA_POOL_ML = [
    "Design a MOMENTUM-EXHAUSTION feature set: z-scores of RSI, momentum divergence (m5 vs m20), squeeze indicators (bb_pct × vol_ratio), and ATR-normalised VWAP deviation. Goal: let the model identify when QBTS is over-extended in either direction.",

    "Design a RETAIL-CROWDING feature set: etf_long_share transforms, short_pressure_z interactions with price direction, vol_ratio comparisons across timeframes. Goal: feed the model leveraged-ETF flow signals so it can detect crowded positions.",

    "Design a NEWS-EVENT feature set: interactions of days_since_8k with momentum, earnings_proximity weighting of volatility, post-news drift indicators (vol_ratio × news_flag), pre-earnings vol ramp (atr × earnings_proximity). Goal: capture catalyst dynamics.",

    "Design a PEER-RELATIVE feature set: rel_ionq smoothed over windows, lead-lag features (peer_ret_1 lagged by 1-3 bars), peer momentum spread (ionq_ret_1 - qbts equivalent), VIX-conditional peer beta. Goal: exploit quantum sector mispricings.",

    "Design a VOLATILITY-REGIME feature set: atr_14 percentile rank, bb_width regime indicators, hl_pct rolling stats (mean, std, max over 20 bars), regime-shift detectors (atr now vs atr 20 bars ago). Goal: let the model learn distinct behaviours in low-vol vs high-vol regimes.",

    "Design a MICROSTRUCTURE feature set: gap × vol_ratio interactions, intraday range vs ATR, volume-weighted momentum (momentum × vol_ratio), close position within day's range. Goal: capture order-flow imbalances and intraday dynamics.",

    "Design a MULTI-TIMEFRAME MOMENTUM feature set: composite momentum scores at 3/5/10/20 bars, momentum acceleration (m5 - m10), persistence indicators (signs aligned across timeframes), and momentum z-scores. Goal: feed the model a rich representation of trend strength at different horizons.",

    "Design a MEAN-REVERSION feature set: distance from rolling means (close - close.rolling(N).mean() in ATR units), z-scores of vwap_dev, oscillator levels (RSI distance from 50), and reversion velocity (rate-of-change of vwap_dev). Goal: highlight stretched-from-fair-value setups.",
]


def _is_feature_code_valid(code: str, df: pd.DataFrame):
    """Heavy validation used by validate_ml_factor."""
    from factors.ml_factor import validate_feature_code   # local import to avoid cycle
    return validate_feature_code(code, df)


def generate_ml_factor(idea: str | None = None, sentiment_context: str | None = None) -> dict:
    """Ask Claude to write engineer_features() for ML factor mode."""
    base_msg = idea if idea else _random.choice(_IDEA_POOL_ML)
    user_msg = base_msg + (sentiment_context or "")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT_ML,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw_code = response.content[0].text.strip()
    raw_code = re.sub(r"^```(?:python)?\n?", "", raw_code)
    raw_code = re.sub(r"\n?```$", "", raw_code)

    name_match = re.search(r'"""(.*?)"""', raw_code, re.DOTALL)
    if name_match:
        lines = [l.strip() for l in name_match.group(1).strip().split("\n") if l.strip()]
        name        = lines[0][:60] if lines else f"ml_factor_{response.id[-6:]}"
        description = lines[1] if len(lines) > 1 else "AI-generated ML feature set"
    else:
        name        = f"ml_factor_{response.id[-6:]}"
        description = "AI-generated ML feature set"

    return {"name": name, "description": description, "code": raw_code}


def validate_ml_factor(factor_dict: dict, df: pd.DataFrame) -> tuple[bool, str]:
    """Compile engineer_features and verify it produces a usable feature matrix."""
    ok, msg, n = _is_feature_code_valid(factor_dict["code"], df)
    return ok, f"{msg} (engineered={n})"


def generate_and_validate_ml(
    df: pd.DataFrame,
    idea: str | None = None,
    max_retries: int = 2,
    sentiment_context: str | None = None,
) -> dict:
    """Generate ML feature code; retry only on recoverable errors."""
    failures: list[str] = []
    for attempt in range(1, max_retries + 1):
        print(f"  [ML attempt {attempt}/{max_retries}] generating features…")
        factor = generate_ml_factor(idea, sentiment_context=sentiment_context)
        ok, msg = validate_ml_factor(factor, df)
        if ok:
            factor["_n_attempts"] = attempt   # for cost telemetry
            print(f"  ✓ ML features valid: {factor['name']} — {msg}")
            return factor

        failures.append(msg[:120])
        print(f"  ✗ ML validation failed: {msg[:140]}")

        if _is_unrecoverable(msg):
            print("  ⚠ Unrecoverable error — skipping remaining retries to save tokens.")
            break

        if attempt < max_retries:
            idea = (idea or "") + f"\n\nPrevious attempt failed: {msg}. Fix this."

    detail = " | ".join(failures)
    raise RuntimeError(f"ML 生成失败 ({len(failures)} 次尝试): {detail}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
    from data.fetcher import load_or_fetch
    from data.enricher import enrich

    _, df_daily = load_or_fetch()
    df_daily = enrich(df_daily, freq="1d")
    print(f"Loaded {len(df_daily)} daily rows, columns: {list(df_daily.columns)}\n")

    factor = generate_and_validate(df_daily)
    print("\n--- Generated Factor Code ---")
    print(factor["code"])
    print("\n--- Signal Distribution ---")
    print(factor["signal"].value_counts().sort_index())
