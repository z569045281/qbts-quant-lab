"""
Storage for the watchlist scan (Supabase when creds present, local-file fallback):

  watchlist     the editable list of tickers the scan covers (single row 'current')
  scan_journal  a track record — every day's per-ticker call, graded after N trading
                days, so the scan is FALSIFIABLE ("when it says 买入区, does it work?")
  scan_paper    a $1000-per-signal PAPER-TRADING ledger — buy on 买入区, hold until a
                sell signal, record realized P&L, so we can show "would the signals
                have made money?" in actual dollars.

All single-row jsonb tables (small), mirroring the journal/calibration pattern so
they survive stateless cloud (Lambda /tmp) runs. Backend-only — never read by the
anon frontend (the scan payload carries the summary the UI needs).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd


def _utc_now() -> str:
    """upsert 时显式刷新 updated_at —— DEFAULT now() 只管 INSERT。"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

logger = logging.getLogger(__name__)

_DIR = Path(__file__).parent.parent / "data" / "cache"
_DIR.mkdir(parents=True, exist_ok=True)
_WATCH_FILE    = _DIR / "watchlist.json"
_JOURNAL_FILE  = _DIR / "scan_journal.json"
_PAPER_FILE    = _DIR / "scan_paper.json"

_WATCH_TABLE   = "watchlist"
_JOURNAL_TABLE = "scan_journal"
_PAPER_TABLE   = "scan_paper"
_GRADE_AFTER   = 5      # grade a scan call after this many trading days
_MAX_RECORDS   = 800    # cap journal size (rolling)
_TRADE_USD     = 1000.0 # paper-trade size per buy signal
_COST_PER_SIDE = 0.002  # ~0.2%/side (spread+commission) on these high-vol names
_MAX_CLOSED    = 200    # cap closed-trade ledger (rolling)
_STOP_VOL_MULT = 2.0          # paper stop ≈ this × recent daily vol …
_STOP_MIN, _STOP_MAX = 0.06, 0.14   # … clamped to [6%, 14%]


def _stop_pct(vol_annual) -> float:
    """Volatility-scaled paper stop (fraction). ≈2× daily vol, clamped 6–14%, so
    normal 1-day noise on these 2× names doesn't whipsaw the trade out, but a real
    breakdown is still capped. Replaces the old 'sell on any MA-break' UI hint,
    which stopped trades the same day they were opened (bought >20MA / closed <50MA)."""
    if not isinstance(vol_annual, (int, float)) or vol_annual <= 0:
        return 0.10
    daily = vol_annual / (252 ** 0.5)
    return min(max(_STOP_VOL_MULT * daily, _STOP_MIN), _STOP_MAX)


from dashboard.db import supabase as _supabase   # 全仓共用一个客户端


# ── single-row jsonb helpers ──────────────────────────────────────────────────
def _load_row(table: str, file: Path) -> dict | None:
    sb = _supabase()
    if sb is not None:
        try:
            rows = sb.table(table).select("data").eq("id", "current").execute().data
            return rows[0]["data"] if rows and rows[0].get("data") else None
        except Exception as e:
            logger.warning(f"scan_store: load {table} failed, using file — {e}")
    if file.exists():
        try:
            return json.loads(file.read_text())
        except Exception:
            return None
    return None


def _save_row(table: str, file: Path, data: dict) -> None:
    sb = _supabase()
    if sb is not None:
        try:
              # 2026-08-05:显式带上 updated_at。upsert 只写 `data`,而 `updated_at` 的
            # DEFAULT now() **只在 INSERT 时生效** —— 这一行 id="current" 从建表那天
            # 起就没变过,导致任何拿 updated_at 判新鲜度的人(含 Claude 自己,08-05
            # 排查 PublishFunction 时就被骗过)会看到一个 42 天没更新的假象,
            # 而 data.generated_at 其实每天都在动。监控字段本身骗人比没有更糟。
            sb.table(table).upsert({"id": "current", "data": data, "updated_at": _utc_now()}).execute()
            return
        except Exception as e:
            logger.warning(f"scan_store: save {table} failed, using file — {e}")
    file.write_text(json.dumps(data, ensure_ascii=False))


# ── watchlist ─────────────────────────────────────────────────────────────────
def _norm(tickers: list[str]) -> list[str]:
    out = []
    for t in tickers:
        t = (t or "").strip().upper()
        if t and t not in out:
            out.append(t)
    return out


def load_watchlist(default: list[str]) -> list[str]:
    row = _load_row(_WATCH_TABLE, _WATCH_FILE)
    if row and row.get("tickers"):
        return _norm(row["tickers"])
    return list(default)


def save_watchlist(tickers: list[str]) -> list[str]:
    tickers = _norm(tickers)
    _save_row(_WATCH_TABLE, _WATCH_FILE, {"tickers": tickers})
    return tickers


