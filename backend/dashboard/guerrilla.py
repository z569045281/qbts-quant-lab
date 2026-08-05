"""🎯 极度超卖游击战 (Extreme Reversion) — 服务端自算 + ntfy 观察模块。

用户点单(2026-07-22):Bear Lock 下的逆宏观、顺微观订单流多头游击线程。
**无 webhook、无 TradingView**(2026-07-22 用户改口"webhook和TV都不需要,触发了
发 ntfy 就行")—— 三个条件全在服务端用现有数据自算,收盘后跑一遍,触发即推:
  A 动能极值: 日线 WaveTrend(VMC/Cipher-B 核心线,wavetrend.py 同源)wt1 < -70
  B 微观停机坪: 连续两根日线的 Intrabar POC(15m 子bar 重构 volume-at-price)
    横向重合 ≤ $0.05 —— 主力限价承接的证据
  C 刺客盈亏比: entry=收盘, stop=POC底座-$0.05, target=上方最近历史POC墙(无则
    50日高), RR≥2.5
满足即:ntfy 推送 + $1000/枪纸面记账;QuoteFunction 分钟 tick 盯 stop/target 触碰
结算;平仓瞬间武装 **24h 强制冷却**(冷却由平仓武装,不是进场)。

零决策权:不进 edge、不进决策 prompt、不碰真金。UNPROVEN,8/15 同审。
状态全部持久化 Supabase 单表(id 前缀分片)—— Lambda /tmp 冷启动清空是本仓库
反复踩过的坑(FINRA/财报日历),内存/本地盘一律不信:
  meta              {last_compute_date}             收盘后每日只算一次的去重
  cooldown:<TICKER> {cooldown_until_epoch, ...}      24h 冷却锁
  open:<TICKER>     {entry, stop, target, rr, ...}   在场仓位
  ledger            {trades: [...], n_win, realized} 已结算流水(cap 100)
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_TABLE = "guerrilla_state"
_COOLDOWN_S = 24 * 3600
_PAPER_USD = 1000.0
_COST = 0.002                      # 0.2%/边,与 scan_paper 同口径
_LEDGER_CAP = 100
_TICKER = "QBTS"                   # 主标的(游击战只跟 QBTS,与主决策同一只票)
_VMC_FLOOR = -70.0                 # Cond A: wt1 < -70(实测日线 4.4% 的天数达标)
_POC_TOL = 0.05                    # Cond B: 连续两日 POC 重合容差
_RR_MIN = 2.5                      # Cond C


from dashboard.db import supabase as _sb   # 全仓共用一个客户端


def _get(sb, sid: str) -> dict | None:
    rows = sb.table(_TABLE).select("data").eq("id", sid).execute().data
    return rows[0]["data"] if rows and rows[0].get("data") else None


def _put(sb, sid: str, data: dict) -> None:
    sb.table(_TABLE).upsert({
        "id": sid, "updated_at": datetime.now(timezone.utc).isoformat(), "data": data,
    }).execute()


def cooldown_active(sb, ticker: str) -> tuple[bool, float]:
    """(冷却中?, 剩余秒)。读失败 fail-CLOSED —— 状态不明时拒signal,宁漏勿重。"""
    try:
        st = _get(sb, f"cooldown:{ticker}")
    except Exception as e:
        logger.warning(f"guerrilla: 冷却状态读取失败,fail-closed — {e}")
        return True, float("nan")
    if not st:
        return False, 0.0
    until = float(st.get("cooldown_until_epoch", 0))
    now = time.time()                # 服务器钟是唯一真理,不信 webhook 时间戳
    return now < until, max(0.0, until - now)


def arm_cooldown(sb, ticker: str, reason: str) -> None:
    until = time.time() + _COOLDOWN_S
    _put(sb, f"cooldown:{ticker}", {
        "cooldown_until_epoch": until,
        "cooldown_until_iso": datetime.fromtimestamp(until, timezone.utc).isoformat(),
        "armed_reason": reason,
        "armed_at_iso": datetime.now(timezone.utc).isoformat(),
    })


def _wt1(df_d: pd.DataFrame) -> float | None:
    """WaveTrend wt1(VMC/Cipher-B 核心线,与 wavetrend.py 同参 10/21)。"""
    try:
        d = df_d.rename(columns=str.lower)
        ap = (d["high"] + d["low"] + d["close"]) / 3
        esa = ap.ewm(span=10, adjust=False).mean()
        dd = (ap - esa).abs().ewm(span=10, adjust=False).mean()
        ci = (ap - esa) / (0.015 * dd)
        return float(ci.ewm(span=21, adjust=False).mean().iloc[-1])
    except Exception:
        return None


def _intrabar_poc(df15: pd.DataFrame, day: pd.Timestamp, bin_w: float = 0.01) -> float | None:
    """单个交易日的 Intrabar POC:15m 子bar 的 volume-at-price 直方图峰值价。
    比 Pine 的 5m 粗(15m ~26根/日 vs 5m ~78根),但 yfinance 稳定拿得到的最细口径。"""
    try:
        d = df15.rename(columns=str.lower)
        idx = pd.DatetimeIndex(d.index).normalize()
        sub = d[idx == day]
        if len(sub) < 4:
            return None
        tp = (sub["high"] + sub["low"] + sub["close"]) / 3
        vol = sub["volume"].astype(float)
        lo = float(tp.min())
        if not np.isfinite(lo):
            return None
        acc: dict[int, float] = {}
        for p, v in zip(tp, vol):
            b = int(round((p - lo) / bin_w))
            acc[b] = acc.get(b, 0.0) + v
        if not acc:
            return None
        best = max(acc, key=acc.get)
        return round(lo + best * bin_w, 2)
    except Exception:
        return None


def compute_signal(df_d: pd.DataFrame, df15: pd.DataFrame) -> dict | None:
    """三条件全算(收盘确认口径,用完整日线 bar)。命中返回 entry/stop/target/rr,
    否则返回 None + 附读数供调试。纯函数,不碰 Supabase。"""
    if df_d is None or len(df_d) < 30 or df15 is None:
        return None
    d = df_d.rename(columns=str.lower)
    entry = float(d["close"].iloc[-1])

    # A: VMC 极值
    wt1 = _wt1(df_d)
    condA = wt1 is not None and wt1 < _VMC_FLOOR

    # B: 连续两日 Intrabar POC 停机坪(≤$0.05)
    days = pd.DatetimeIndex(df15.index).normalize().unique().sort_values()
    poc_now = _intrabar_poc(df15, days[-1]) if len(days) >= 1 else None
    poc_prev = _intrabar_poc(df15, days[-2]) if len(days) >= 2 else None
    condB = (poc_now is not None and poc_prev is not None
             and abs(poc_now - poc_prev) <= _POC_TOL)

    # C: 刺客 RR —— stop=POC底座-0.05, target=上方最近历史POC墙(无则50日高)
    stop = target = rr = None
    if condB:
        base = min(poc_now, poc_prev)
        stop = round(base - 0.05, 2)
        walls = sorted({p for p in (_intrabar_poc(df15, dd) for dd in days[:-1])
                        if p is not None and p > entry * 1.005})
        target = walls[0] if walls else round(float(d["high"].tail(50).max()), 2)
        risk = entry - stop
        rr = round((target - entry) / risk, 2) if risk > 0 else 0.0
    condC = rr is not None and rr >= _RR_MIN and stop < entry < target

    read = {"wt1": round(wt1, 1) if wt1 is not None else None,
            "poc_now": poc_now, "poc_prev": poc_prev,
            "A": condA, "B": condB, "C": condC}
    if condA and condB and condC:
        return {"entry": round(entry, 2), "stop": stop, "target": target,
                "rr": rr, "wt1": read["wt1"], "poc": poc_now, "read": read}
    return {"fired": False, "read": read}


def maybe_guerrilla_signal(now_et) -> dict | None:
    """收盘后每日算一次(16:05–20:00 ET,date 去重),命中→ntfy+开纸面仓。
    QuoteFunction 分钟 tick 调用;非窗口/已算过/冷却中/已持仓 → 秒退。"""
    if now_et.weekday() >= 5 or not ((16, 5) <= (now_et.hour, now_et.minute) < (20, 0)):
        return None
    sb = _sb()
    if sb is None:
        return None
    today = now_et.strftime("%Y-%m-%d")
    try:
        meta = _get(sb, "meta") or {}
        if meta.get("last_compute_date") == today:
            return None
    except Exception as e:
        logger.warning(f"guerrilla: meta 读取失败,跳过本 tick — {e}")
        return None

    active, left = cooldown_active(sb, _TICKER)
    if active:                      # fail-CLOSED 已含在 cooldown_active
        _put(sb, "meta", {"last_compute_date": today})   # 冷却中也标记已算,免每分钟重试
        return None
    if _get(sb, f"open:{_TICKER}"):
        _put(sb, "meta", {"last_compute_date": today})
        return None

    try:
        from data.fetcher import load_or_fetch, load_15m
        _, df_d = load_or_fetch(_TICKER)
        df15 = load_15m(_TICKER)
        sig = compute_signal(df_d, df15)
    except Exception as e:
        logger.warning(f"guerrilla: 信号计算失败 — {e}")
        return None

    _put(sb, "meta", {"last_compute_date": today})       # 无论命中都标记,当天不再算
    if not sig or not sig.get("entry"):
        return None                # 未命中(常态)

    _put(sb, f"open:{_TICKER}", {
        "ticker": _TICKER, "entry": sig["entry"], "stop": sig["stop"],
        "target": sig["target"], "rr": sig["rr"], "wt1": sig["wt1"],
        "shares": round(_PAPER_USD / sig["entry"], 4),
        "opened_at": datetime.now(timezone.utc).isoformat(), "status": "open",
    })
    _ntfy(f"ER signal {_TICKER}",
          f"极度超卖游击战开枪:{_TICKER} VMC={sig['wt1']} 进场 ${sig['entry']} "
          f"止损 ${sig['stop']} 目标 ${sig['target']} RR {sig['rr']}(纸面$1000,观察模块)")
    logger.info(f"guerrilla: OPEN {_TICKER} {sig}")
    return {"fired": True, **sig}


def check_exits(now_et=None) -> dict | None:
    """QuoteFunction 分钟 tick 调用(minute%5==4,错开 SMC/挑战/地缘分钟)。
    只在存在 open 仓位时才拉行情(平时零成本);触 stop/target → 结算+冷却。"""
    if now_et is not None and now_et.minute % 5 != 4:
        return None
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = sb.table(_TABLE).select("id,data").like("id", "open:%").execute().data
    except Exception as e:
        logger.warning(f"guerrilla: open 仓位读取失败 — {e}")
        return None
    if not rows:
        return None

    out = {}
    for row in rows:
        pos = row.get("data") or {}
        tk = pos.get("ticker") or row["id"].split(":", 1)[1]
        px = _last_price(tk)
        if px is None:
            continue
        exit_px, why = None, None
        if px <= pos["stop"]:
            exit_px, why = pos["stop"], "stop"      # 保守:按止损价结算,不按更差现价
        elif px >= pos["target"]:
            exit_px, why = pos["target"], "target"
        if exit_px is None:
            continue
        ret = (exit_px / pos["entry"] - 1) - 2 * _COST
        pnl = round(_PAPER_USD * ret, 2)
        trade = {**pos, "exit": exit_px, "exit_why": why, "ret_pct": round(ret, 4),
                 "pnl": pnl, "closed_at": datetime.now(timezone.utc).isoformat(),
                 "status": "closed"}
        try:
            led = _get(sb, "ledger") or {"trades": []}
            led["trades"] = ([trade] + led.get("trades", []))[:_LEDGER_CAP]
            closed = led["trades"]
            led["n_trades"] = len(closed)
            led["n_win"] = sum(1 for t in closed if t.get("pnl", 0) > 0)
            led["realized"] = round(sum(t.get("pnl", 0) for t in closed), 2)
            _put(sb, "ledger", led)
            sb.table(_TABLE).delete().eq("id", row["id"]).execute()
            arm_cooldown(sb, tk, f"{why}@{exit_px}")   # 冷却由平仓武装,不是进场
        except Exception as e:
            logger.warning(f"guerrilla: 结算写入失败({tk}) — {e}")
            continue
        _ntfy(f"ER exit {tk}",
              f"游击战平仓:{tk} {'止盈' if why == 'target' else '止损'} @${exit_px} "
              f"盈亏 {pnl:+.0f}(${_PAPER_USD:.0f}仓)· 进入24h冷却")
        out[tk] = {"exit": exit_px, "why": why, "pnl": pnl}
        logger.info(f"guerrilla: CLOSE {tk} {why}@{exit_px} pnl={pnl}")
    return out or None


def _last_price(ticker: str) -> float | None:
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period="1d", interval="1m", prepost=True)
        if len(h) > 0:
            return float(h["Close"].iloc[-1])
        return float(yf.Ticker(ticker).fast_info.last_price)
    except Exception as e:
        logger.warning(f"guerrilla: {ticker} 价格获取失败 — {e}")
        return None


from dashboard.notify import push as _ntfy   # 全仓唯一一份推送
