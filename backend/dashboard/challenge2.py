"""
千元挑战 · 第二期 —— $5000 云端全自动(Alpaca paper,真实挂单纸面成交)。

第一期($1000→+$100,本地 bot,2026-07 达标 +10.7%)的升级复刻:
  资金   $5000 · 地板 −15%($4250)· 🏁 马拉松:跑到 2026-08-15(审判日)
         (2026-07-10 用户改规则:不再 +10% 判赢收手 —— $5500 只是里程碑,
         落袋后继续滚,到期看 $5000 变成多少)
  宇宙   challenge_basket 的全场 2×/3× 长腿杠杆 ETF 扫描(~40只,流动性门)
         —— 不再只看 4 只篮子;进场纪律一字不改:>50日线 + 近周涨,
         合格者中 20 日动量最强
  执行   空仓时进场:87% 仓位市价单 + GTC bracket(止盈备份 +11.5% /
         止损 −12%);每 15 分钟盯一次,浮盈触 +10% 即市价落袋
         (bracket 只是断电保险,「触碰即落袋」才是第一期的原味打法);
         平仓当日冷却(次日再进场 —— 否则落袋下一跳就原价买回,白付点差);
         触地板→全清停手;到期→全清结束。每跳把权益点记进 equity_curve
         (前端画资金曲线)。
  运行   AWS QuoteFunction(每分钟调度)里 minute%15==2 的分钟跑一跳
         (错开 %5==0 的 SMC 重算分钟,防超时)—— 电脑关机也照跑。
         订单挂在 Alpaca 服务端,Lambda 漏跳也不会丢止损。
  账务   sleeve 记账:纸面账户里只认本挑战的 $5000 口袋,和账户其他
         历史仓位隔离(同第一期口径)。
  推送   ENTER/CLOSED/WON/HALTED/到期 → ntfy(复用 NTFY_TOPIC);
         进场时可选一句 Haiku 点评进日志(有 ANTHROPIC_API_KEY 才调)。

状态写 Supabase crypto_challenge 表 id='current'(前端 /challenge 直读);
第一期原状态自动归档到 id='round1-2026-07'。纸面模拟,非投资建议。
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_TABLE = "crypto_challenge"
_ROW = "current"
_ARCHIVE_ROW = "round1-2026-07"

_START_CAP = 5000.0
_WIN_PCT = 0.10          # 里程碑线 = 本金 +10%(不收手,只报喜)
_FLOOR_PCT = 0.15        # 地板 = 本金 −15%(硬性停手,不动)
_SIZE_PCT = 0.87         # 单仓资金占比(第一期 869.70/1000 的口径)
_TP_TOUCH = 0.10         # 浮盈触碰即落袋
_TP_BACKSTOP = 0.115     # bracket 止盈限价(备份,略宽于落袋线)
_STOP_PCT = 0.12         # bracket 止损
_END_DATE = "2026-08-15"   # 马拉松终点 = 审判日
_CURVE_CAP = 2000          # equity_curve 最多点数(15min 一点,~26/交易日,富余)
_LAST_ENTRY_ET = (15, 30)  # 15:30 ET 后不再开新仓(只管已有仓)

_BASE = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
_DATA = "https://data.alpaca.markets"


# ── Alpaca REST(不依赖 alpaca-py,镜像零新增)────────────────────────────
def _keys_ok() -> bool:
    return bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY"))


def _req(method: str, url: str, **kw):
    import requests
    r = requests.request(method, url, timeout=20, headers={
        "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
        "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"],
    }, **kw)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json() if r.text else None


def _latest_px(sym: str) -> "float | None":
    try:
        j = _req("GET", f"{_DATA}/v2/stocks/{sym}/trades/latest")
        return float(j["trade"]["p"]) if j and j.get("trade") else None
    except Exception as e:
        logger.warning(f"challenge2: latest price {sym} failed — {e}")
        return None


# ── Supabase state ───────────────────────────────────────────────────────────
from dashboard.db import supabase as _sb   # 全仓共用一个客户端


def _load(sb) -> "dict | None":
    rows = sb.table(_TABLE).select("data").eq("id", _ROW).execute().data
    return rows[0]["data"] if rows and rows[0].get("data") else None


def _save(sb, st: dict) -> None:
    st["updated_at"] = _now_iso()
    sb.table(_TABLE).upsert({"id": _ROW, "data": st}).execute()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log(st: dict, line: str) -> None:
    st["history"] = (st.get("history") or [])[-79:] + [f"{_now_iso()}  {line}"]


def _ntfy(title: str, body: str, **kw) -> None:
    try:
        from dashboard.notify import push
        push(title, body, **kw)
    except Exception as e:
        logger.warning(f"challenge2 ntfy failed: {e}")


# ── 状态种子 & 归档 ──────────────────────────────────────────────────────────
def _seed(sb, old: "dict | None", now_et: datetime) -> dict:
    """归档第一期(如在)并写第二期初始状态。"""
    if old and old.get("round", 1) < 2:
        try:
            sb.table(_TABLE).upsert({"id": _ARCHIVE_ROW, "data": old}).execute()
        except Exception as e:
            logger.warning(f"challenge2: archive round1 failed — {e}")
    st = {
        "round": 2,
        "runner": "cloud",
        "status": "running",
        "marathon": True,
        "sleeve_start": _START_CAP,
        "sleeve_cash": _START_CAP,
        "equity": _START_CAP,
        "pnl": 0.0, "pnl_pct": 0.0,
        "peak_equity": _START_CAP,
        "win_line": round(_START_CAP * (1 + _WIN_PCT), 2),
        "floor_line": round(_START_CAP * (1 - _FLOOR_PCT), 2),
        "position": None,
        "basket": ["全场 2×/3× 杠杆ETF宇宙 ~40只", "门槛=50日线上+近周涨 · 押动量最强"],
        "deadline": _END_DATE,
        "equity_curve": [[_now_iso(), _START_CAP]],
        "odds_note": ("第二期规则与第一期同款(触碰即落袋),但宇宙从 4 只扩到全场"
                      "~40 只 —— 60% 触碰赔率未在这个宇宙校准过,本期就是在攒这个数据。"
                      "n=2 → n=3,纸面盘,非保证。"),
        "history": [],
        "updated_at": _now_iso(),
    }
    _log(st, f"🎬 第二期开局:本金 ${_START_CAP:,.0f},里程碑 ${st['win_line']:,.0f},"
             f"地板 ${st['floor_line']:,.0f},跑到 {st['deadline']}(云端 Lambda 全自动)")
    _save(sb, st)
    _ntfy("Challenge round 2 started",
          f"第二期开跑:$5,000 马拉松,跑到 {st['deadline']}\n"
          f"全场杠杆ETF宇宙 · 同款纪律 · 云端全自动(纸面盘)",
          tags="rocket", priority="default")
    return st


def _upgrade_to_marathon(st: dict) -> None:
    """就地升级已在跑的第二期:赢线收手 → 马拉松到 2026-08-15(用户 07-10 改规则)。"""
    st["marathon"] = True
    st["deadline"] = _END_DATE
    if not st.get("equity_curve"):
        start_ts = _now_iso()
        try:                                  # 起点回填到开局那条日志的时间戳
            start_ts = (st.get("history") or [""])[0].split("  ")[0] or start_ts
        except Exception:
            pass
        st["equity_curve"] = [[start_ts, _START_CAP]]
    _log(st, f"🏁 规则升级:取消 +10% 判赢收手 → 马拉松模式,持续交易到 {_END_DATE};"
             f"${st['win_line']:,.0f} 降为里程碑,地板 ${st['floor_line']:,.0f} 不变")


# ── 交易动作 ─────────────────────────────────────────────────────────────────
def _reconcile_close(st: dict, sym: str, fallback_px: "float | None",
                     now_et: datetime) -> None:
    """仓位没了/刚清仓 → 从已成交卖单回填 proceeds;找不到就用现价估算。"""
    qty = (st.get("position") or {}).get("qty") or 0
    invested = (st.get("position") or {}).get("invested") or 0.0
    proceeds = None
    try:
        orders = _req("GET", f"{_BASE}/v2/orders",
                      params={"status": "closed", "symbols": sym, "limit": 20,
                              "direction": "desc"}) or []
        for o in orders:
            if o.get("side") == "sell" and float(o.get("filled_qty") or 0) > 0:
                proceeds = float(o["filled_avg_price"]) * float(o["filled_qty"])
                break
    except Exception as e:
        logger.warning(f"challenge2: reconcile orders failed — {e}")
    approx = ""
    if proceeds is None and fallback_px:
        proceeds, approx = fallback_px * qty, "≈"
    if proceeds is None:
        proceeds, approx = invested, "≈?"
    pnl = proceeds - invested
    st["sleeve_cash"] = round(st["sleeve_cash"] + proceeds, 2)
    # 平仓当日冷却:马拉松模式下防止落袋下一跳就原价买回(白付点差)
    st["cooldown_date"] = now_et.date().isoformat()
    _log(st, f"CLOSED {sym} proceeds={approx}${proceeds:,.2f} pnl=${pnl:+,.2f}; "
             f"sleeve_cash=${st['sleeve_cash']:,.2f}(今日冷却,次日再进场)")
    _ntfy("Challenge position closed",
          f"平仓 {sym}:{'盈利' if pnl >= 0 else '亏损'} ${pnl:+,.2f}\n"
          f"口袋现金 ${st['sleeve_cash']:,.2f} / 本金 $5,000",
          tags=("moneybag" if pnl >= 0 else "small_red_triangle_down"))
    st["position"] = None


def _liquidate(st: dict, sym: str, why: str, now_et: datetime) -> None:
    """市价全清 + 撤 bracket 子单,然后回填账务。"""
    px = _latest_px(sym)
    try:
        _req("DELETE", f"{_BASE}/v2/positions/{sym}", params={"cancel_orders": "true"})
        time.sleep(3)   # 给市价单一点成交时间,好让 reconcile 拿到真实 fill
    except Exception as e:
        logger.warning(f"challenge2: liquidate {sym} failed — {e}")
    _log(st, f"LIQUIDATE {sym} @~${px or 0:,.2f} ({why})")
    _reconcile_close(st, sym, px, now_et)


def _ai_note(pick: dict) -> "str | None":
    """进场时一句 Haiku 点评(可选,失败静默)。"""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        msg = anthropic.Anthropic().messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=80,
            messages=[{"role": "user", "content":
                f"我按机械动量纪律买入了杠杆ETF {pick['ticker']}({pick.get('label','')}),"
                f"20日动量{pick['mom20']*100:+.0f}%、在50日线上、近一周{pick['week_ret']*100:+.1f}%。"
                f"用一句中文(<40字)点评这笔交易的主要风险,不要建议,不要套话。"}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.warning(f"challenge2 ai note failed: {e}")
        return None


def _try_enter(st: dict, now_et: datetime) -> None:
    """空仓 → 全场扫描 → 合格且有之选就 87% 市价 bracket 进场。"""
    if now_et.hour * 60 + now_et.minute >= _LAST_ENTRY_ET[0] * 60 + _LAST_ENTRY_ET[1]:
        return                                   # 尾盘不开新仓
    today = now_et.date().isoformat()
    if st.get("cooldown_date") == today:
        return                                   # 平仓当日不再进场
    # 大盘风向闸门(2026-07-21 三连亏复盘加:扫描器此前对大盘环境全盲,三笔全买
    # 在动量榜首却全撞上 risk_off 回撤 regime —— 复用 scan.py 同款判定,与自选扫描
    # 纸面台账同一条纪律:risk_off 时不逆势买"上升趋势"信号,宁可空仓等风向转)
    try:
        from dashboard.scan import _market_context
        mkt_ctx = _market_context()
    except Exception as e:
        mkt_ctx = None
        logger.warning(f"challenge2: market context failed — {e}")
    if mkt_ctx and mkt_ctx.get("regime") == "risk_off":
        if st.get("no_signal_date") != today:
            st["no_signal_date"] = today
            _log(st, f"SKIP 大盘 risk_off({mkt_ctx.get('note','')}) —— 按纪律空仓等风向转")
        return
    from dashboard.challenge_basket import analyze_challenge_basket
    scan = analyze_challenge_basket()
    mkt = (scan or {}).get("market") or {}
    pick_t = mkt.get("pick")
    if not pick_t:
        if st.get("no_signal_date") != today:    # 每天只记一次,防刷屏
            st["no_signal_date"] = today
            _log(st, f"SCAN 全场 {mkt.get('n_scanned', '?')} 只零合格 —— 按纪律空仓等待")
        return
    pick = next(e for e in mkt["top"] if e["ticker"] == pick_t)
    px = _latest_px(pick_t) or pick["close"]
    qty = int(st["sleeve_cash"] * _SIZE_PCT / px)
    if qty < 1:
        _log(st, f"SKIP {pick_t} 单价 ${px:,.2f} 超出仓位预算,跳过")
        return
    tp = round(px * (1 + _TP_BACKSTOP), 2)
    stop = round(px * (1 - _STOP_PCT), 2)
    coid = f"chal2-{now_et.strftime('%Y%m%d-%H%M')}"
    order = _req("POST", f"{_BASE}/v2/orders", json={
        "symbol": pick_t, "qty": str(qty), "side": "buy", "type": "market",
        "time_in_force": "gtc", "order_class": "bracket",
        "take_profit": {"limit_price": str(tp)},
        "stop_loss": {"stop_price": str(stop)},
        "client_order_id": coid,
    })
    cost = round(px * qty, 2)
    st["sleeve_cash"] = round(st["sleeve_cash"] - cost, 2)
    st["position"] = {
        "symbol": pick_t, "qty": qty, "entry_px": round(px, 2), "invested": cost,
        "tp_px": tp, "stop_px": stop, "order_id": (order or {}).get("id"),
        "entry_date": today,
    }
    _log(st, f"ENTER {pick_t} qty={qty} @~${px:,.2f} cost=${cost:,.2f} "
             f"BRACKET TP=${tp} STOP=${stop}(触碰+10%即落袋,bracket为备份)")
    note = _ai_note(pick)
    if note:
        _log(st, f"🤖 {note}")
    _ntfy("Challenge ENTER", (
        f"第二期进场:{pick_t}({pick.get('label','')})×{qty} @~${px:,.2f}\n"
        f"20日动量 {pick['mom20']*100:+.0f}% · TP ${tp} / STOP ${stop}\n"
        + (f"🤖 {note}" if note else "")).strip(), tags="dart")


def _finish(sb, st: dict, status: str, title: str, body: str, tags: str) -> None:
    st["status"] = status
    # 2026-07-21 复盘发现:halt/end 走这条早退路径,从没到过下面主循环里的 pnl 重算行,
    # 导致停手那一刻显示的 pnl 是上一跳的旧值、对不上最终 equity —— 这里补算一次。
    st["pnl"] = round(st["equity"] - _START_CAP, 2)
    st["pnl_pct"] = round(st["pnl"] / _START_CAP * 100, 1)
    curve = st.get("equity_curve") or []
    curve.append([_now_iso(), st["equity"]])          # 曲线收个尾
    st["equity_curve"] = curve[-_CURVE_CAP:]
    _log(st, f"{'🏆' if status == 'won' else '🛑' if status == 'halted' else '⏱'} "
             f"{title} final equity=${st['equity']:,.2f}")
    _save(sb, st)
    _ntfy(f"Challenge {status.upper()}", body,
          tags=tags, priority="high" if status == "won" else "default")


# ── 主入口:QuoteFunction 每分钟调,自己挑 minute%15==2 的分钟干活 ─────────
def maybe_challenge_tick(now_et: datetime, force: bool = False) -> "dict | None":
    """一跳:对账→(触线全清/判赢/停手/到期)→空仓则找进场。返回摘要或 None。"""
    if not _keys_ok():
        return None
    in_session = (now_et.weekday() < 5
                  and (9, 30) <= (now_et.hour, now_et.minute) < (16, 0))
    if not force and (not in_session or now_et.minute % 15 != 2):
        return None
    sb = _sb()
    if sb is None:
        return None

    st = _load(sb)
    if st is None or st.get("round", 1) < 2:
        st = _seed(sb, st, now_et)
    if st.get("status") != "running":
        return {"status": st.get("status"), "noop": True}
    if not st.get("marathon"):
        _upgrade_to_marathon(st)

    sym = (st.get("position") or {}).get("symbol")
    pos = None
    if sym:
        try:
            pos = _req("GET", f"{_BASE}/v2/positions/{sym}")
        except Exception as e:
            logger.warning(f"challenge2: position fetch failed — {e}")
            _save(sb, st)
            return {"status": "running", "error": "position fetch failed"}
        if pos is None:                       # bracket 在两跳之间自己成交了
            _reconcile_close(st, sym, _latest_px(sym), now_et)
            sym, pos = None, None

    # ── 有仓:更新市值,触线处理 ──
    if pos is not None:
        mv = float(pos["market_value"])
        entry_val = st["position"]["invested"]
        unreal = mv - entry_val
        st["position"].update({
            "cur_px": round(float(pos["current_price"]), 2),
            "unreal": round(unreal, 2),
        })
        st["equity"] = round(st["sleeve_cash"] + mv, 2)
        if unreal / entry_val >= _TP_TOUCH:
            _liquidate(st, sym, f"触碰 +{_TP_TOUCH*100:.0f}% 落袋", now_et)
        elif st.get("floor_line") is not None and st["equity"] <= st["floor_line"]:
            _liquidate(st, sym, f"权益触地板 ${st['floor_line']:,.0f}", now_et)

    # ── 空仓:到期/判定/进场 ──
    if st.get("position") is None:
        st["equity"] = st["sleeve_cash"]
        # floor_line=None(2026-07-21 用户复盘后拍板取消地板,跑到期)→ 跳过此闸
        if st.get("floor_line") is not None and st["equity"] <= st["floor_line"]:
            _finish(sb, st, "halted", "CHALLENGE HALTED.",
                    f"🛑 第二期触地板停手:${st['equity']:,.2f}", "octagonal_sign")
            return {"status": "halted"}
        if now_et.date().isoformat() > st["deadline"]:
            _finish(sb, st, "ended", "CHALLENGE ENDED (deadline).",
                    f"⏱ 第二期到期:${st['equity']:,.2f}"
                    f"({(st['equity']/_START_CAP-1)*100:+.1f}%)", "checkered_flag")
            return {"status": "ended"}
        try:
            _try_enter(st, now_et)
        except Exception as e:
            logger.warning(f"challenge2: entry failed — {e}")
            _log(st, f"⚠️ 进场失败:{type(e).__name__}: {str(e)[:80]}")
    else:
        # 持仓过期日到点也要清(到期日收盘前最后一跳自然会走到这里的下一跳)
        if now_et.date().isoformat() > st["deadline"]:
            _liquidate(st, sym, "到期全清", now_et)
            st["equity"] = st["sleeve_cash"]
            _finish(sb, st, "ended", "CHALLENGE ENDED (deadline).",
                    f"⏱ 第二期到期:${st['equity']:,.2f}"
                    f"({(st['equity']/_START_CAP-1)*100:+.1f}%)", "checkered_flag")
            return {"status": "ended"}

    st["pnl"] = round(st["equity"] - _START_CAP, 2)
    st["pnl_pct"] = round(st["pnl"] / _START_CAP * 100, 1)
    st["peak_equity"] = round(max(st.get("peak_equity", _START_CAP), st["equity"]), 2)

    # ── 里程碑:首次踩上 +10% 线报个喜,但不收手(马拉松跑到 8/15)──
    if st["equity"] >= st["win_line"] and not st.get("milestone_at"):
        st["milestone_at"] = _now_iso()
        _log(st, f"🏆 里程碑:权益 ${st['equity']:,.2f} 首次站上 ${st['win_line']:,.0f}"
                 f"(+10%)—— 马拉松继续,跑到 {st['deadline']}")
        _ntfy("Challenge milestone +10%",
              f"🏆 第二期权益 ${st['equity']:,.2f},首次 +10%!\n"
              f"马拉松模式不收手 —— 继续滚到 {st['deadline']},看 $5,000 变成多少",
              tags="trophy", priority="default")

    # ── 资金曲线:每跳一点(15min 粒度,前端画 line chart)──
    curve = st.get("equity_curve") or []
    curve.append([_now_iso(), st["equity"]])
    st["equity_curve"] = curve[-_CURVE_CAP:]

    _save(sb, st)
    return {"status": "running", "equity": st["equity"],
            "position": (st.get("position") or {}).get("symbol")}
