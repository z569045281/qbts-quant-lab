"""策略战绩复算(🏇 /factors 页,2026-07-08 起替代因子排行榜)。

把七匹在册纸面马的规则在**全部缓存历史**(QBTS 日线 ~500 根)上重放,产出:
  - trades[]  历史进出段(买入/卖出日期与收盘价、段收益、持有天数)
  - stats     全期/近1年收益、最大回撤、段数、胜率
  - current   当前状态(在场/空仓、敞口、入场价、浮动)

规则与 qbts_paper 台账同源(0.2%/边成本、收盘定仓吃次日收益);数字口径与
mining.md 回测一致。**这是回测复算,不是实盘记录** —— 实盘记录在马厩台账,
页面必须标注这一点。按最后 bar 日期做 JSON 文件缓存(每个交易日只算一次;
外部数据 QQQ/BTC/QTUM/IONQ 各拉一次 2y)。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_COST = 0.002
_CACHE = Path(__file__).parent.parent / "data" / "cache" / "strategy_replay.json"


def _dl(ticker: str) -> pd.Series | None:
    try:
        import yfinance as yf
        s = yf.download(ticker, period="2y", interval="1d",
                        auto_adjust=True, progress=False)["Close"].squeeze()
        if s is None or len(s) < 60:
            return None
        if s.index.tz is not None:
            s.index = s.index.tz_localize(None)
        return s
    except Exception as e:
        logger.warning(f"replay: {ticker} fetch failed — {e}")
        return None


def _nav_stats(sret: pd.Series) -> dict:
    nav = (1 + sret.fillna(0)).cumprod()
    dd = float((nav / nav.cummax() - 1).min())
    n1y = nav.iloc[-min(253, len(nav)):]
    w0 = min(60, len(nav) - 1)          # 扣指标热身,与 mining.md 回测同口径
    return {
        "ret_full": round(float(nav.iloc[-1] / nav.iloc[w0] - 1), 4),
        "ret_1y": round(float(n1y.iloc[-1] / n1y.iloc[0] - 1), 4),
        "max_dd": round(dd, 4),
    }, nav


def _segments(w: pd.Series, c: pd.Series, nav: pd.Series) -> list[dict]:
    """连续仓位 w>0 的进出段:买=w 由 0 转正那天的收盘,卖=归零那天的收盘。
    段收益用 NAV 比值(含真实仓位与成本),不是裸价差。"""
    out, in_i = [], None
    active = (w > 0).values
    for i in range(len(w)):
        if active[i] and in_i is None:
            in_i = i
        elif not active[i] and in_i is not None:
            out.append((in_i, i)); in_i = None
    if in_i is not None:
        out.append((in_i, None))
    trades = []
    for a, b in out:
        e = {"buy_date": str(c.index[a].date()), "buy_px": round(float(c.iloc[a]), 2)}
        if b is None:
            e |= {"open": True, "days": int(len(c) - 1 - a),
                  "ret": round(float(nav.iloc[-1] / nav.iloc[a] - 1), 4)}
        else:
            e |= {"open": False, "sell_date": str(c.index[b].date()),
                  "sell_px": round(float(c.iloc[b]), 2), "days": int(b - a),
                  "ret": round(float(nav.iloc[b] / nav.iloc[a] - 1), 4)}
        trades.append(e)
    return trades


def _pack(key, name, emoji, rule, w, c, extra_current=None) -> dict:
    ret = c.pct_change()
    sret = w.shift(1).fillna(0) * ret - _COST * w.diff().abs().fillna(0)
    stats, nav = _nav_stats(sret)
    trades = _segments(w, c, nav)
    closed = [t for t in trades if not t["open"]]
    wins = sum(1 for t in closed if t["ret"] > 0)
    cur_w = float(w.iloc[-1])
    cur = {"in_market": cur_w > 0, "exposure": round(cur_w, 2)}
    if trades and trades[-1]["open"]:
        cur |= {"since": trades[-1]["buy_date"], "entry_px": trades[-1]["buy_px"],
                "unreal": trades[-1]["ret"]}
    if extra_current:
        cur |= extra_current
    return {
        "key": key, "name": name, "emoji": emoji, "rule": rule,
        "stats": stats | {"n_trades": len(closed), "n_wins": wins,
                          "win_rate": round(wins / len(closed), 3) if closed else None},
        "current": cur,
        "trades": trades[::-1][:12],          # 最新在前,最多 12 段
        "n_trades_total": len(trades),
    }


def compute_replay(df_d: pd.DataFrame) -> dict | None:
    d = df_d.rename(columns=str.lower)
    if len(d) < 130 or not {"high", "low", "close"}.issubset(d.columns):
        return None
    c, h, l = d["close"].astype(float), d["high"].astype(float), d["low"].astype(float)
    idx = c.index
    as_of = str(pd.Timestamp(idx[-1]).date())

    # 缓存:同一根 bar 只算一次
    if _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text())
            if cached.get("as_of") == as_of:
                return cached
        except Exception:
            pass

    ret = c.pct_change()
    vol20 = ret.rolling(20).std() * np.sqrt(252)
    vt = (0.60 / vol20).clip(0.20, 1.00).fillna(0.5)

    qqq = _dl("QQQ")
    if qqq is None:
        return None
    qqq = qqq.reindex(idx).ffill()
    risk_on = (qqq > qqq.rolling(50).mean()).fillna(False)

    strategies = []

    # ① QQQ50×波动率目标
    strategies.append(_pack(
        "volreg", "QQQ50×波动率目标", "🥇",
        "QQQ 在 50 日线上才在场;仓位 = 0.6÷QBTS波动率(20%~100%)。回撤保护地基,三票交叉验证 3/3。",
        risk_on.astype(float) * vt, c))

    # ② 5日swing×QQQ50(事件式)
    lo5, hi5 = c.rolling(5).min(), c.rolling(5).max()
    pos, days, sw = 0.0, 0, []
    for i in range(len(c)):
        if pos > 0 and (c.iloc[i] >= hi5.iloc[i - 1] or days >= 10):
            pos, days = 0.0, 0
        elif pos == 0 and i > 5 and c.iloc[i] <= lo5.iloc[i - 1] and risk_on.iloc[i]:
            pos, days = 1.0, 0
        elif pos > 0:
            days += 1
        sw.append(pos)
    strategies.append(_pack(
        "swing", "5日swing×QQQ50", "🥈",
        "绿灯时收盘创5日新低买入;弹回5日新高或满10天卖出。无止损(回测:加止损毁掉它)。胜率~72%,三票 3/3。",
        pd.Series(sw, index=idx), c))

    # ③ BTC 昨日绿 ×QQQ50×波目
    btc = _dl("BTC-USD")
    if btc is not None:
        # 第四轮口径:BTC 收盘序列先对齐交易日(周一含周末),信号(t) 吃 t+1 收益
        # (_pack 里统一 shift(1));多 shift 一天会把 1 天领先的肉全挪没。
        bg = (btc.reindex(idx).ffill().pct_change() > 0).fillna(False)
        strategies.append(_pack(
            "btc", "BTC昨日绿×QQQ50", "🆕",
            "BTC 昨天收涨且绿灯 → 按波目持有;否则空仓。回撤全场最浅(−20%),QBTS 是它最佳宿主。",
            (bg & risk_on).astype(float) * vt, c))

    # ④ CLV 强收盘 ×QQQ50×波目
    clv = ((2 * c - h - l) / (h - l).replace(0, np.nan)).fillna(0)
    strategies.append(_pack(
        "clv", "CLV强收盘×QQQ50", "🆕",
        "昨天收盘收在当日区间上部(CLV>0.3)且绿灯 → 持有今天。吃 1 天惯性;交叉验证 0/3,QBTS 特有,打折看。",
        ((clv > 0.3) & risk_on).astype(float) * vt, c))

    # ⑤ 配对超涨 veto
    ionq = _dl("IONQ")
    if ionq is not None:
        spread = (np.log(c) - np.log(ionq.reindex(idx).ffill())).dropna()
        z40 = ((spread - spread.rolling(40).mean()) / spread.rolling(40).std()).reindex(idx)
        strategies.append(_pack(
            "veto", "配对超涨veto", "🆕",
            "照①做,但 QBTS 比 IONQ 贵出1σ(40日z>1)时强制清仓等。交叉验证 0/3,QBTS 特有,打折看。",
            (risk_on & (z40 <= 1.0).fillna(True)).astype(float) * vt, c,
            extra_current={"z40": round(float(z40.iloc[-1]), 2) if pd.notna(z40.iloc[-1]) else None}))

    # ⑥ QTUM 板块昨日绿
    qtum = _dl("QTUM")
    if qtum is not None:
        qg = (qtum.reindex(idx).ffill().pct_change() > 0).fillna(False)   # 同 BTC 口径
        strategies.append(_pack(
            "qtum", "QTUM板块绿×QQQ50", "🆕",
            "量子板块 ETF 昨天收涨且绿灯 → 按波目持有。注意 QTUM 自含 QBTS 权重,榜首数字有水分。",
            (qg & risk_on).astype(float) * vt, c))

    # ⑦ 特调双腿(事件式)
    def wpr(n):
        hh, ll = h.rolling(n).max(), l.rolling(n).min()
        return (hh - c) / (hh - ll).replace(0, np.nan) * -100
    f_, s_ = wpr(22), wpr(112).rolling(3).mean()
    buy = ((f_ > -80) & (f_.shift(1) <= -80) & (s_ < -50)).fillna(False)
    sell = (((f_ < -20) & (f_.shift(1) >= -20) & (s_ >= -20)) |
            ((f_ < -50) & (f_.shift(1) >= -50) & (s_ < -20))).fillna(False)
    pos, tj = 0.0, []
    for i in range(len(c)):
        if pos > 0 and sell.iloc[i]:
            pos = 0.0
        elif pos == 0 and buy.iloc[i]:
            pos = 1.0
        tj.append(pos)
    strategies.append(_pack(
        "tj", "特调双腿(用户自创)", "🎯",
        "快%R上穿−80且慢<−50 → 抄底买入;快%R下穿−20(止盈)或下穿−50(破位)→ 卖出。进场腿十三轮最强(+17.4%/5天),QBTS 专用。",
        pd.Series(tj, index=idx), c))

    # B&H 基准
    bh_stats, _ = _nav_stats(ret)

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": as_of,
        "window_start": str(pd.Timestamp(idx[0]).date()),
        "bh": bh_stats,
        "strategies": strategies,
    }
    try:
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(json.dumps(out, ensure_ascii=False))
    except Exception:
        pass
    return out
