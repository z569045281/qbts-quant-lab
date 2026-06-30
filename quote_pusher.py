#!/usr/bin/env python3
"""
Live quote pusher — runs 24/7 on any spare machine.

Every ~60s during US trading hours (incl. pre/post) it fetches QBTS / QBTX /
QBTZ quotes via yfinance and upserts one row into Supabase `live_quote`.
The deployed dashboard polls that row for a near-real-time price header.

Setup on a fresh machine:
    1. python3 -m venv venv && venv/bin/pip install yfinance supabase python-dotenv
    2. copy .env with SUPABASE_URL (or NEXT_PUBLIC_SUPABASE_URL) + SUPABASE_SECRET_KEY
    3. venv/bin/python quote_pusher.py            # loop forever
       venv/bin/python quote_pusher.py --once     # single push (testing)

Cadence (gentle on Yahoo, fresh where it matters):
    pre/regular/post session : every 60s
    overnight / weekend      : every 10 min (keeps prev-close row fresh)
"""

from __future__ import annotations

import os
import sys
import time
import warnings
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

warnings.filterwarnings("ignore")
load_dotenv()

ET = ZoneInfo("America/New_York")
TICKERS = ["QBTS", "QBTX", "QBTZ"]


def us_session(now_et: datetime) -> str:
    """closed | pre | regular | post (US equities, ET)."""
    if now_et.weekday() >= 5:
        return "closed"
    hm = now_et.hour * 60 + now_et.minute
    if 4 * 60 <= hm < 9 * 60 + 30:
        return "pre"
    if 9 * 60 + 30 <= hm < 16 * 60:
        return "regular"
    if 16 * 60 <= hm < 20 * 60:
        return "post"
    return "closed"


def fetch_quote(symbol: str) -> dict | None:
    """Last traded price incl. extended hours + previous regular close."""
    import yfinance as yf
    t = yf.Ticker(symbol)
    price = None
    bar_time = None
    try:
        # 1-minute bars with prepost give the freshest extended-hours print
        h = t.history(period="1d", interval="1m", prepost=True)
        if len(h) > 0:
            price = float(h["Close"].iloc[-1])
            bar_time = h.index[-1].isoformat()
    except Exception:
        pass
    if price is None:
        try:
            price = float(t.fast_info.last_price)
        except Exception:
            return None
    try:
        prev_close = float(t.fast_info.previous_close)
    except Exception:
        prev_close = None
    chg = (price / prev_close - 1) if prev_close else None
    return {
        "price":      round(price, 4),
        "prev_close": round(prev_close, 4) if prev_close else None,
        "change_pct": round(chg, 6) if chg is not None else None,
        "bar_time":   bar_time,
    }


def build_payload() -> dict:
    now_et = datetime.now(ET)
    quotes = {}
    for sym in TICKERS:
        q = fetch_quote(sym)
        if q:
            quotes[sym.lower()] = q
    return {
        "session":    us_session(now_et),
        "asof_et":    now_et.strftime("%Y-%m-%d %H:%M:%S"),
        "asof_epoch": int(time.time()),
        "quotes":     quotes,
    }


def get_supabase():
    from supabase import create_client
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SECRET_KEY")
    if not url or not key:
        sys.exit("✗ .env 缺少 SUPABASE_URL / SUPABASE_SECRET_KEY")
    return create_client(url, key)


def push_payload(sb, payload: dict) -> dict:
    """Upsert a pre-built payload into the live_quote row (id=1)."""
    sb.table("live_quote").upsert(
        {"id": 1, "updated_at": datetime.utcnow().isoformat() + "Z", "data": payload}
    ).execute()
    return payload


def push_once(sb) -> dict:
    """Build + push a quote payload. The local loop uses this lean path; the
    cloud QuoteFunction builds the payload itself so it can attach the intraday
    SMC playbook before upserting (see aws/lambda_handlers.quote_handler)."""
    return push_payload(sb, build_payload())


def main() -> None:
    sb = get_supabase()
    once = "--once" in sys.argv

    while True:
        try:
            p = push_once(sb)
            q = p["quotes"].get("qbts", {})
            chg = q.get("change_pct")
            chg_s = f"{chg*100:+.2f}%" if chg is not None else "—"
            print(f"[{p['asof_et']} ET / {p['session']:7s}] "
                  f"QBTS ${q.get('price','—')} ({chg_s})  "
                  f"QBTX ${p['quotes'].get('qbtx',{}).get('price','—')}  "
                  f"QBTZ ${p['quotes'].get('qbtz',{}).get('price','—')}", flush=True)
        except Exception as e:
            print(f"! push failed: {type(e).__name__}: {str(e)[:140]}", flush=True)

        if once:
            break
        session = us_session(datetime.now(ET))
        time.sleep(60 if session != "closed" else 600)


if __name__ == "__main__":
    main()
