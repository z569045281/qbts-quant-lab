"""
Kalman filters for QBTS feature engineering — pure numpy, dependency-light.

CRITICAL — NO LOOK-AHEAD:
  Both filters are the FORWARD (causal) Kalman filter only. The estimate at
  bar t uses observations [0..t]. We never run the RTS smoother (which uses
  future bars and would leak look-ahead into features). The hedge-ratio
  "spread" is the one-step prediction error (uses the PRIOR state, before
  seeing y_t) — a genuine out-of-sample residual.

Two models:

  1. Local Linear Trend (LLT) — denoise price into [level, velocity].
       state  x = [level, velocity]
       F = [[1,1],[0,1]]   H = [1,0]
       level_t   = level_{t-1} + velocity_{t-1} + noise
       velocity_t= velocity_{t-1} + noise
     velocity is a cleaner momentum signal than raw returns;
     (close - level) is a mean-reversion signal (distance from KF fair value).

  2. Dynamic Hedge Ratio — pairs trading vs a peer (IONQ/RGTI).
       y_t = alpha_t + beta_t * x_t + noise,  random-walk on [alpha, beta]
     The innovation e_t = y_t - (alpha + beta*x_t) is the tradeable spread;
     extreme |z-score(e)| flags mean-reversion opportunities.
"""

from __future__ import annotations

import numpy as np


def kalman_local_linear_trend(
    prices: np.ndarray,
    q_level: float = 1e-3,
    q_vel:   float = 1e-4,
    r:       float | None = None,
    warmup:  int = 30,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Forward Kalman on a Local Linear Trend model.

    Args:
        prices : 1-D array of close prices (may contain NaN — held as 'no obs')
        q_level, q_vel : process-noise variances. Higher = more responsive.
        r      : observation-noise variance. If None, estimated from the FIRST
                 `warmup` finite diffs only (so it's causal / truncation-invariant —
                 estimating r from the whole series would leak future volatility).

    Returns:
        (level, velocity) arrays, same length, causal (no look-ahead for t≥warmup).
    """
    p = np.asarray(prices, dtype=float)
    n = len(p)
    level = np.full(n, np.nan)
    vel   = np.full(n, np.nan)
    if n == 0:
        return level, vel

    finite = p[np.isfinite(p)]
    if len(finite) < 3:
        level[:] = np.where(np.isfinite(p), p, finite[0] if len(finite) else 0.0)
        vel[:]   = 0.0
        return level, vel

    if r is None:
        # Estimate noise from the warmup window ONLY — never from future bars.
        d = np.diff(finite[:max(warmup, 5)])
        r = float(np.var(d)) if np.var(d) > 0 else 1.0

    F = np.array([[1.0, 1.0], [0.0, 1.0]])
    H = np.array([[1.0, 0.0]])
    Q = np.array([[q_level, 0.0], [0.0, q_vel]])

    # init at first finite observation
    first = int(np.argmax(np.isfinite(p)))
    x = np.array([[p[first]], [0.0]])
    P = np.eye(2)

    for t in range(n):
        if t > first:
            # predict
            x = F @ x
            P = F @ P @ F.T + Q
        z = p[t]
        if np.isfinite(z) and t >= first:
            y = z - (H @ x)[0, 0]               # innovation
            S = (H @ P @ H.T)[0, 0] + r
            K = (P @ H.T) / S                    # 2x1 gain
            x = x + K * y
            P = (np.eye(2) - K @ H) @ P
        level[t] = x[0, 0]
        vel[t]   = x[1, 0]

    return level, vel


def kalman_hedge_ratio(
    y: np.ndarray,
    x: np.ndarray,
    delta: float = 1e-4,
    r:     float = 1e-3,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Dynamic hedge ratio via Kalman (Chan's formulation).

    y_t = alpha_t + beta_t * x_t + noise,  random walk on [alpha, beta].
    delta in (0,1): adaptation speed of the hedge ratio (higher = faster).

    Returns:
        (alpha, beta, spread) arrays, causal. `spread` is the one-step
        prediction error (out-of-sample residual) — the tradeable signal.
    """
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    n = len(y)
    alphas  = np.full(n, np.nan)
    betas   = np.full(n, np.nan)
    spreads = np.full(n, np.nan)
    if n == 0:
        return alphas, betas, spreads

    Vw = (delta / (1.0 - delta)) * np.eye(2)    # process covariance
    state = np.array([[0.0], [0.0]])            # [alpha, beta]
    P = np.zeros((2, 2))

    for t in range(n):
        if not (np.isfinite(y[t]) and np.isfinite(x[t])):
            alphas[t]  = state[0, 0]
            betas[t]   = state[1, 0]
            spreads[t] = 0.0
            continue
        H = np.array([[1.0, x[t]]])             # time-varying observation matrix
        P = P + Vw                              # predict (random-walk state)
        yhat = (H @ state)[0, 0]
        e = y[t] - yhat                         # out-of-sample spread (uses prior state)
        S = (H @ P @ H.T)[0, 0] + r
        K = (P @ H.T) / S
        state = state + K * e
        P = P - K @ H @ P
        alphas[t]  = state[0, 0]
        betas[t]   = state[1, 0]
        spreads[t] = e

    return alphas, betas, spreads


def rolling_zscore(arr: np.ndarray, window: int = 20) -> np.ndarray:
    """Causal rolling z-score (uses only past `window` values up to t)."""
    a = np.asarray(arr, dtype=float)
    n = len(a)
    out = np.zeros(n)
    for t in range(n):
        lo = max(0, t - window + 1)
        w = a[lo:t + 1]
        w = w[np.isfinite(w)]
        if len(w) >= 5:
            mu, sd = w.mean(), w.std()
            out[t] = (a[t] - mu) / sd if sd > 1e-9 and np.isfinite(a[t]) else 0.0
    return np.clip(out, -5, 5)
