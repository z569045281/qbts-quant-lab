"""
ML Factor Engine — Phase 3b.

Replaces the if-then `compute_factor` paradigm with a feature-engineering +
LightGBM training pipeline. The fundamental shift:

  OLD (rule-based):
    Claude writes a single boolean expression that maps (32 features) → {-1, 0, +1}.
    Expressiveness ≈ a few dozen decision points.
    Hit-rate ceiling on QBTS daily: ~52% (basically random).

  NEW (ML-based):
    Claude writes engineer_features(df) → adds 5-15 derived features.
    System trains a LightGBM classifier per WFO IS window on (base + engineered)
    features predicting forward-N-bar direction. Predictions become signals when
    confidence exceeds a threshold; flat otherwise.

    Expressiveness: thousands of nonlinear interaction trees with proper
    threshold tuning. Hit-rate ceiling: higher (the model finds patterns the
    human can't articulate).

Label design (5-bar ATR-normalised forward return):
    z = forward_5d_return / (atr_14 * sqrt(5))
    label = 1 if z > +0.5  (meaningful up move)
          = 0 if z < -0.5  (meaningful down move)
          = NaN otherwise (noise — excluded from training)

Signal mapping (at OOS):
    prob_up = model.predict(features)  # probability of "up" in [0,1]
    signal  = +1 if prob_up > 0.55
            = -1 if prob_up < 0.45
            =  0 otherwise (low-confidence → flat)

This sparse-signal behaviour aligns with the hit-rate gate: high-confidence
predictions are scarce but should have stronger directional accuracy.
"""

from __future__ import annotations

import warnings
from typing import Callable

import numpy as np
import pandas as pd
import lightgbm as lgb

from backtest.engine    import BacktestResult, walk_forward_splits, bars_per_month, _build_result, _strategy_returns, PERIODS_PER_YEAR
from backtest.risk      import apply_risk_management


# ── Default hyperparameters ───────────────────────────────────────────────────
_LABEL_HORIZON         = 5            # predict 5 bars ahead (~ 1 trading week)
_LABEL_Z_THRESHOLD     = 0.5          # |z-score| threshold for "meaningful" move
_SIGNAL_UP_THRESHOLD   = 0.62         # prob > 0.62 → long (confident enough to overcome 50/50 prior)
_SIGNAL_DOWN_THRESHOLD = 0.38         # prob < 0.38 → short
_SIGNAL_TOP_QUANTILE   = 0.85         # only signal if prob is in top 15% of this window
_SIGNAL_BOT_QUANTILE   = 0.15         # only signal if prob is in bottom 15%
_MIN_TRAIN_SAMPLES     = 40           # need ≥ 40 labelled bars to train

# Columns that should NEVER be used as features (look-ahead, target leakage, etc.)
_BLACKLIST = {"open", "high", "low", "close", "volume"}

_LGB_PARAMS = {
    "objective":        "binary",
    "metric":           "binary_logloss",
    "boosting_type":    "gbdt",
    "num_leaves":       15,
    "min_data_in_leaf": 8,
    "learning_rate":    0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq":     3,
    "is_unbalance":     True,        # handle class imbalance (QBTS bull-run dominates)
    "verbose":          -1,
    "force_row_wise":   True,
}
_LGB_BOOST_ROUNDS = 100


# ── Label construction ───────────────────────────────────────────────────────

def create_label(df: pd.DataFrame, horizon: int = _LABEL_HORIZON, z_thresh: float = _LABEL_Z_THRESHOLD) -> pd.Series:
    """
    Binary direction label, ATR-normalised.
    Returns pd.Series in {0, 1, NaN}; NaN bars are excluded from training.
    """
    fwd_ret = df["close"].pct_change(horizon).shift(-horizon)
    atr     = df.get("atr_14", pd.Series(0.03, index=df.index)).clip(lower=0.005)
    z       = fwd_ret / (atr * np.sqrt(horizon))
    label   = pd.Series(np.nan, index=df.index, dtype=float)
    label[z >  z_thresh] = 1.0
    label[z < -z_thresh] = 0.0
    return label