def add_ticker(ticker: str, default: list[str]) -> list[str]:
    wl = load_watchlist(default)
    t = (ticker or "").strip().upper()
    if t and t not in wl:
        wl.append(t)
    return save_watchlist(wl)


def remove_ticker(ticker: str, default: list[str]) -> list[str]:
    t = (ticker or "").strip().upper()
    return save_watchlist([x for x in load_watchlist(default) if x != t])


# ── scan journal (track record) ───────────────────────────────────────────────
def _load_journal() -> list[dict]:
    row = _load_row(_JOURNAL_TABLE, _JOURNAL_FILE)
    return (row or {}).get("records", []) if row else []


def _save_journal(records: list[dict]) -> None:
    _save_row(_JOURNAL_TABLE, _JOURNAL_FILE, {"records": records[-_MAX_RECORDS:]})


def grade_and_record(results: list[dict], dfs: dict[str, pd.DataFrame]) -> None:
    """One read-modify-write: grade all pending calls old enough, then append
    today's calls (replacing any same-day pending for these tickers).

    Grading uses each ticker's daily closes:
      买入区/接近买点 (bullish lean) → correct if +N-day return > 0
      偏空回避        (bearish)      → correct if return < 0
      观望            (no lean)      → informational (correct = None)
    """
    recs = _load_journal()
    today = datetime.now().strftime("%Y-%m-%d")

    # build per-ticker close maps once
    cmaps: dict[str, pd.Series] = {}
    for t, df in dfs.items():
        if df is None or df.empty:
            continue
        s = pd.Series(df["close"].values, index=pd.DatetimeIndex(df.index).normalize())
        cmaps[t] = s[~s.index.duplicated(keep="last")].sort_index()

    for r in recs:
        if r.get("status") != "pending":
            continue
        cmap = cmaps.get(r.get("ticker"))
        if cmap is None:
            continue
        try:
            d0 = pd.Timestamp(r["date"]).normalize()
        except Exception:
            continue
        after = cmap.index[cmap.index > d0]
        anchor = cmap.index[cmap.index <= d0]
        if len(after) < _GRADE_AFTER or len(anchor) == 0:
            continue
        p0 = float(cmap.loc[anchor[-1]])
        p1 = float(cmap.loc[after[_GRADE_AFTER - 1]])
        if p0 <= 0:
            continue
        ret = (p1 - p0) / p0
        stance = r.get("stance")
        if stance in ("买入区", "接近买点"):
            correct = ret > 0
        elif stance == "偏空回避":
            correct = ret < 0
        else:
            correct = None
        r["status"] = "graded"
        r["result"] = {"ret": round(ret, 4), "correct": correct, "graded_at": today}

    # append today's calls (idempotent: replace same-day pending for these tickers)
    tickers = {x["ticker"] for x in results if not x.get("error")}
    recs = [r for r in recs
            if not (r.get("date") == today and r.get("ticker") in tickers and r.get("status") == "pending")]
    for x in results:
        if x.get("error"):
            continue
        recs.append({
            "id":     f"{x['ticker']}:{today}",
            "ticker": x["ticker"],
            "date":   today,
            "stance": x.get("stance"),
            "score":  x.get("score"),
            "price":  x.get("price"),
            "status": "pending",
            "result": None,
        })
    _save_journal(recs)


# ── paper-trading sim ($1000 per buy signal → does the scan make money?) ─────────
def _load_paper() -> dict:
    row = _load_row(_PAPER_TABLE, _PAPER_FILE)
    return {"positions": (row or {}).get("positions", {}),
            "closed":    (row or {}).get("closed", []),
            "pending":   (row or {}).get("pending", {})}


def _save_paper(state: dict) -> None:
    _save_row(_PAPER_TABLE, _PAPER_FILE, {
        "positions": state.get("positions", {}),
        "closed":    state.get("closed", [])[-_MAX_CLOSED:],
        "pending":   state.get("pending", {}),
    })


def _bdays(d0: str, d1: str) -> int:
    try:
        return max(int(pd.bdate_range(d0, d1).size) - 1, 0)
    except Exception:
        return 0


_PENDING_DAYS = 5   # 回踩限价单有效期(交易日),不触价过期撤单


