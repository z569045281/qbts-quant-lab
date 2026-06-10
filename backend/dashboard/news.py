"""
News pipeline for the dashboard.

  1. fetch_news_items() — pull recent QBTS + sector news via yfinance.
  2. analyze_news_batch() — single Claude call rates impact on QBTS.

The Claude call is BATCHED across all items (one API call per refresh)
to keep cost low. Result is cached for 1 hour.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import anthropic
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_CLIENT      = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
_NEWS_CACHE  = Path(__file__).parent.parent / "data" / "cache" / "news_analysis.json"
_NEWS_CACHE.parent.mkdir(parents=True, exist_ok=True)

_CACHE_SECONDS = 3600        # 1-hour TTL — news doesn't change minute-by-minute
_PER_TICKER_LIMIT = 5
_TICKERS = ["QBTS", "IONQ", "RGTI"]


def _normalize_item(raw: dict, ticker: str) -> dict:
    """Handle both old and new yfinance news payload shapes."""
    c = raw.get("content", raw)
    provider = c.get("provider") or {}
    if isinstance(provider, dict):
        publisher = provider.get("displayName") or raw.get("publisher", "Unknown")
    else:
        publisher = str(provider) or raw.get("publisher", "Unknown")

    link = c.get("canonicalUrl") or c.get("clickThroughUrl") or {}
    if isinstance(link, dict):
        url = link.get("url")
    else:
        url = link or raw.get("link", "")

    return {
        "title":     c.get("title", "?"),
        "publisher": publisher,
        "published": (c.get("pubDate") or raw.get("providerPublishTime", "") or "")[:19],
        "url":       url,
        "summary":   (c.get("summary") or "")[:280],
        "ticker":    ticker,
    }


def fetch_news_items() -> list[dict]:
    """Fetch recent news for QBTS + quantum peers, deduped, sorted by date."""
    items: list[dict] = []
    for sym in _TICKERS:
        try:
            raw_list = yf.Ticker(sym).news[:_PER_TICKER_LIMIT]
            for raw in raw_list:
                items.append(_normalize_item(raw, sym))
        except Exception as e:
            logger.warning(f"News fetch failed for {sym}: {e}")

    # Dedup by title (sometimes peers republish)
    seen, dedup = set(), []
    for it in items:
        key = it["title"].lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        dedup.append(it)

    dedup.sort(key=lambda x: x["published"], reverse=True)
    return dedup[:12]   # cap so the Claude prompt stays small


_ANALYSIS_PROMPT = """You are a senior quant analyst rating news impact on QBTS (D-Wave Quantum Inc.) stock price.

For each news headline below, return a JSON object with:
  - sentiment   : "bullish" | "bearish" | "neutral"
  - impact      : "high" | "medium" | "low" (price-move magnitude expected: high = 5%+, medium = 1-5%, low = <1%)
  - horizon     : "intraday" | "1-3d" | "1-2w" | "longer"
  - reasoning   : ONE concise sentence explaining the mechanism (max 100 chars)

Rules:
- QBTS is a quantum-computing pure-play with low float; news cuts hard in both directions.
- IONQ / RGTI news matters for sector-wide regime but less per-name.
- Earnings, government contracts, partnerships = high impact.
- Analyst price target changes = medium impact.
- General market commentary = low impact (often neutral).
- Repeat / minor news = low impact.

Output ONLY a JSON array (no markdown fence, no other text), one object per headline, in the same order:
[
  {"sentiment": "...", "impact": "...", "horizon": "...", "reasoning": "..."},
  ...
]
"""


def analyze_news_batch(items: list[dict]) -> list[dict]:
    """Single Claude call analysing all news items. Returns items annotated with `ai`."""
    if not items:
        return []

    headline_block = "\n".join(
        f"{i+1}. [{it['ticker']}] [{it['publisher']}] {it['title']}"
        for i, it in enumerate(items)
    )
    user_msg = headline_block + "\n\nReturn the JSON array now."

    try:
        # Haiku is plenty for news sentiment classification (~90% cheaper than Sonnet).
        # If quality regresses, swap back to claude-sonnet-4-6.
        resp = _CLIENT.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=_ANALYSIS_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip()
        # Strip accidental markdown fences
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.rsplit("```", 1)[0]
        ratings = json.loads(text.strip())
    except Exception as e:
        logger.warning(f"News analysis failed: {e}")
        ratings = [{"sentiment": "neutral", "impact": "low", "horizon": "1-3d",
                    "reasoning": "AI analysis unavailable"} for _ in items]

    # Pad/truncate to match items length
    if len(ratings) < len(items):
        ratings += [{"sentiment": "neutral", "impact": "low", "horizon": "1-3d",
                     "reasoning": "missing analysis"} for _ in range(len(items) - len(ratings))]
    ratings = ratings[:len(items)]

    out = []
    for it, r in zip(items, ratings):
        out.append({**it, "ai": r})
    return out


def aggregate_news_sentiment(items: list[dict]) -> dict:
    """Weighted average sentiment across items. Weight = impact level."""
    impact_w = {"high": 3, "medium": 2, "low": 1}
    score = 0
    n_bull = n_bear = n_neut = 0
    for it in items:
        ai = it.get("ai", {})
        w = impact_w.get(ai.get("impact", "low"), 1)
        s = ai.get("sentiment", "neutral")
        if s == "bullish":   score += w; n_bull += 1
        elif s == "bearish": score -= w; n_bear += 1
        else:                            n_neut += 1
    if score >= 3:
        label, signal = "bullish", 1
    elif score <= -3:
        label, signal = "bearish", -1
    else:
        label, signal = "neutral", 0
    return {
        "label":   label,
        "signal":  signal,
        "score":   score,
        "n_bull":  n_bull,
        "n_bear":  n_bear,
        "n_neutral": n_neut,
        "n_items": len(items),
    }


def get_news_snapshot(force_refresh: bool = False) -> dict:
    """
    Public entry point. Returns:
      { "as_of": iso, "items": [...], "aggregate": {...} }
    Cached for 1 hour by default.
    """
    if not force_refresh and _NEWS_CACHE.exists():
        try:
            cached = json.loads(_NEWS_CACHE.read_text())
            if time.time() - cached.get("_ts", 0) < _CACHE_SECONDS:
                return cached["payload"]
        except Exception:
            pass

    items     = fetch_news_items()
    annotated = analyze_news_batch(items)
    payload   = {
        "as_of":     time.strftime("%Y-%m-%d %H:%M", time.localtime()),
        "items":     annotated,
        "aggregate": aggregate_news_sentiment(annotated),
    }
    _NEWS_CACHE.write_text(json.dumps({"_ts": time.time(), "payload": payload}, ensure_ascii=False))
    return payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    snap = get_news_snapshot(force_refresh=True)
    print(f"As of: {snap['as_of']}")
    print(f"Aggregate: {snap['aggregate']}")
    for it in snap["items"][:5]:
        ai = it["ai"]
        print(f"  [{ai['sentiment']:8s} / {ai['impact']:6s}] {it['title'][:70]}")
        print(f"    → {ai['reasoning']}")
