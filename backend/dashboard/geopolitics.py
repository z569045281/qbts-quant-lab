"""
🌍 地缘政治/政策雷达 — 伊朗战局 + 川普政策 + 量子政策 headline tracker.

Why: QBTS (high-beta quantum) trades on the war/policy tape — the 2026-07-07
crash was the Iran talks collapsing, not anything company-specific. The rest
of the dashboard is mechanical and event-blind; this module watches exactly
the three tracks the user identified:

  iran     — 伊朗/中东战局(谈判/停火/袭击/霍尔木兹)
  trump    — 川普政策发言(关税/行政令/市场相关表态)
  quantum  — 量子政策(国防/出口管制/政府预算)

Source: Google News RSS search (free, no key, `when:2d` window). One Haiku
call classifies the batch: per-item relevance/stance/一句话中文注 + an overall
risk level (alert/watch/calm) with a Chinese situation summary.

Cost control: RSS is free; Haiku only runs when the headline set actually
changed (new item keys vs cache) or the analysis is >6h old. The intraday
Lambda path (`maybe_geo_refresh`) runs ~every 30 min and fires an ntfy push
on (a) a NEW high-relevance item, (b) the risk level flipping — deduped via
the `alerted` key list carried in live_quote, same pattern as intraday_smc.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).parent.parent / "data" / "cache" / "geopolitics.json"
_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

_FRESH_SECONDS   = 15 * 60      # 缓存 <15min 直接用(盘中刷新节拍是 ~30min)
_REANALYZE_SECONDS = 6 * 3600   # 即便无新头条,分析 >6h 也重跑一次 Haiku
_PER_TRACK_LIMIT = 8
_PROMPT_CAP      = 16           # 喂给 Haiku 的条数上限

# (track, 中文标签, Google News 检索式) — `when:2d` 限最近 48h
_TRACKS = [
    ("iran", "伊朗/中东",
     'Iran nuclear talks OR Iran ceasefire OR Iran strikes OR "Strait of Hormuz"'),
    ("trump", "川普政策",
     'Trump tariffs OR "executive order" Trump OR Trump statement stock market'),
    ("quantum", "量子政策",
     '"quantum computing" Pentagon OR "quantum computing" export controls OR "quantum computing" funding bill'),
]

_RISK_CN = {"alert": "🔴 升温", "watch": "🟡 观察", "calm": "🟢 平静"}


def _item_key(title: str) -> str:
    return hashlib.md5(title.lower().strip()[:80].encode("utf-8")).hexdigest()[:10]


def _fetch_track(track: str, track_cn: str, query: str) -> list[dict]:
    q = urllib.parse.quote(f"{query} when:2d")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        root = ET.fromstring(resp.read())

    items = []
    for it in root.findall(".//item")[:_PER_TRACK_LIMIT]:
        title  = (it.findtext("title") or "").strip()
        source = (it.findtext("source") or "").strip()
        # Google News 标题带 " - Source" 尾巴 — 去掉
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate") or "").astimezone(timezone.utc)
            published = pub.isoformat()[:16]
        except Exception:
            published = ""
        if not title:
            continue
        items.append({
            "key":       _item_key(title),
            "track":     track,
            "track_cn":  track_cn,
            "title":     title[:160],
            "source":    source[:40],
            "published": published,
            "url":       (it.findtext("link") or "")[:400],
        })
    return items


def _fetch_all_tracks() -> list[dict]:
    items: list[dict] = []
    for track, track_cn, query in _TRACKS:
        try:
            items.extend(_fetch_track(track, track_cn, query))
        except Exception as e:
            logger.warning(f"geo RSS fetch failed for {track}: {e}")
    # 跨检索式去重(同一事件常同时命中 iran+trump)
    seen, dedup = set(), []
    for it in items:
        if it["key"] in seen:
            continue
        seen.add(it["key"])
        dedup.append(it)
    dedup.sort(key=lambda x: x["published"], reverse=True)
    return dedup[:_PROMPT_CAP]


_ANALYSIS_PROMPT = """你是给 QBTS(D-Wave Quantum,高贝塔量子股)做地缘政治风险分级的分析师。
量子股与「伊朗战局/川普政策发言/量子相关政策」高度联动:谈判破裂・开战・关税升级 → 高贝塔股暴跌(risk_off);停火・协议达成・量子利好政策 → 反弹(risk_on)。

