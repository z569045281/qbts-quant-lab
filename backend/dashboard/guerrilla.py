"""🎯 极度超卖游击战 (Extreme Reversion) — TradingView webhook 观察模块。

用户点单(2026-07-22):Bear Lock 下的逆宏观、顺微观订单流多头游击线程。
信号完全由用户的 TradingView Pine 脚本生成(VMC<-70 + 连续两根K线 Intrabar
POC 重合≤$0.05 + RR≥2.5),webhook 打进来;本模块只做三件事:
  ① 闸门:secret 校验(URL query,TV 不支持自定义 header)+ bar_ts 幂等去重
    + 24h 冷却锁(fail-CLOSED:状态读不到=拒信号,高危模块宁漏勿重)
  ② 纸面记账:$1000/枪(与 journal/scan 同口径),QuoteFunction 分钟 tick
    盯 stop/target 触碰结算;平仓瞬间武装 24h 冷却
  ③ 展示:/factors 策略战绩页直读 guerrilla_state 表渲染

零决策权:不进 edge、不进决策 prompt、不碰真金。UNPROVEN,8/15 同审。
状态全部持久化 Supabase 单表(id 前缀分片)—— Lambda /tmp 冷启动清空是本仓库
反复踩过的坑(FINRA/财报日历),内存/本地盘一律不信:
  cooldown:<TICKER> {cooldown_until_epoch, armed_reason, ...}
  lastsig:<TICKER>  {bar_ts}                       幂等去重
  open:<TICKER>     {entry, stop, target, rr, ...} 在场仓位
  ledger            {trades: [...], n_win, realized} 已结算流水(cap 100)
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_TABLE = "guerrilla_state"
_COOLDOWN_S = 24 * 3600
_PAPER_USD = 1000.0
_COST = 0.002                      # 0.2%/边,与 scan_paper 同口径
_LEDGER_CAP = 100


def _sb():
    from supabase import create_client
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        return None
    return create_client(url, key)


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


def on_signal(body: dict) -> dict:
    """Webhook 入口(secret 已在上游校验)。返回 dict 作 HTTP 响应体。"""
    sb = _sb()
    if sb is None:
        return {"ok": False, "why": "supabase not configured"}
    tk = str(body.get("ticker", "")).strip().upper()
    if not tk or body.get("module") != "extreme_reversion":
        return {"ok": False, "why": "bad payload"}
    try:
        entry, stop, target = float(body["entry"]), float(body["stop"]), float(body["target"])
        rr = float(body.get("rr", 0))
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "why": "bad numbers"}
    if not (stop < entry < target):
        return {"ok": False, "why": f"geometry invalid: {stop}/{entry}/{target}"}

    # 幂等去重(TV 会重试同一告警;bar_ts 即天然去重键)。读失败不挡路 —— 冷却锁才是硬闸
    bar_ts = int(body.get("bar_ts", 0) or 0)
    try:
        last = _get(sb, f"lastsig:{tk}")
        if last and last.get("bar_ts") == bar_ts and bar_ts:
            return {"ok": True, "dedup": True}
    except Exception:
        pass

    active, left = cooldown_active(sb, tk)
    if active:
        logger.info(f"guerrilla: {tk} 冷却中(剩 {left/3600:.1f}h),信号丢弃")
        return {"ok": True, "suppressed": "cooldown", "left_s": round(left)}

    if _get(sb, f"open:{tk}"):
        return {"ok": True, "suppressed": "already_open"}

    _put(sb, f"lastsig:{tk}", {"bar_ts": bar_ts})
    _put(sb, f"open:{tk}", {
        "ticker": tk, "entry": entry, "stop": stop, "target": target,
        "rr": round(rr, 2), "wt1": body.get("wt1"),
        "shares": round(_PAPER_USD / entry, 4),
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "status": "open",
    })
    _ntfy(f"ER signal {tk}",
          f"极度超卖游击战开枪:{tk} 进场 ${entry} 止损 ${stop} 目标 ${target} RR {rr:.1f}"
          f"(纸面 $1000,观察模块)")
    logger.info(f"guerrilla: OPEN {tk} @{entry} stop={stop} target={target}")
    return {"ok": True, "accepted": True}


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


def _ntfy(title: str, body: str) -> None:
    """复用 NTFY_TOPIC;标题保持 ASCII(HTTP header 是 latin-1),中文进 body。"""
    topic = os.getenv("NTFY_TOPIC")
    if not topic:
        return
    try:
        import requests
        requests.post(f"{os.getenv('NTFY_URL', 'https://ntfy.sh')}/{topic}",
                      data=body.encode(), headers={"Title": title}, timeout=8)
    except Exception:
        pass
