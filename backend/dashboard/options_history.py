"""
QBTS 期权链**历史**数据管线(第四十二轮产出,2026-08-24)。

背景:mining.md 第二十一轮收矿时写「复挖需新数据维度(期权链历史/融券费率,均付费)」。
**这条已过时** —— .env 里现有的 Alpaca key 就能免费拉 OPRA 期权日线。

关键机制(踩过的坑,别再踩):
  1. `/v2/options/contracts` 只返回**未过期**合约 → 拿不到历史合约列表。
     但 `/v1beta1/options/bars` 对**过期合约照给数据**,OCC 符号自己拼即可。
  2. **未到期**合约需签 OPRA 协议(免费但未签)→ 返回 403 "OPRA agreement is not signed"。
     所以历史可用、实时不可用;合约到期后数据自动开放,每月自然补齐。
  3. 实测数据边界:**2024-01-18** 起。

产出:reverse-BS 得到的 IV 曲面特征(ATM IV / 偏斜 / 期限结构 / VRP)。

⚠️ 用途限制(第四十二轮实证,别接错地方):
  - ❌ **不要**用它做方向判断。控制掉价格特征后增量为零,偏斜与未来收益相关 +0.002。
  - ✅ **可以**用它预报**幅度**。ATM IV 对未来 10 日累计波动:
    仅价格 R²=0.178 → 加隐含 R²=0.422(Newey-West t=+6.56)。
    隐含最低档未来 10 日出现 ≥8% 跳的概率 74%,最高档 98%。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_BARS = "https://data.alpaca.markets/v1beta1/options/bars"
_DATA_START = "2024-01-01"          # 实测最早 bar 2024-01-18


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY", ""),
    }


def _get(url: str, tries: int = 4) -> dict:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=_headers())
            return json.load(urllib.request.urlopen(req, timeout=120))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503):
                time.sleep(2 * (i + 1))
                continue
            body = e.read()[:200].decode("utf8", "ignore")
            if e.code == 403 and "OPRA" in body:
                logger.debug("未到期合约需 OPRA 协议,跳过: %s", url[:80])
                return {}
            logger.warning("options bars %s: %s", e.code, body)
            return {}
        except Exception:
            time.sleep(2 * (i + 1))
    return {}


def occ_symbol(ticker: str, exp: dt.date, cp: str, strike: float) -> str:
    """拼 OCC 符号。cp = 'C' | 'P'"""
    return f"{ticker}{exp:%y%m%d}{cp}{int(round(strike * 1000)):08d}"


def third_friday(year: int, month: int) -> dt.date:
    d = dt.date(year, month, 1)
    fridays = [
        d + dt.timedelta(i)
        for i in range(31)
        if (d + dt.timedelta(i)).month == month and (d + dt.timedelta(i)).weekday() == 4
    ]
    return fridays[2]


def fetch_bars(ticker: str, expirations, strikes, start: str = _DATA_START) -> pd.DataFrame:
    """按到期日 × 行权价网格拉日线。返回 date/exp/cp/strike/close/vwap/vol/ntrades。"""
    rows = []
    for exp in expirations:
        syms = [occ_symbol(ticker, exp, cp, k) for cp in "CP" for k in strikes]
        for i in range(0, len(syms), 60):          # 一次 60 个符号,实测稳定
            token = None
            while True:
                params = {
                    "symbols": ",".join(syms[i:i + 60]),
                    "timeframe": "1Day",
                    "start": start,
                    "end": (exp + dt.timedelta(days=1)).isoformat(),
                    "limit": 10000,
                }
                if token:
                    params["page_token"] = token
                r = _get(f"{_BARS}?{urllib.parse.urlencode(params)}")
                for sym, bars in (r.get("bars") or {}).items():
                    cp = "C" if sym[-9] == "C" else "P"
                    strike = int(sym[-8:]) / 1000.0
                    for b in bars:
                        rows.append((b["t"][:10], exp.isoformat(), cp, strike,
                                     b["c"], b["vw"], b["v"], b["n"]))
                token = r.get("next_page_token")
                if not token:
                    break
            time.sleep(0.05)
    df = pd.DataFrame(rows, columns=["date", "exp", "cp", "strike",
                                     "close", "vwap", "vol", "ntrades"])
    return df.drop_duplicates(subset=["date", "exp", "cp", "strike"])


# ── Black-Scholes 反解 ────────────────────────────────────────────────────────

def _norm_cdf(x):
    from scipy.stats import norm
    return norm.cdf(x)


def bs_price(S, K, T, r, sigma, cp):
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if cp == "C" else (K - S))
    d1 = (np.log(S / K) + (r + sigma * sigma / 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if cp == "C":
        return S * _norm_cdf(d1) - K * np.exp(-r * T) * _norm_cdf(d2)
    return K * np.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def implied_vol(price, S, K, T, r, cp):
    """无解返回 NaN(价格穿破无套利边界时必然无解,属正常)。"""
    from scipy.optimize import brentq
    intrinsic = max(0.0, (S - K) if cp == "C" else (K - S))
    if price <= intrinsic + 1e-6 or T <= 0:
        return np.nan
    upper = S if cp == "C" else K * np.exp(-r * T)
    if price >= upper * 0.999:
        return np.nan
    try:
        return brentq(lambda s: bs_price(S, K, T, r, s, cp) - price,
                      1e-4, 8.0, maxiter=60, xtol=1e-5)
    except Exception:
        return np.nan


def surface(iv_points: pd.DataFrame) -> pd.DataFrame:
    """
    IV 点 → 每日曲面特征。iv_points 需含 date/dte/iv/strike/S/ntrades。

    ⚠️ 坑:列名别用 'T' —— `df.T` 是 DataFrame 转置,会静默把整列换成转置结果
    (第四十二轮实际踩到,26,473 个点只解出 1 个)。本模块统一用 'tau'。
    """
    m = iv_points.copy()
    m["x"] = np.log(m.strike / m.S)
    m["w"] = np.sqrt(m.ntrades.clip(1, 500))

    def _fit(g):
        g = g[g.x.abs() < 0.55]
        if len(g) < 6 or (g.x < -0.02).sum() < 2 or (g.x > 0.02).sum() < 2:
            return None
        X = np.column_stack([np.ones(len(g)), g.x, g.x ** 2])
        W = np.diag(g.w.values)
        try:
            beta = np.linalg.solve(X.T @ W @ X, X.T @ W @ g.iv.values)
        except np.linalg.LinAlgError:
            return None
        f = lambda xx: beta[0] + beta[1] * xx + beta[2] * xx * xx
        atm = f(0.0)
        if not (0.2 < atm < 5.0):
            return None
        # skew = 看跌翼 − 看涨翼(正 = 恐慌,负 = 欣快)。实测对方向无信息,仅存档。
        return dict(atm=atm, skew=f(-0.223) - f(0.223), curv=beta[2])

    out = []
    for d, g in m.groupby("date"):
        base = _fit(g[g.dte.between(7, 90)])
        if base is None:
            continue
        short = _fit(g[g.dte.between(7, 45)]) or {}
        long_ = _fit(g[g.dte.between(40, 120)]) or {}
        out.append(dict(
            date=d, S=g.S.iloc[0], atm_iv=base["atm"], skew=base["skew"],
            curv=base["curv"],
            iv_short=short.get("atm", np.nan), iv_long=long_.get("atm", np.nan),
        ))
    s = pd.DataFrame(out).set_index("date").sort_index()
    s["term"] = s.iv_short - s.iv_long          # >0 = 近端倒挂
    return s


def jump_risk_band(atm_iv: float) -> dict:
    """
    把当前 ATM 隐含波动率翻译成「未来 10 日会跳多大」的实测读数。
    分档来自第四十二轮 n=450 的实测四分位,**只报幅度,不报方向**。
    """
    if atm_iv is None or not np.isfinite(atm_iv):
        return {}
    if atm_iv < 0.95:
        band, jump, p8 = "Q1 低", 0.112, 0.74
    elif atm_iv < 1.10:
        band, jump, p8 = "Q2", 0.110, 0.69
    elif atm_iv < 1.43:
        band, jump, p8 = "Q3", 0.140, 0.90
    else:
        band, jump, p8 = "Q4 高", 0.220, 0.98
    return {
        "band": band,
        "expected_max_daily_move_10d": jump,
        "p_gap_ge_8pct_10d": p8,
        "note": "纯幅度信号。方向无信息(实测四档 fwd10 中位 +3.8/−0.8/−5.3/+2.2%,不单调)。",
    }