对下面每条新闻标题,输出:
  - relevance : "high" | "medium" | "low" — 对量子股/高贝塔盘面的影响力度。
      high = 战争状态改变(开战/停火/谈判破裂或达成)、重大政策落地、直接点名量子行业;
      medium = 局势演进但非转折、政策放风;low = 评论/旧闻重复/背景报道。
  - stance    : "risk_off" | "risk_on" | "neutral" — 对量子股方向(升级/破裂=risk_off,缓和/利好=risk_on)。
  - note_cn   : ≤40字中文,说清「这条对盘面意味着什么」。

然后给整体:
  - risk_level  : "alert"(局势升温,高贝塔随时再挨打) | "watch"(有变数,盯紧) | "calm"(平静)。
  - headline_cn : ≤30字,一句话当前局势(如「美伊停火破裂,美军再袭伊朗」)。
  - summary_cn  : 2-3句中文:①伊朗/政策现状 ②对 QBTS/量子股的具体含义(方向+该防什么)。

规则:同一事件多条报道,只给最新最具体的一条 high,其余降级;不确定就保守(watch 而非 calm)。

只输出 JSON(无 markdown 围栏):
{"risk_level": "...", "headline_cn": "...", "summary_cn": "...",
 "items": [{"relevance": "...", "stance": "...", "note_cn": "..."}, ...]}
