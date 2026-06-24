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
_MAX_CLOSED    = 200    # cap closed-trade ledger (rolling)

_SB = None
_SB_INIT = False


def _supabase():
    global _SB, _SB_INIT
    if _SB_INIT:
        return _SB
    _SB_INIT = True
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if url and key:
        try:
            from supabase import create_client
            _SB = create_client(url, key)
        except Exception as e:
            logger.warning(f"scan_store: Supabase init failed, using files — {e}")
            _SB = None
    return _SB


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
            sb.table(table).upsert({"id": "current", "data": data}).execute()
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
            "closed":    (row or {}).get("closed", [])}


def _save_paper(state: dict) -> None:
    _save_row(_PAPER_TABLE, _PAPER_FILE, {
        "positions": state.get("positions", {}),
        "closed":    state.get("closed", [])[-_MAX_CLOSED:],
    })


def _bdays(d0: str, d1: str) -> int:
    try:
        return max(int(pd.bdate_range(d0, d1).size) - 1, 0)
    except Exception:
        return 0


def run_paper_trades(results: list[dict]) -> dict:
    """$1000 paper trade per buy signal, held until a sell signal; records realized P&L.

      Buy  = stance 买入区 (and not already holding).
      Sell = 偏空回避(转空) | exit_hint profit(到目标止盈) | exit_hint risk(跌破均线止损).

    One position per ticker at a time; entry/exit at the scan-day close. Persists the
    ledger to scan_paper and returns a display summary with live unrealized P&L."""
    state = _load_paper()
    positions: dict = state["positions"]
    closed: list = state["closed"]
    today = datetime.now().strftime("%Y-%m-%d")

    for r in results:
        if r.get("error"):
            continue
        t, price = r.get("ticker"), r.get("price")
        if not t or not isinstance(price, (int, float)) or price <= 0:
            continue
        stance = r.get("stance")
        kind = (r.get("exit_hint") or {}).get("kind")

        if t in positions:                                   # holding → maybe exit
            pos = positions[t]
            if pos.get("entry_date") == today:               # just entered; no same-day flip
                continue
            reason = ("转空"         if stance == "偏空回避"
                      else "到目标止盈"  if kind == "profit"
                      else "跌破均线止损" if kind == "risk"
                      else None)
            if reason:
                positions.pop(t)
                pnl = pos["shares"] * price - pos["cost"]
                closed.append({
                    "ticker": t, "theme": r.get("theme"),
                    "entry_date": pos["entry_date"], "entry_price": pos["entry_price"],
                    "exit_date": today, "exit_price": round(price, 2),
                    "shares": pos["shares"], "cost": pos["cost"],
                    "pnl": round(pnl, 2), "pnl_pct": round(pnl / pos["cost"], 4),
                    "reason": reason, "days": _bdays(pos["entry_date"], today),
                })
        elif stance == "买入区":                              # flat → enter
            positions[t] = {"entry_date": today, "entry_price": round(price, 2),
                            "shares": round(_TRADE_USD / price, 4), "cost": _TRADE_USD}

    _save_paper({"positions": positions, "closed": closed})

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
    return {
        "trade_usd": _TRADE_USD,
        "open": open_rows,
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
            sb.table("watchlist_scan").upsert({"id": "current", "data": safe}).execute()
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
