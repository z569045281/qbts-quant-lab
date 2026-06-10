"""
QBTS Sentiment Pipeline — StockTwits public API (no auth required).

Fetches recent messages for QBTS and computes:
  - bull_ratio     : fraction of sentiment-tagged messages that are bullish
  - message_count  : volume of recent messages (attention proxy)
  - watchers       : StockTwits followers (interest proxy)
  - sentiment_label: "BULLISH" | "BEARISH" | "NEUTRAL"

Used as market context injected into Claude's factor generation prompt.
"""

import logging
import urllib.request
import json
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/QBTS.json?limit=30"


def _fetch_stocktwits(url: str = STOCKTWITS_URL, timeout: int = 8) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; QBTS-Miner/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def get_sentiment_context(ticker: str = "QBTS") -> dict:
    """
    Returns a dict with QBTS sentiment snapshot.
    Falls back gracefully if the API is unavailable.
    """
    try:
        data = _fetch_stocktwits()

        messages = data.get("messages", [])
        symbol_info = data.get("symbol", {})

        bull_count = sum(
            1 for m in messages
            if (m.get("entities", {}).get("sentiment") or {}).get("basic") == "Bullish"
        )
        bear_count = sum(
            1 for m in messages
            if (m.get("entities", {}).get("sentiment") or {}).get("basic") == "Bearish"
        )
        tagged_total = bull_count + bear_count
        bull_ratio = round(bull_count / tagged_total, 3) if tagged_total > 0 else 0.5

        # Grab a few recent message bodies for qualitative context
        recent_msgs = [
            m.get("body", "")[:120]
            for m in messages[:5]
            if m.get("body")
        ]

        label = "NEUTRAL"
        if tagged_total >= 3:
            label = "BULLISH" if bull_ratio >= 0.6 else ("BEARISH" if bull_ratio <= 0.4 else "NEUTRAL")

        result = {
            "ticker":        ticker,
            "fetched_at":    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "message_count": len(messages),
            "bull_count":    bull_count,
            "bear_count":    bear_count,
            "bull_ratio":    bull_ratio,
            "sentiment_label": label,
            "watchers":      symbol_info.get("watchlist_count", "N/A"),
            "recent_messages": recent_msgs,
        }
        logger.info(f"StockTwits {ticker}: {label} bull={bull_ratio:.0%} msgs={len(messages)}")
        return result

    except Exception as e:
        logger.warning(f"StockTwits fetch failed ({e}), using neutral fallback")
        return {
            "ticker":          ticker,
            "fetched_at":      "unavailable",
            "sentiment_label": "NEUTRAL",
            "bull_ratio":      0.5,
            "message_count":   0,
            "watchers":        "N/A",
            "recent_messages": [],
            "error":           str(e),
        }


def get_fear_greed() -> dict:
    """
    Crypto/market Fear & Greed Index via alternative.me (free, no auth).
    0 = Extreme Fear, 100 = Extreme Greed.
    """
    try:
        req = urllib.request.Request(
            "https://api.alternative.me/fng/?limit=5",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
        entries = data.get("data", [])
        if not entries:
            raise ValueError("empty")
        latest = entries[0]
        score  = int(latest["value"])
        label  = latest["value_classification"]   # e.g. "Fear", "Greed"
        # 5-day trend: rising or falling
        if len(entries) >= 3:
            trend = int(entries[0]["value"]) - int(entries[2]["value"])
            trend_label = "rising" if trend > 3 else ("falling" if trend < -3 else "flat")
        else:
            trend_label = "flat"
        logger.info(f"Fear & Greed: {score} ({label}), 3d trend={trend_label}")
        return {"score": score, "label": label, "trend": trend_label, "available": True}
    except Exception as e:
        logger.warning(f"Fear & Greed fetch failed: {e}")
        return {"score": 50, "label": "Neutral", "trend": "flat", "available": False}


def sentiment_to_prompt_context(ctx: dict) -> str:
    """
    Formats the sentiment snapshot into a concise paragraph
    that can be appended to Claude's user message.
    """
    label   = ctx["sentiment_label"]
    bull_r  = ctx["bull_ratio"]
    msgs    = ctx["message_count"]
    watch   = ctx["watchers"]
    fetched = ctx["fetched_at"]

    lines = [
        f"\n\n--- LIVE MARKET CONTEXT (as of {fetched}) ---",
        f"StockTwits sentiment for QBTS: {label}",
        f"  Bullish ratio : {bull_r:.0%}  ({ctx.get('bull_count',0)} bull / {ctx.get('bear_count',0)} bear)",
        f"  Message volume: {msgs} recent posts (high = elevated retail attention)",
        f"  Watchers      : {watch}",
    ]

    if ctx.get("recent_messages"):
        lines.append("  Recent chatter sample:")
        for i, m in enumerate(ctx["recent_messages"][:3], 1):
            lines.append(f"    [{i}] {m}")

    fg = ctx.get("fear_greed", {})
    if fg.get("available"):
        lines += [
            f"  Fear & Greed Index: {fg['score']}/100 ({fg['label']}, 3d trend={fg['trend']})",
            f"    → score <25 = Extreme Fear (contrarian BUY signal historically)",
            f"    → score >75 = Extreme Greed (contrarian SELL / mean-reversion signal)",
        ]

    lines += [
        "---",
        "Use this multi-source sentiment context to bias your factor design:",
        f"  - StockTwits BULLISH + F&G Greed    → momentum exhaustion / contrarian short setup",
        f"  - StockTwits BEARISH + F&G Fear      → capitulation / contrarian long setup",
        f"  - High message volume                → elevated volatility regime, wider stops",
        f"  - StockTwits BULLISH + F&G Fear      → retail buying dip, momentum continuation",
        "The factor code must still use only the OHLCV + pre-computed columns in df.",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    ctx = get_sentiment_context()
    print(json.dumps(ctx, indent=2, ensure_ascii=False))
    print()
    print(sentiment_to_prompt_context(ctx))
