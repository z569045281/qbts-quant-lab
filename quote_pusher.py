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
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

warnings.filterwarnings("ignore")
load_dotenv()

ET = ZoneInfo("America/New_York")
TICKERS = ["QBTS", "QBTX", "QBTZ"]

# 🌙 Blue Ocean 夜盘:yfinance 的 prepost 只到盘后 20:00 ET,夜盘(20:00–04:00 ET)
# 全盲——这正是用户在 moomoo 夜盘下单时仪表盘变黑的盲区。Alpaca 的 `overnight`
# feed(免费档即可,key 已部署)吐 Blue Ocean 实时成交/盘口。以 QBTS 最新成交的
# 新鲜度判定"夜盘此刻是否真的在交易"——≤此秒数内有成交才算活跃,否则(假日夜/
# 周六)退回昨收显示,不硬套时钟窗。
_ALPACA_DATA = "https://data.alpaca.markets/v2/stocks"
_OVERNIGHT_FRESH_S = 20 * 60


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


def _overnight_window(now_et: datetime) -> bool:
    """Cheap clock gate for the Blue Ocean overnight session, so we only hit
    Alpaca when it's plausibly trading (never Sat / mid-day). Evening leg =
    Sun–Thu 20:00–23:59; morning leg = Mon–Fri 00:00–03:59 (tail of Sun–Thu
    nights). The freshness check is the real authority — this just avoids waste."""
    wd, h = now_et.weekday(), now_et.hour   # Mon=0 … Sun=6
    if h >= 20 and wd in (6, 0, 1, 2, 3):   # evening leg (Sun–Thu nights)
        return True
    if h < 4 and wd in (0, 1, 2, 3, 4):     # morning leg (Mon–Fri)
        return True
    return False


def _alpaca_headers() -> "dict | None":
    k, s = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    return {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s} if k and s else None


def _age_s(iso_ts: str) -> float:
    try:
        tt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - tt).total_seconds()
    except Exception:
        return 1e9


def fetch_overnight(symbol: str, headers: dict) -> "dict | None":
    """Blue Ocean overnight mark via Alpaca `overnight` feed. Returns
    {price, bar_time, ov_bid?, ov_ask?, ov_trade?} or None.

    Price = bid/ask MIDPOINT when a two-sided quote exists, else the last trade.
    Overnight is thin: quotes refresh continuously but trades are sparse, so the
    last *trade* can be many hours stale (QBTZ printed 19h-old $6.49 while its
    live quote midpoint was $5.83). The NBBO midpoint is the honest current mark;
    `bar_time` tracks whichever source set the price so freshness stays truthful."""
    try:
        q = (requests.get(f"{_ALPACA_DATA}/{symbol}/quotes/latest", headers=headers,
                          params={"feed": "overnight"}, timeout=10).json().get("quote") or {})
        bid, ask, q_ts = q.get("bp"), q.get("ap"), q.get("t")
        tr = (requests.get(f"{_ALPACA_DATA}/{symbol}/trades/latest", headers=headers,
                           params={"feed": "overnight"}, timeout=10).json().get("trade") or {})
        tp, t_ts = tr.get("p"), tr.get("t")

        out: dict = {}
        if bid and ask and q_ts:
            out["ov_bid"], out["ov_ask"] = round(float(bid), 4), round(float(ask), 4)
            out["price"] = round((float(bid) + float(ask)) / 2, 4)
            out["bar_time"] = q_ts
            if tp is not None:
                out["ov_trade"] = round(float(tp), 4)
        elif tp is not None and t_ts:
            out["price"] = round(float(tp), 4)
            out["bar_time"] = t_ts
        else:
            return None
        return out
    except Exception:
        return None


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
    session = us_session(now_et)
    quotes = {}
    for sym in TICKERS:
        q = fetch_quote(sym)
        if q:
            quotes[sym.lower()] = q

    # 🌙 夜盘覆盖:常规/盘前后 yfinance(prepost)已够;仅当 yfinance 收工(closed)
    # 且时钟在夜盘窗内,才用 Alpaca overnight feed 覆盖实时价。以 QBTS 最新成交
    # ≤_OVERNIGHT_FRESH_S 判定夜盘活跃;prev_close 仍取 yfinance(上一常规收盘),
    # 夜盘涨跌据此重算。QBTX/QBTZ 成交稀疏,拿到就覆盖、拿不到保留昨收(各带 ov_age_s)。
    if session == "closed" and _overnight_window(now_et):
        headers = _alpaca_headers()
        qbts_ov = fetch_overnight("QBTS", headers) if headers else None
        if qbts_ov and _age_s(qbts_ov["bar_time"]) <= _OVERNIGHT_FRESH_S:
            session = "overnight"
            for sym in TICKERS:
                ov = qbts_ov if sym == "QBTS" else fetch_overnight(sym, headers)
                q = quotes.get(sym.lower())
                if not ov or not q:
                    continue
                q["price"] = ov["price"]
                q["bar_time"] = ov["bar_time"]
                q["ov_age_s"] = int(_age_s(ov["bar_time"]))
                for k in ("ov_bid", "ov_ask"):
                    if k in ov:
                        q[k] = ov[k]
                pc = q.get("prev_close")
                q["change_pct"] = round(q["price"] / pc - 1, 6) if pc else None

    # 杠杆腿隐含公允价:QBTZ/QBTX 薄流动性,最后成交价常偏离 2× 换算(实测
    # 07-09 收盘差 0.66pp,是真实贴价偏离而非 prev_close 口径问题)。给下游一个
    # 干净基准:implied_px = 自身上一收盘 × (1 + 杠杆 × QBTS涨跌),premium_pct
    # = 现价对它的折溢价 —— 失效价换算/一致性自检都以此为准。
    base = quotes.get("qbts")
    if base and base.get("change_pct") is not None:
        for sym, lev in (("qbtx", 2.0), ("qbtz", -2.0)):
            q = quotes.get(sym)
            if q and q.get("prev_close"):
                fair = q["prev_close"] * (1 + lev * base["change_pct"])
                q["implied_px"] = round(fair, 4)
                if q.get("price") and fair:
                    q["premium_pct"] = round(q["price"] / fair - 1, 6)
    return {
        "session":    session,
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
        # overnight counts as "live" → 60s; only truly closed (Sat/holiday) idles at 600s
        sess = p.get("session", "closed")
        time.sleep(60 if sess != "closed" else 600)


if __name__ == "__main__":
    main()
