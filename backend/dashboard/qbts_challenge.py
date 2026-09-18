"""
🎯 QBTS $1000 纸面挑战 —— Claude 自营(2026-09-18 用户点单)。

用户原话:「给你 1000 刀,自由买卖 QBTS,根据已有的数据和回测自己想办法赚钱,
至少每个月赚回订阅费,记录买入和卖出,类似隔壁的 5000 挑战」。
同日改口:「尽可能赚钱就可以,别管订阅费」→ 月报对照改成「同月一直拿着 QBTS」。

**纸面,不是真金**(铁律:真金只给建议不代下单)。Alpaca paper 真实挂单、纸面成交,
与 challenge2 同一个纸面账户;本 bot 只碰 QBTS,challenge2 只碰杠杆 ETF,互不串仓。

规则 —— 不新造信号,机械执行在册马里交叉验证最硬的一匹(mining.md「QQQ50×波动率目标」,
三票交叉验证 3/3,replay.py 的 `volreg` 同一公式):
  在场   QQQ 收在 50 日线上
  仓位   0.60 ÷ QBTS 20 日年化波动,夹在 20%~100%;红灯 → 0
  执行   每个交易日 15:52 ET(收盘前 8 分钟)按实时价算一次目标仓位,市价单调仓 ——
         回测口径是收盘执行,而 QBTS 的收益主体在隔夜跳空(核心事实 #4),次日开盘
         再买会把跳空让出去。仓位变动不足权益 10% 不动(每天微调只是白付点差)。
  止损   没有。这匹马的出场就是红灯;档案实测给反转/趋势马加止损都更差。
         它的风险控制是「波动越大仓位越小」和「大盘转弱就空仓」。

上线时写下的诚实预期(2026-09-18,yfinance 实算,0.2%/边成本):
  近 12 个月月均 −0.1%,月中位 −1.8%;12 个月里 3 个月 ≥+10%、6 个月亏损;
  规则定型(07-09)后至今 −31%,同期一直拿着 QBTS −23%。
  **没有证据支持「每月稳定赚钱」**。这是一个公开记账的实盘测试,不是印钞机。

记账:crypto_challenge 表 id='qbts1000'(零迁移);前端 /challenge 页直读。
  trades   每一笔买卖(时间/方向/股数/成交价/金额/原因/已实现盈亏)
  months   逐月:月初权益 → 月末权益、盈亏,对照同月一直拿着 QBTS 的涨跌
推送:买/卖/月报 → ntfy。
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_TABLE = "crypto_challenge"
_ROW = "qbts1000"
_SYM = "QBTS"
_START = 1000.0
_TARGET_VOL = 0.60          # 与 replay.volreg / exposure.py 同一常数
_W_MIN, _W_MAX = 0.20, 1.00
_REBAL_MIN = 0.10           # 目标与现仓相差 < 权益 10% → 不动
_RUN_FROM = (15, 52)        # ET;窗口 15:52–15:57,每天只成交一次(见 maybe_qbts_tick)
_RUN_TO = (15, 58)
_CURVE_CAP = 800            # 每交易日一点,够三年


def _sb():
    from dashboard.db import supabase
    return supabase()


def _load(sb) -> "dict | None":
    rows = sb.table(_TABLE).select("data").eq("id", _ROW).execute().data
    return rows[0]["data"] if rows and rows[0].get("data") else None


def _save(sb, st: dict) -> None:
    st["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sb.table(_TABLE).upsert({"id": _ROW, "data": st}).execute()


def _seed(now_et: datetime) -> dict:
    return {
        "status": "running", "started": now_et.date().isoformat(),
        "start_cap": _START,
        "cash": _START, "shares": 0, "avg_px": None,
        "equity": _START, "pnl": 0.0, "pnl_pct": 0.0,
        "rule": ("QQQ 在 50 日线上才持有 QBTS 正股;仓位 = 0.6 ÷ QBTS 20 日波动率(20%~100%);"
                 "每个交易日 15:52 ET 按实时价调仓,变动 <10% 不动;无止损,红灯即清仓。"),
        "trades": [], "months": {}, "equity_curve": [], "last_signal": None,
    }


def _ntfy(title: str, body: str, priority: str = "default", tags: str = "chart") -> None:
    try:
        from dashboard.notify import push
        push(title, body, tags=tags, priority=priority)
    except Exception as e:
        logger.warning(f"qbts_challenge ntfy failed: {e}")


# ── 信号:与 replay.volreg 同一公式,只是把今天的实时价当作收盘价 ────────────
def target_weight(qbts_px: float, qqq_px: float, today_et) -> dict:
    import numpy as np
    import yfinance as yf
    hist = {}
    for t in ("QBTS", "QQQ"):
        s = yf.download(t, period="6mo", interval="1d", progress=False,
                        auto_adjust=True)["Close"].squeeze().dropna()
        hist[t] = s[s.index.date < today_et]        # 只留已收盘的日线,今天用实时价补(按 ET 日期)
    q = list(hist["QQQ"].iloc[-49:]) + [qqq_px]
    ma50 = sum(q) / len(q)
    c = list(hist["QBTS"].iloc[-20:]) + [qbts_px]
    rets = np.diff(np.log(c))
    rv20 = float(np.std(rets, ddof=1) * math.sqrt(252))
    risk_on = qqq_px > ma50
    w = min(_W_MAX, max(_W_MIN, _TARGET_VOL / rv20)) if (risk_on and rv20 > 0) else 0.0
    return {"w": round(w, 3), "risk_on": bool(risk_on), "qqq": round(qqq_px, 2),
            "qqq_ma50": round(ma50, 2), "rv20": round(rv20, 3), "px": round(qbts_px, 3)}


# ── 下单:Alpaca paper 市价单,等成交价(复用 challenge2 的 REST 小工具)─────
def _order(side: str, qty: int) -> tuple[float | None, bool]:
    """返回 (成交均价, 是否真实成交价)。拿不到成交价时退回最新价并标记 approx。"""
    from dashboard.challenge2 import _req, _BASE, _latest_px
    o = _req("POST", f"{_BASE}/v2/orders", json={
        "symbol": _SYM, "qty": str(qty), "side": side,
        "type": "market", "time_in_force": "day"})
    oid = (o or {}).get("id")
    for _ in range(10):
        time.sleep(2)
        j = _req("GET", f"{_BASE}/v2/orders/{oid}") if oid else None
        if j and j.get("status") == "filled" and j.get("filled_avg_price"):
            return float(j["filled_avg_price"]), True
    return _latest_px(_SYM), False


def _roll_month(st: dict, now_et: datetime, px: float) -> None:
    """跨月:把上个月封账并推月报;给本月开账。"""
    key = now_et.strftime("%Y-%m")
    months = st.setdefault("months", {})
    if key in months:
        return
    for k, m in months.items():
        if m.get("end_equity") is None:
            m["end_equity"] = st["equity"]
            m["pnl"] = round(st["equity"] - m["start_equity"], 2)
            m["ret"] = round(m["pnl"] / m["start_equity"], 4)
            m["bh_ret"] = round(px / m["start_px"] - 1, 4) if m.get("start_px") else None
            vs = (f"\n同月一直拿着 QBTS:{m['bh_ret']*100:+.1f}% → "
                  f"{'✅ 跑赢' if m['ret'] > m['bh_ret'] else '❌ 跑输'}"
                  if m["bh_ret"] is not None else "")
            _ntfy("QBTS1000 monthly",
                  f"📅 {k} 月报:${m['start_equity']:,.2f} → ${m['end_equity']:,.2f}"
                  f"({m['pnl']:+,.2f} / {m['ret']*100:+.1f}%){vs}\n"
                  f"累计 ${st['equity']:,.2f}({st['pnl_pct']:+.1f}%)",
                  tags="calendar")
    months[key] = {"start_equity": st["equity"], "start_px": px, "end_equity": None,
                   "pnl": None, "ret": None, "bh_ret": None}


def maybe_qbts_tick(now_et: datetime, force: bool = False, dry: bool = False) -> "dict | None":
    """每个交易日 15:52–15:57 ET 窗口里跑**一次**。dry=True:只算不下单不写库。

    为什么是窗口不是单分钟:QuoteFunction 某一分钟可能整跳放弃(live_quote 读失败)
    或超时 —— 单分钟会整天漏掉。窗口 + `last_run` 日期标记 = 漏了下一分钟补,
    成功了当天不再动(Lambda 重试也不会重复下单)。"""
    if not force and not (now_et.weekday() < 5
                          and _RUN_FROM <= (now_et.hour, now_et.minute) < _RUN_TO):
        return None
    from dashboard.challenge2 import _keys_ok, _latest_px
    if not _keys_ok():
        return None
    sb = None if dry else _sb()
    if not dry and sb is None:
        return None

    st = (_load(sb) if sb else None) or _seed(now_et)
    if st.get("status") != "running":
        return {"status": st.get("status"), "noop": True}
    if not force and st.get("last_run") == now_et.date().isoformat():
        return None                                   # 今天已经跑过

    px, qqq = _latest_px(_SYM), _latest_px("QQQ")
    if not px or not qqq:
        return {"error": "no price"}
    st["equity"] = round(st["cash"] + st["shares"] * px, 2)
    if not dry:
        _roll_month(st, now_et, px)

    sig = target_weight(px, qqq, now_et.date())
    target_sh = int(sig["w"] * st["equity"] // px)
    delta = target_sh - st["shares"]
    trade = None
    if delta != 0 and (target_sh == 0 or abs(delta * px) >= _REBAL_MIN * st["equity"]):
        side = "buy" if delta > 0 else "sell"
        why = ("QQQ 跌回 50 日线下 → 清仓" if target_sh == 0 else
               "QQQ 站上 50 日线 → 建仓" if st["shares"] == 0 else
               f"波动率变化 → 仓位调到 {sig['w']:.0%}")
        if dry:
            fill, real = px, False
        else:
            fill, real = _order(side, abs(delta))
        fill = fill or px
        value = round(abs(delta) * fill, 2)
        realized = None
        if side == "buy":
            old = st["shares"] * (st["avg_px"] or 0)
            st["shares"] += delta
            st["cash"] = round(st["cash"] - value, 2)
            st["avg_px"] = round((old + value) / st["shares"], 4)
        else:
            realized = round((fill - (st["avg_px"] or fill)) * abs(delta), 2)
            st["shares"] += delta
            st["cash"] = round(st["cash"] + value, 2)
            if st["shares"] == 0:
                st["avg_px"] = None
        trade = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "date": now_et.date().isoformat(), "side": side, "qty": abs(delta),
                 "px": round(fill, 3), "value": value, "approx_px": not real,
                 "reason": why, "w": sig["w"], "realized": realized}
        st["trades"].append(trade)
        st["equity"] = round(st["cash"] + st["shares"] * px, 2)
        if not dry:
            _ntfy(f"QBTS1000 {side.upper()}",
                  f"{'🟢 买入' if side == 'buy' else '🔴 卖出'} {abs(delta)} 股 QBTS @ ${fill:.2f}"
                  f"(${value:,.2f})\n原因:{why}\n"
                  + (f"已实现 ${realized:+,.2f}\n" if realized is not None else "")
                  + f"持仓 {st['shares']} 股 · 现金 ${st['cash']:,.2f} · 权益 ${st['equity']:,.2f}\n"
                  f"(纸面挑战,非真金)",
                  tags="moneybag")

    st["pnl"] = round(st["equity"] - st["start_cap"], 2)
    st["pnl_pct"] = round(st["pnl"] / st["start_cap"] * 100, 2)
    st["last_signal"] = sig | {"date": now_et.date().isoformat(), "target_shares": target_sh}
    m = st.get("months", {}).get(now_et.strftime("%Y-%m"))
    if m:
        m["pnl_so_far"] = round(st["equity"] - m["start_equity"], 2)
        if m.get("start_px"):
            m["bh_so_far"] = round(px / m["start_px"] - 1, 4)
    curve = st.get("equity_curve") or []
    curve.append([now_et.date().isoformat(), st["equity"]])
    st["equity_curve"] = curve[-_CURVE_CAP:]
    st["last_run"] = now_et.date().isoformat()
    if not dry:
        _save(sb, st)
    return {"equity": st["equity"], "shares": st["shares"], "signal": sig, "trade": trade}


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    from zoneinfo import ZoneInfo
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parents[2] / ".env")
    print(json.dumps(maybe_qbts_tick(datetime.now(ZoneInfo("America/New_York")),
                                     force=True, dry=True), ensure_ascii=False, indent=2))