def run_paper_trades(results: list[dict], market_regime: str | None = None,
                     dfs: "dict[str, pd.DataFrame] | None" = None) -> dict:
    """$1000 paper trade per buy signal — **v2 (2026-07-10 机制修订,epoch 划线)**。

    v1 的两个结构性 bug(首月账本 −$226 的主因):①卡片说"回踩需求区分批买",
    模拟器却当日收盘追入——买在信号日高点,被正常回踩打掉止损;②目标取"最近
    参照"能近到 +0.4% 而止损 7–14%,盈亏比天生是倒的。v2 改成执行卡片自己的打法:

      进场  买入区信号 → 现价已在买点(≤entry_limit×1.005 或无可表达买点)当日
            收盘进场;否则在需求区上沿挂回踩限价单,_PENDING_DAYS 个交易日内
            触价成交(按当日 min(open, limit),跳空低开按开盘成交),过期撤单,
            转偏空回避立即撤单。目标已在 scan.py 过 1.5R 盈亏比门(不合格=None)。
      出场  入场锚定的波动止损 | 转空 | 到目标止盈 |
            无目标仓位(突破票/盈亏比veto)收盘破 10 日线跟踪出场。

    新仓位/成交记 epoch='v2';v1 老仓位继续按新出场规则跑完,账本不清零,
    审判时按 epoch 分开统计。"""
    state = _load_paper()
    positions: dict = state["positions"]
    closed: list = state["closed"]
    pending: dict = state.get("pending", {})
    today = datetime.now().strftime("%Y-%m-%d")
    cards = {r["ticker"]: r for r in results if not r.get("error")}
    dfs = dfs or {}

    # ── ① 挂单结算:回看挂单日之后的日线,触价成交 / 过期或转空撤单 ──
    for t in list(pending):
        po = pending[t]
        card = cards.get(t)
        if t in positions:
            pending.pop(t); continue
        if card and card.get("stance") == "偏空回避":
            pending.pop(t); continue                     # 信号翻空,撤单
        df = dfs.get(t)
        if df is None or df.empty or not {"open", "low"}.issubset(df.columns):
            continue                                     # 数据缺,挂单原样保留
        try:
            d0 = pd.Timestamp(po["placed_date"]).normalize()
        except Exception:
            pending.pop(t); continue
        idx = pd.DatetimeIndex(df.index).normalize()
        bars = df[idx > d0]
        filled = False
        for i, (ts, row) in enumerate(bars.iterrows()):
            if i >= _PENDING_DAYS:
                break
            if float(row["low"]) <= po["limit"]:
                fill = min(float(row["open"]), po["limit"])   # 跳空低开按开盘价成交
                sp = po.get("stop_pct") or _stop_pct((card or {}).get("vol_annual"))
                positions[t] = {
                    "entry_date": str(pd.Timestamp(ts).date()),
                    "entry_price": round(fill, 2),
                    "shares": round(_TRADE_USD * (1 - _COST_PER_SIDE) / fill, 4),
                    "cost": _TRADE_USD,
                    "target": po.get("target"),
                    "stop_price": round(fill * (1 - sp), 2), "stop_pct": round(sp, 4),
                    "epoch": "v2", "limit_fill": True,
                }
                filled = True
                break
        if filled or len(bars) >= _PENDING_DAYS:
            pending.pop(t, None)                         # 已成交 / 过期撤单

    # ── ② 持仓出场 + ③ 新信号进场/挂单 ──
    for r in results:
        if r.get("error"):
            continue
        t, price = r.get("ticker"), r.get("price")
        if not t or not isinstance(price, (int, float)) or price <= 0:
            continue
        stance = r.get("stance")

        if t in positions:                                   # holding → maybe exit
            pos = positions[t]
            if pos.get("entry_date") == today:               # just entered; no same-day flip
                continue
            sp_price = pos.get("stop_price") or round(
                pos["entry_price"] * (1 - _stop_pct(r.get("vol_annual"))), 2)
            tgt = pos.get("target")
            hit_target = isinstance(tgt, (int, float)) and tgt > 0 and price >= tgt
            # 无目标仓位(突破票/盈亏比veto)的跟踪出场:收盘破 10 日线
            trail_break = False
            if not (isinstance(tgt, (int, float)) and tgt > 0):
                df = dfs.get(t)
                if df is not None and len(df) >= 10:
                    sma10 = float(df["close"].rolling(10).mean().iloc[-1])
                    trail_break = price < sma10
            reason = ("止损"        if price <= sp_price
                      else "转空"    if stance == "偏空回避"
                      else "到目标止盈" if hit_target
                      else "破10日线跟踪出场" if trail_break
                      else None)
            if reason:
                positions.pop(t)
                proceeds = pos["shares"] * price * (1 - _COST_PER_SIDE)   # sell-side cost
                pnl = proceeds - pos["cost"]
                closed.append({
                    "ticker": t, "theme": r.get("theme"),
                    "entry_date": pos["entry_date"], "entry_price": pos["entry_price"],
                    "exit_date": today, "exit_price": round(price, 2),
                    "shares": pos["shares"], "cost": pos["cost"],
                    "pnl": round(pnl, 2), "pnl_pct": round(pnl / pos["cost"], 4),
                    "reason": reason, "days": _bdays(pos["entry_date"], today),
                    "epoch": pos.get("epoch", "v1"),
                    # 2026-07-24 审判器修订配套:落账单笔风险距,审判期望R用
                    # (R = pnl_pct/stop_pct);老记录无此字段 → 不进R统计。
                    "stop_pct": pos.get("stop_pct"),
                })
        elif stance == "买入区" and not r.get("thin_data") and t not in pending:
            if market_regime == "risk_off":                  # tape filter: don't fight a selloff
                continue
            sp = _stop_pct(r.get("vol_annual"))
            limit = r.get("entry_limit")
            if isinstance(limit, (int, float)) and limit > 0 and price > limit * 1.005:
                # 现价还没回到买点 → 照卡片打法挂回踩限价单,而不是追价
                pending[t] = {"placed_date": today, "limit": round(float(limit), 2),
                              "target": r.get("target_num"),
                              "stop_pct": round(sp, 4), "signal_price": round(price, 2)}
            else:
                # 已在买点之内(或无可表达的回踩参照)→ 当日收盘进场
                positions[t] = {"entry_date": today, "entry_price": round(price, 2),
                                "shares": round(_TRADE_USD * (1 - _COST_PER_SIDE) / price, 4),
                                "cost": _TRADE_USD,
                                "target": r.get("target_num"),          # 已过 1.5R 门
                                "stop_price": round(price * (1 - sp), 2), "stop_pct": round(sp, 4),
                                "epoch": "v2"}

    _save_paper({"positions": positions, "closed": closed, "pending": pending})

    # ── display summary with live unrealized P&L (today's prices) ──
    px = {r["ticker"]: r.get("price") for r in results if not r.get("error")}
    open_rows, unreal = [], 0.0
    for t, pos in positions.items():
        cur = px.get(t) or pos["entry_price"]
        u = pos["shares"] * cur - pos["cost"]
        unreal += u
        open_rows.append({
            "ticker": t, "theme": next((r.get("theme") for r in results if r.get("ticker") == t), None),
            "entry_date": pos["entry_date"], "entry_price": pos["entry_price"],
            "current_price": round(cur, 2), "pnl": round(u, 2),
            "pnl_pct": round(u / pos["cost"], 4), "days": _bdays(pos["entry_date"], today),
        })
    open_rows.sort(key=lambda x: -x["pnl"])
    realized = sum(c["pnl"] for c in closed)
    n_win = sum(1 for c in closed if c["pnl"] > 0)
    pending_rows = [{
        "ticker": t, "limit": po.get("limit"), "placed_date": po.get("placed_date"),
        "signal_price": po.get("signal_price"), "target": po.get("target"),
    } for t, po in pending.items()]
    return {
        "trade_usd": _TRADE_USD,
        "open": open_rows,
        "pending": pending_rows,
        "closed": list(reversed(closed))[:30],          # newest first
        "totals": {
            "realized": round(realized, 2), "unrealized": round(unreal, 2),
            "total": round(realized + unreal, 2),
            "n_open": len(open_rows),
            "invested_open": round(sum(p["cost"] for p in positions.values()), 2),
            "n_closed": len(closed), "n_win": n_win,
            "win_rate": round(n_win / len(closed), 3) if closed else None,
        },
    }