# ── Feature engineering execution ────────────────────────────────────────────

def execute_feature_code(feature_code: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    Run Claude-supplied engineer_features(df) → DataFrame of new features.
    Returns combined (base + engineered) feature matrix ready for training.
    """
    ns: dict = {"pd": pd, "np": np}
    exec(compile(feature_code, "<feature>", "exec"), ns)
    if "engineer_features" not in ns:
        raise ValueError("Feature code must define engineer_features(df) -> pd.DataFrame")

    engineered = ns["engineer_features"](df.copy())
    if not isinstance(engineered, pd.DataFrame):
        raise TypeError(f"engineer_features must return a pd.DataFrame, got {type(engineered)}")
    if not engineered.index.equals(df.index):
        raise ValueError("Engineered features index mismatch with input df")

    # Drop any engineered column that is constant, all NaN, or non-numeric
    keep_cols = []
    for col in engineered.columns:
        s = engineered[col]
        if not pd.api.types.is_numeric_dtype(s):
            continue
        s_clean = s.replace([np.inf, -np.inf], np.nan).dropna()
        if len(s_clean) < 10 or s_clean.std() == 0:
            continue
        keep_cols.append(col)
    engineered = engineered[keep_cols]

    # Combine base (non-blacklisted) + engineered, drop NaN-padded leading rows
    base_cols = [c for c in df.columns if c not in _BLACKLIST]
    combined  = pd.concat([df[base_cols], engineered], axis=1)
    combined  = combined.replace([np.inf, -np.inf], np.nan)
    return combined


# ── Walk-forward LightGBM training & prediction ──────────────────────────────

def run_ml_walk_forward(
    df: pd.DataFrame,
    feature_code: str,
    freq: str = "1d",
    is_bars: int | None = None,
    oos_bars: int | None = None,
    step_bars: int | None = None,
    horizon: int = _LABEL_HORIZON,
    commission: float = 0.001,
    slippage: float = 0.001,
    stop_pct: float = 0.05,
    target_vol: float = 0.02,
    initial_capital: float = 10_000.0,
) -> tuple[BacktestResult, pd.Series]:
    """
    Walk-forward LightGBM backtest.
      1. Run engineer_features(df) once on the full df.
      2. Compute labels once.
      3. For each WFO window:
          a. Slice IS features + labels (drop NaN labels)
          b. Train LightGBM
          c. Predict on OOS features → probabilities → signal {-1, 0, +1}
          d. Apply risk management + standard backtest math
      4. Stitch all OOS strategy returns.
    """
    bpm = bars_per_month(freq)
    if is_bars   is None: is_bars   = 6 * bpm
    if oos_bars  is None: oos_bars  = 1 * bpm
    if step_bars is None: step_bars = 1 * bpm

    # Step 1+2 — engineer features and labels over the entire history
    features_full = execute_feature_code(feature_code, df)
    label_full    = create_label(df, horizon=horizon)

    feature_cols = features_full.columns.tolist()

    splits = walk_forward_splits(df, is_bars=is_bars, oos_bars=oos_bars, step_bars=step_bars)
    if not splits:
        raise ValueError(f"Insufficient data for WFO (need ≥ {is_bars + oos_bars} bars)")

    periods_per_year = PERIODS_PER_YEAR.get(freq, 252)
    cost_per_side    = commission + slippage

    raw_sig_parts:  list[pd.Series] = []
    eff_pos_parts:  list[pd.Series] = []
    strat_parts:    list[pd.Series] = []
    total_stops = 0

    for df_is, df_oos in splits:
        is_idx   = df_is.index
        oos_idx  = df_oos.index

        X_is  = features_full.loc[is_idx]
        y_is  = label_full.loc[is_idx]
        train_mask = y_is.notna() & X_is.notna().all(axis=1)
        if train_mask.sum() < _MIN_TRAIN_SAMPLES:
            # Not enough labelled bars in this IS window — skip with all-zero signal
            raw_sig_parts.append(pd.Series(0, index=oos_idx, dtype=int))
            eff_pos_parts.append(pd.Series(0.0, index=oos_idx, dtype=float))
            strat_parts.append(pd.Series(0.0, index=oos_idx, dtype=float))
            continue

        X_train = X_is[train_mask].values
        y_train = y_is[train_mask].astype(int).values

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_cols)
            model      = lgb.train(_LGB_PARAMS, train_data, num_boost_round=_LGB_BOOST_ROUNDS)

        X_oos = features_full.loc[oos_idx].values
        # Replace any remaining NaN with column mean from IS (cheap imputation)
        if np.isnan(X_oos).any():
            col_means = np.nanmean(X_train, axis=0)
            inds      = np.where(np.isnan(X_oos))
            X_oos[inds] = np.take(col_means, inds[1])

        prob_up = model.predict(X_oos)
        # Signal only on HIGH CONFIDENCE: must exceed both the absolute threshold
        # AND be in the top/bottom quantile of this window's predictions.
        # This prevents the model from producing constant-direction signals when
        # all its predictions happen to skew the same way.
        upper = max(_SIGNAL_UP_THRESHOLD,   float(np.quantile(prob_up, _SIGNAL_TOP_QUANTILE)))
        lower = min(_SIGNAL_DOWN_THRESHOLD, float(np.quantile(prob_up, _SIGNAL_BOT_QUANTILE)))
        signal_arr = np.where(prob_up >= upper, 1,
                      np.where(prob_up <= lower, -1, 0))
        raw_sig = pd.Series(signal_arr.astype(int), index=oos_idx)

        atr = df_oos.get("atr_14", pd.Series(0.03, index=oos_idx))
        eff_pos, n_stops = apply_risk_management(
            raw_positions=raw_sig,
            closes       = df_oos["close"],
            atr_norm     = atr,
            stop_pct     = stop_pct,
            target_vol   = target_vol,
        )
        bar_ret   = df_oos["close"].pct_change().fillna(0)
        strat_ret = _strategy_returns(eff_pos, bar_ret, cost_per_side)

        raw_sig_parts.append(raw_sig)
        eff_pos_parts.append(eff_pos)
        strat_parts.append(strat_ret)
        total_stops += n_stops

    combined_raw_sig = pd.concat(raw_sig_parts).sort_index()
    combined_eff_pos = pd.concat(eff_pos_parts).sort_index()
    combined_strat   = pd.concat(strat_parts).sort_index()

    combined_raw_sig = combined_raw_sig[~combined_raw_sig.index.duplicated(keep="last")]
    combined_eff_pos = combined_eff_pos[~combined_eff_pos.index.duplicated(keep="last")]
    combined_strat   = combined_strat[~combined_strat.index.duplicated(keep="last")]

    closes_arr = df.reindex(combined_eff_pos.index)["close"].values
    result     = _build_result(
        eff_positions    = combined_eff_pos,
        strat_returns    = combined_strat,
        closes           = closes_arr,
        cost_per_side    = cost_per_side,
        n_stops          = total_stops,
        periods_per_year = periods_per_year,
        initial_capital  = initial_capital,
    )
    return result, combined_raw_sig


# ── Validation helper used by the generator ──────────────────────────────────

def validate_feature_code(feature_code: str, df: pd.DataFrame) -> tuple[bool, str, int]:
    """
    Compile + run engineer_features once on a small df slice.
    Returns (ok, message, n_engineered_features).
    """
    try:
        combined = execute_feature_code(feature_code, df)
    except SyntaxError as e:
        return False, f"SyntaxError: {e}", 0
    except Exception as e:
        return False, f"Runtime error: {type(e).__name__}: {e}", 0

    base_cols = [c for c in df.columns if c not in _BLACKLIST]
    n_eng = len(combined.columns) - len(base_cols)
    if n_eng < 1:
        return False, "engineer_features returned no usable features (all dropped as constant/NaN/non-numeric)", 0
    if n_eng > 50:
        return False, f"Too many engineered features ({n_eng}) — limit to ≤ 20 for tractable training", n_eng

    return True, "OK", n_eng
