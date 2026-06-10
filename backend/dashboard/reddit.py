"""
Reddit mention-velocity signal for the meta-model.

⚠️ REQUIRES OAUTH IN 2026
  Reddit blocks all unauthenticated API calls (returns HTTP 403). You MUST set:
      REDDIT_CLIENT_ID=...
      REDDIT_CLIENT_SECRET=...
  in your .env file (or shell environment). 2-minute setup:

    1. Go to https://www.reddit.com/prefs/apps
    2. Click "create another app..." at the bottom
    3. Name: "QBTS Quant Lab"  (or anything)
    4. Type: SELECT "script"  ← important
    5. redirect uri: http://localhost (anything works for script type)
    6. Click "create app"
    7. Copy the string under your app name (that's CLIENT_ID, ~14 chars)
       and the "secret" string (CLIENT_SECRET, ~27 chars)
    8. Add to backend/.env:
         REDDIT_CLIENT_ID=xxxxxxxxxxxxxx
         REDDIT_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxx
    9. Restart the backend

  Reddit's "client_credentials" grant gives 100 requests/min — way more than
  we need. Token auto-refreshes every ~24h. Free forever for personal use.

What this signal measures:
  Mention velocity for QBTS/D-Wave across r/wallstreetbets + r/stocks +
  r/quantumcomputing. Spikes lead retail flow by 1-3 days.

Signal computation:
  We count mentions of "QBTS"/"D-Wave"/"$QBTS" in WSB + r/stocks + r/quantumcomputing
  over the last 7 days. Velocity = (last 24h mentions) / (mean prev 6 days).
  Sentiment = simple lexicon score on titles + (first 200 chars of) selftexts.

  velocity > 3 + bullish → BUY (FOMO inflow imminent)
  velocity > 3 + bearish → SELL (panic spreading)
  velocity > 2  → directional BUY/SELL by sentiment
  velocity < 0.5 → fading attention → slight SELL bias (meme-stock decay)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).parent.parent / "data" / "cache" / "reddit_signal.json"
_TOKEN_PATH = Path(__file__).parent.parent / "data" / "cache" / "reddit_token.json"
_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

_CACHE_TTL = 1800     # 30 min
_USER_AGENT = "QBTS-Quant-Lab/1.0 (private research tool)"
_TIMEOUT   = 10

# Subreddits to monitor (ordered by signal value for a low-float retail meme)
_SUBREDDITS = ["wallstreetbets", "stocks", "quantumcomputing"]

# Search variants for QBTS — Reddit search is OR'd within one query
_SEARCH_QUERIES = ["QBTS OR \"D-Wave\""]

# WSB-flavoured sentiment lexicon
_BULL = {
    # generic finance bull
    "moon", "rocket", "🚀", "calls", "buy", "long", "bullish", "rally",
    "breakout", "squeeze", "gamma", "gap up", "ath", "all time high",
    "diamond", "hodl", "hold", "to the moon", "lambo", "tendies",
    "yolo long", "pumping", "ripping", "buying", "loaded", "loading",
    # quantum/QBTS-specific positives
    "contract", "doe", "partnership", "milestone", "advantage", "supremacy",
    "earnings beat", "upgrade", "price target", "PT raise",
}
_BEAR = {
    "puts", "short", "shorting", "bearish", "dump", "dumping", "crash",
    "tank", "tanking", "rug", "rugged", "bag holder", "bagholder",
    "drilling", "dropping", "sell", "selling", "selloff", "selloffs",
    "rip", "dead", "decline", "miss", "downgrade", "PT cut",
    "exit", "exiting", "fade", "dilution", "offering", "secondary",
}


def _http_get_json(url: str, headers: dict | None = None) -> dict | None:
    """GET a URL returning parsed JSON, or None on failure."""
    h = {"User-Agent": _USER_AGENT}
    if headers:
        h.update(headers)
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode(errors="ignore"))
    except Exception as e:
        logger.debug(f"Reddit GET failed for {url[:90]}: {e}")
        return None


# ── OAuth path ──────────────────────────────────────────────────────────────

def _get_oauth_token() -> str | None:
    """
    Application-only OAuth ("client_credentials" grant). Caches the token to
    disk for ~24h. Returns None if credentials not configured or auth fails.
    """
    cid = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    csec = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    if not (cid and csec):
        return None

    # Cached token?
    if _TOKEN_PATH.exists():
        try:
            cached = json.loads(_TOKEN_PATH.read_text())
            if cached.get("expires_at", 0) > time.time() + 60:
                return cached["access_token"]
        except Exception:
            pass

    auth = base64.b64encode(f"{cid}:{csec}".encode()).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=body,
        headers={"Authorization": f"Basic {auth}", "User-Agent": _USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode())
        token = payload["access_token"]
        ttl   = int(payload.get("expires_in", 3600))
        _TOKEN_PATH.write_text(json.dumps({
            "access_token": token,
            "expires_at":   time.time() + ttl - 60,
        }))
        logger.info("Reddit OAuth token acquired")
        return token
    except Exception as e:
        logger.warning(f"Reddit OAuth failed: {e}")
        return None


def _fetch_oauth(sub: str, query: str, limit: int = 50) -> list[dict]:
    """Fetch via oauth.reddit.com using a bearer token."""
    token = _get_oauth_token()
    if not token:
        return []
    q = urllib.parse.quote(query)
    url = f"https://oauth.reddit.com/r/{sub}/search?q={q}&restrict_sr=1&sort=new&t=week&limit={limit}"
    data = _http_get_json(url, headers={"Authorization": f"Bearer {token}"})
    if not data:
        return []
    return [child["data"] for child in data.get("data", {}).get("children", [])]


# ── Unauthenticated path ────────────────────────────────────────────────────

def _fetch_public(sub: str, query: str, limit: int = 50) -> list[dict]:
    """Fetch via the public old.reddit.com JSON endpoint (no auth, rate-limited)."""
    q = urllib.parse.quote(query)
    url = f"https://old.reddit.com/r/{sub}/search.json?q={q}&restrict_sr=on&sort=new&t=week&limit={limit}"
    data = _http_get_json(url)
    if not data:
        return []
    return [child["data"] for child in data.get("data", {}).get("children", [])]


# ── Aggregation ─────────────────────────────────────────────────────────────

def _score_text(text: str) -> int:
    """+1 per bull keyword, -1 per bear keyword. Cheap but effective for headline-style text."""
    t = (text or "").lower()
    pos = sum(1 for w in _BULL if w in t)
    neg = sum(1 for w in _BEAR if w in t)
    return pos - neg


def _aggregate(posts: list[dict]) -> dict:
    """Bucket posts by day for the last 7d, score sentiment, find hot posts."""
    now = time.time()
    day_secs = 86400
    counts_by_day = defaultdict(int)
    sentiment_sum_by_day = defaultdict(int)
    hot_posts: list[dict] = []

    for p in posts:
        created = p.get("created_utc")
        if not created:
            continue
        age_days = int((now - created) // day_secs)
        if age_days < 0 or age_days > 7:
            continue
        title = p.get("title", "")
        body  = (p.get("selftext", "") or "")[:200]
        ups   = int(p.get("ups", 0) or 0)
        score = _score_text(title + " " + body)
        # Upweight by upvotes (log-scaled — viral posts matter more)
        import math
        weight = 1 + math.log(max(ups, 1))
        counts_by_day[age_days] += 1
        sentiment_sum_by_day[age_days] += score * weight

        if ups > 5 or age_days <= 1:
            hot_posts.append({
                "title":      title[:120],
                "ups":        ups,
                "num_comments": int(p.get("num_comments", 0) or 0),
                "subreddit":  p.get("subreddit", ""),
                "url":        f"https://reddit.com{p.get('permalink','')}",
                "age_days":   age_days,
                "sentiment":  score,
            })

    last_24h    = counts_by_day.get(0, 0)
    prev_6days  = [counts_by_day.get(d, 0) for d in range(1, 7)]
    prev_avg    = sum(prev_6days) / max(len(prev_6days), 1)
    velocity    = last_24h / prev_avg if prev_avg > 0.5 else (last_24h * 1.0 if last_24h else 1.0)

    # Net sentiment over the recent 3 days, normalised by count
    recent_sent = sum(sentiment_sum_by_day.get(d, 0) for d in (0, 1, 2))
    recent_count = sum(counts_by_day.get(d, 0)        for d in (0, 1, 2))
    sentiment   = recent_sent / max(recent_count, 1)

    hot_posts.sort(key=lambda x: (x["age_days"], -x["ups"]))

    return {
        "n_total_7d":  sum(counts_by_day.values()),
        "n_last_24h":  last_24h,
        "n_prev_6d_avg": round(prev_avg, 2),
        "velocity":    round(velocity, 2),
        "sentiment":   round(sentiment, 3),
        "by_day":      {str(k): v for k, v in counts_by_day.items()},
        "hot_posts":   hot_posts[:8],
    }


def _signal_from_agg(agg: dict, auth_mode: str = "public") -> dict:
    if not agg or agg.get("n_total_7d", 0) == 0:
        if auth_mode == "public":
            reason = "❌ 需要 OAuth 凭证（Reddit 已封无凭证 API）— 设置 REDDIT_CLIENT_ID/SECRET 启用"
        else:
            reason = "OAuth 已配置但 7 日内无 QBTS 提及（确实冷清）"
        return {
            "signal": 0, "label": "HOLD", "confidence": "low",
            "log_odds_magnitude": 0.0,
            "rationale": reason,
            "snapshot": agg,
        }

    vel = agg["velocity"]
    sent = agg["sentiment"]
    n24  = agg["n_last_24h"]

    signal     = 0
    confidence = "low"
    mag        = 0.0
    bits       = []

    # Strong velocity spike
    if vel >= 3.0 and n24 >= 5:
        if sent > 0.3:
            signal, confidence, mag = 1, "high", 0.40
            bits.append(f"提及速度 {vel:.1f}× + 情绪偏多 ({sent:+.2f})（FOMO 流入）")
        elif sent < -0.3:
            signal, confidence, mag = -1, "high", 0.40
            bits.append(f"提及速度 {vel:.1f}× + 情绪偏空 ({sent:+.2f})（恐慌扩散）")
        else:
            # High attention, neutral sentiment — usually bullish for meme stocks (any attention helps)
            signal, confidence, mag = 1, "medium", 0.25
            bits.append(f"提及速度 {vel:.1f}× + 情绪中性 ({sent:+.2f})（高关注度）")
    elif vel >= 2.0 and n24 >= 3:
        if sent > 0.2:
            signal, confidence, mag = 1, "medium", 0.22
            bits.append(f"提及速度 {vel:.1f}× + 偏多 ({sent:+.2f})")
        elif sent < -0.2:
            signal, confidence, mag = -1, "medium", 0.22
            bits.append(f"提及速度 {vel:.1f}× + 偏空 ({sent:+.2f})")
    elif vel <= 0.4 and agg["n_prev_6d_avg"] >= 3:
        # Attention fading — meme stocks lose momentum as WSB moves on
        signal, confidence, mag = -1, "low", 0.10
        bits.append(f"提及速度 {vel:.1f}× 衰退（散户关注转移）")

    if not bits:
        bits.append(f"提及速度 {vel:.1f}× · 情绪 {sent:+.2f} · 24h {n24} 条（中性）")

    return {
        "signal":             signal,
        "label":              {1: "BUY", -1: "SELL", 0: "HOLD"}[signal],
        "confidence":         confidence,
        "log_odds_magnitude": round(mag, 3),
        "rationale":          " · ".join(bits),
        "snapshot":           agg,
    }


# ── Public entry point ─────────────────────────────────────────────────────

def fetch_reddit_signal(force_refresh: bool = False) -> dict:
    if not force_refresh and _CACHE_PATH.exists():
        try:
            cached = json.loads(_CACHE_PATH.read_text())
            if time.time() - cached.get("_ts", 0) < _CACHE_TTL:
                return cached["payload"]
        except Exception:
            pass

    use_oauth = bool(os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET"))

    # If no OAuth creds, skip fetching entirely (unauth endpoint is 100% blocked
    # in 2026 → wasted requests + 3+ seconds of sleep for guaranteed HOLD).
    # Cache the "needs auth" result for the normal TTL so we don't re-check.
    if not use_oauth:
        payload = _signal_from_agg({}, auth_mode="public")
        payload["auth_mode"] = "public"
        _CACHE_PATH.write_text(json.dumps({"_ts": time.time(), "payload": payload},
                                           ensure_ascii=False))
        return payload

    all_posts: list[dict] = []
    for sub in _SUBREDDITS:
        for q in _SEARCH_QUERIES:
            posts = _fetch_oauth(sub, q, limit=50)
            all_posts.extend(posts)

    # Dedup by post id (a search can return same post from different queries)
    seen = set()
    unique = []
    for p in all_posts:
        pid = p.get("id")
        if pid and pid not in seen:
            seen.add(pid)
            unique.append(p)

    agg = _aggregate(unique)
    auth_mode = "oauth" if use_oauth else "public"
    payload = _signal_from_agg(agg, auth_mode=auth_mode)
    payload["auth_mode"] = auth_mode

    _CACHE_PATH.write_text(json.dumps({"_ts": time.time(), "payload": payload},
                                       ensure_ascii=False))
    return payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sig = fetch_reddit_signal(force_refresh=True)
    print(json.dumps(sig, indent=2, ensure_ascii=False)[:2500])