items 数组与输入同序同长。"""


def _analyze(items: list[dict]) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    lines = "\n".join(
        f"{i+1}. [{it['track_cn']}] ({it['published'][5:16]}) {it['title']} — {it['source']}"
        for i, it in enumerate(items))
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        system=_ANALYSIS_PROMPT,
        messages=[{"role": "user", "content": lines + "\n\n现在输出 JSON。"}],
    )
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        text = text[4:] if text.startswith("json") else text
        text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())


def get_geo_snapshot(force_refresh: bool = False) -> dict | None:
    """Public entry. Returns the radar payload (None only if everything failed).

    RSS refreshes every call (>15min old); Haiku re-runs only when the headline
    set changed or the last analysis is >6h old.
    """
    cached = None
    if _CACHE_PATH.exists():
        try:
            cached = json.loads(_CACHE_PATH.read_text())
        except Exception:
            cached = None

    now = time.time()
    if cached and not force_refresh and now - cached.get("_ts", 0) < _FRESH_SECONDS:
        return cached["payload"]

    try:
        items = _fetch_all_tracks()
    except Exception as e:
        logger.warning(f"geo RSS fetch failed entirely: {e}")
        return cached["payload"] if cached else None
    if not items:
        return cached["payload"] if cached else None

    # 头条没变且分析还新鲜 → 跳过 Haiku(只更新时间戳)
    if cached and not force_refresh:
        old_keys = {it["key"] for it in cached["payload"].get("items", [])}
        analyzed_at = cached.get("_analyzed", 0)
        if (all(it["key"] in old_keys for it in items)
                and now - analyzed_at < _REANALYZE_SECONDS):
            cached["_ts"] = now
            _CACHE_PATH.write_text(json.dumps(cached, ensure_ascii=False))
            return cached["payload"]

    try:
        ai = _analyze(items)
        ratings = ai.get("items") or []
        for it, r in zip(items, ratings):
            it["relevance"] = r.get("relevance", "low")
            it["stance"]    = r.get("stance", "neutral")
            it["note_cn"]   = str(r.get("note_cn", ""))[:60]
        for it in items[len(ratings):]:
            it.update({"relevance": "low", "stance": "neutral", "note_cn": ""})
        level = ai.get("risk_level") if ai.get("risk_level") in _RISK_CN else "watch"
        payload = {
            "as_of":       datetime.now(timezone.utc).isoformat(),
            "risk_level":  level,
            "risk_cn":     _RISK_CN[level],
            "headline_cn": str(ai.get("headline_cn", ""))[:60],
            "summary_cn":  str(ai.get("summary_cn", ""))[:400],
            "items":       items,
        }
    except Exception as e:
        logger.warning(f"geo Haiku analysis failed: {e}")
        if cached:
            return cached["payload"]
        # 无缓存也别全黑:给未分级的原始头条,级别保守置 watch
        for it in items:
            it.update({"relevance": "medium", "stance": "neutral", "note_cn": ""})
        payload = {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "risk_level": "watch", "risk_cn": _RISK_CN["watch"],
            "headline_cn": "AI 分级不可用,仅原始头条",
            "summary_cn": "", "items": items,
        }

    _CACHE_PATH.write_text(json.dumps(
        {"_ts": now, "_analyzed": now, "payload": payload}, ensure_ascii=False))
    return payload


# ── 盘中刷新 + ntfy 推送(QuoteFunction 每分钟调,~30min 节拍)──────────────


def _should_refresh(now_et: datetime) -> bool:
    # 分钟错开:%5==0 是 SMC 重算,%15==2 是挑战 bot;周日夜盘只有 1/10 分钟
    # 的调度(20:01 ET 那次刚好补一发周末局势检查)。
    if now_et.minute % 30 == 8:
        return True
    return now_et.weekday() == 6 and now_et.hour == 20 and now_et.minute == 1


def maybe_geo_refresh(prev: dict | None, now_et: datetime) -> dict | None:
    """Carry-forward off-tick; on-tick refresh + push. Never raises past itself."""
    if not _should_refresh(now_et):
        return prev
    try:
        fresh = get_geo_snapshot()
    except Exception as e:
        logger.warning(f"geo refresh failed: {e}")
        return prev
    if not fresh:
        return prev

    fresh = dict(fresh)                       # live_quote copy carries push state
    alerted = list((prev or {}).get("alerted") or [])
    hot = [it for it in fresh.get("items", [])
           if it.get("relevance") == "high" and it["key"] not in alerted]
    level_flip = bool(prev) and prev.get("risk_level") and \
        prev.get("risk_level") != fresh.get("risk_level")

    if prev is None:
        # 首次运行不推(避免部署即轰炸),只登记现有高影响条目
        alerted += [it["key"] for it in hot]
    elif hot or level_flip:
        head = f"{fresh.get('risk_cn','?')} {fresh.get('headline_cn','')}"
        lines = [head]
        if level_flip:
            lines.append(f"风险级别 {_RISK_CN.get(prev.get('risk_level'),'?')} → {fresh.get('risk_cn')}")
        for it in hot[:3]:
            lines.append(f"· [{it['track_cn']}] {it['title'][:70]}")
            if it.get("note_cn"):
                lines.append(f"  → {it['note_cn']}")
        if fresh.get("summary_cn"):
            lines.append(fresh["summary_cn"])
        from dashboard.intraday_smc import _ntfy
        pri = "high" if (level_flip or fresh.get("risk_level") == "alert") else "default"
        if _ntfy("QBTS Geo Radar", "\n".join(lines), tags="globe_with_meridians", priority=pri):
            alerted += [it["key"] for it in hot]

    # 只保留仍在雷达上的 key + 最近 100 个,防无限增长
    fresh["alerted"] = alerted[-100:]
    return fresh


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    snap = get_geo_snapshot(force_refresh=True)
    if not snap:
        print("geo snapshot failed")
    else:
        print(f"{snap['risk_cn']} — {snap['headline_cn']}")
        print(snap["summary_cn"])
        for it in snap["items"]:
            print(f"  [{it['track_cn']}/{it['relevance']}/{it['stance']}] {it['title'][:70]}")
            if it.get("note_cn"):
                print(f"    → {it['note_cn']}")