def publish_scan() -> dict:
    """Run the scan and upsert it to the watchlist_scan table. Shared by the daily
    publish (local + Lambda) and live watchlist edits. Returns the scan payload."""
    from dashboard.scan import scan_watchlist
    payload = scan_watchlist()
    sb = _supabase()
    if sb is not None:
        try:
            safe = json.loads(json.dumps(payload, default=str),
                              parse_constant=lambda _c: None)   # NaN/Inf → null
            sb.table("watchlist_scan").upsert({"id": "current", "data": safe, "updated_at": _utc_now()}).execute()
        except Exception as e:
            logger.warning(f"publish_scan write failed: {e}")
    return payload


def scan_summary() -> dict:
    """Hit rates of graded directional calls (buy-leaning + avoid), per ticker + overall."""
    recs = _load_journal()
    graded = [r for r in recs if r.get("status") == "graded"
              and r.get("result") and r["result"].get("correct") is not None]
    by_ticker: dict[str, list[int]] = {}   # ticker -> [correct, n]
    for r in graded:
        t = r["ticker"]
        by_ticker.setdefault(t, [0, 0])
        by_ticker[t][1] += 1
        if r["result"]["correct"]:
            by_ticker[t][0] += 1
    per = {t: {"n": n, "correct": c, "hit_rate": round(c / n, 3) if n else None}
           for t, (c, n) in by_ticker.items()}
    tot_c = sum(c for c, n in by_ticker.values())
    tot_n = sum(n for c, n in by_ticker.values())
    return {
        "overall": {"n": tot_n, "correct": tot_c,
                    "hit_rate": round(tot_c / tot_n, 3) if tot_n else None},
        "by_ticker": per,
    }
