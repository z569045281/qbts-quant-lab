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

Push rate limit (2026-07-10, after a 20-push night): a sustained hot story
churns re-worded headlines every fetch → new md5 keys → a push per tick.
So pushes now cool down: level ESCALATION is immediate, same-level fresh
items wait ≥3h since the last push (silently registered meanwhile — the
dashboard card still updates live), de-escalation waits ≥1h (damps
alert↔watch flapping). `last_push_ts` rides in the live_quote payload.
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
_LEVEL_RANK = {"calm": 0, "watch": 1, "alert": 2}

# Haiku 挂了、又没有缓存可退时的降级级别。**刻意不是 "watch"**:一个伪造的
# 🟡 观察会被 decision.py 当真读进提示词,也会污染任何拿级别做的统计
# (2026-07-31 回测这条链路时发现)。"unknown" = 「本模块这一跳没有判断」,
# 前端画灰、决策提示词整块跳过、推送静默。
_UNKNOWN_LEVEL = "unknown"
_UNKNOWN_CN    = "⚪️ 分级不可用"

_PUSH_COOLDOWN_SAME = 3 * 3600   # 同级别的持续报道:距上次推送 ≥3h 才再推
_PUSH_COOLDOWN_DOWN = 1 * 3600   # 降级(缓和):≥1h,防 alert↔watch 横跳刷屏

# 🆕 2026-08-13 用户点单「治本」:**同一条线(track)的冷却**。
#
# 起因:08-13 十一小时里推了 4 条,全是「🟡 观察」,全是美伊谈判/霍尔木兹海峡
# 这同一件事 —— 03:08 / 07:08 / 10:38 / 14:08。查下来**去重和频控都在按设计工作**:
# 每条都是不同的 RSS 条目(`alerted` 认的是单条 key),间隔也都超过 3h 冷却。
# 病根是**去重粒度错了**:它认「这条新闻推没推过」,不认「这件事讲没讲过」。
# 一个主题一天有四篇不同报道,对系统就是四条新消息,对人就是同一件事讲四遍。
#
# 治本 = 把粒度从「单条新闻」提到「track」。同一条线在冷却期内只响一次,
# 后续同 track 的条目静默登记进 alerted,卡片照常更新。
# ⚠️ **升级(escalated)不受此限** —— 局势真从观察变升温时必须立刻响,
# 否则这个补丁会把最该收到的那一条也吃掉。
_PUSH_COOLDOWN_TRACK = 12 * 3600


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
 "items": [{"i": 1, "relevance": "...", "stance": "...", "note_cn": "..."}, ...]}
**每条必须带 `i` = 输入里那条的编号**(从 1 开始),一条都不能漏、不能改序。"""


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
        # ⚠️ 按**回显的编号 i** 对齐,不按位置(2026-08-13)。原来是
        # `zip(items, ratings)` 纯按位置配对,而「同序同长」只写在 prompt 里、
        # 代码零校验 —— Haiku 少返一条/并一条/换个序,后面全部错位一格而无人知晓。
        # 08-13 那条推送实测错位 3 格:第 11 条的标题配上了第 14 条的解读,
        # 而 `relevance` 跟着错位 → **推送选中的条目本身就是错的**。
        by_i = {}
        for r in ratings:
            try:
                by_i[int(r["i"]) - 1] = r
            except (KeyError, TypeError, ValueError):
                continue
        for idx, it in enumerate(items):
            r = by_i.get(idx) or {}          # 没回显到的一律降级,不猜
            it["relevance"] = r.get("relevance", "low")
            it["stance"]    = r.get("stance", "neutral")
            it["note_cn"]   = str(r.get("note_cn", ""))[:60]
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
        # 无缓存也别全黑:给未分级的原始头条,级别标 unknown(不是 watch)。
        # **且这一份绝不写缓存** —— 写了会被上面「头条没变 + _analyzed 还新鲜」
        # 那条捷径认成有效分析,于是一次瞬时 API 失败能把雷达焊死 6 小时,
        # 哪怕下一跳 Haiku 早就恢复了。不写 = 下一跳自动重试。
        for it in items:
            it.update({"relevance": "medium", "stance": "neutral", "note_cn": ""})
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "risk_level": _UNKNOWN_LEVEL, "risk_cn": _UNKNOWN_CN,
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


def _last_good(prev: dict | None) -> str | None:
    """上一次**真实**分级出来的级别(跳过 unknown 那些跳)。

    `last_good_level` 是这次改动新加的键;老 payload 没有 → 退回 risk_level,
    但要是它本身就是 unknown(旧版本的 payload 不会有,只可能是同版本前一跳)
    就当没有,免得 unknown 参与 flip 比较。
    """
    p = prev or {}
    lg = p.get("last_good_level")
    if lg:
        return lg
    rl = p.get("risk_level")
    return rl if rl and rl != _UNKNOWN_LEVEL else None


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
    if fresh.get("risk_level") == _UNKNOWN_LEVEL:
        # 这一跳没有判断 → 卡片照常显示原始头条,但推送全部静默:所有条目的
        # relevance 都是兜底填的,拿它当「新高影响条目」会响一堆假警报。
        # push 状态 + 最后一次真实级别原样带走,好让下一跳恢复后拿真级别比
        # flip(否则 unknown→alert 会被算成「升级」,凭空推一条)。
        fresh["alerted"]        = list((prev or {}).get("alerted") or [])
        fresh["last_push_ts"]   = float((prev or {}).get("last_push_ts") or 0)
        # ⚠️ 主题冷却也必须原样带走。live_quote 是整块覆写的,这里漏一个键
        # 就等于把冷却清零 → 下一跳同一条线立刻重响(2026-07-31 事件日同一个坑)。
        fresh["pushed_tracks"]  = dict((prev or {}).get("pushed_tracks") or {})
        fresh["last_good_level"] = _last_good(prev)
        return fresh

    alerted = list((prev or {}).get("alerted") or [])
    last_push = float((prev or {}).get("last_push_ts") or 0)
    pushed_tracks = dict((prev or {}).get("pushed_tracks") or {})
    now_ts = time.time()
    hot = [it for it in fresh.get("items", [])
           if it.get("relevance") == "high" and it["key"] not in alerted]
    prev_level = _last_good(prev)          # 跳过 unknown,拿最后一次真实级别比
    cur_level = fresh.get("risk_level")
    level_flip = bool(prev) and prev_level and prev_level != cur_level
    escalated = level_flip and \
        _LEVEL_RANK.get(cur_level, 0) > _LEVEL_RANK.get(prev_level, 0)

    # 主题级去重(见 _PUSH_COOLDOWN_TRACK)。升级时不过滤 —— 那一条必须响。
    if not escalated:
        muted = [it for it in hot
                 if now_ts - float(pushed_tracks.get(it.get("track"), 0)) < _PUSH_COOLDOWN_TRACK]
        if muted:
            alerted += [it["key"] for it in muted]   # 静默登记,卡片照常显示
            hot = [it for it in hot if it not in muted]

    if prev is None:
        # 首次运行不推(避免部署即轰炸),只登记现有高影响条目
        alerted += [it["key"] for it in hot]
    elif hot or level_flip:
        # 频控:升级立推;降级 ≥1h;同级别持续报道 ≥3h(冷却中静默登记,
        # 卡片照常盘中更新 — 推送只做「注意力触发」,不当新闻流)
        cooldown = 0 if escalated else \
            (_PUSH_COOLDOWN_DOWN if level_flip else _PUSH_COOLDOWN_SAME)
        if now_ts - last_push < cooldown:
            alerted += [it["key"] for it in hot]
        else:
            head = f"{fresh.get('risk_cn','?')} {fresh.get('headline_cn','')}"
            lines = [head]
            if level_flip:
                lines.append(f"风险级别 {_RISK_CN.get(prev_level,'?')} → {fresh.get('risk_cn')}")
            for it in hot[:3]:
                lines.append(f"· [{it['track_cn']}] {it['title'][:70]}")
                if it.get("note_cn"):
                    lines.append(f"  → {it['note_cn']}")
            if fresh.get("summary_cn"):
                lines.append(fresh["summary_cn"])
            from dashboard.notify import push as _ntfy
            pri = "high" if (escalated and cur_level == "alert") else "default"
            if _ntfy("QBTS Geo Radar", "\n".join(lines), tags="globe_with_meridians", priority=pri):
                alerted += [it["key"] for it in hot]
                last_push = now_ts
                for it in hot:                       # 记下这条线刚响过
                    pushed_tracks[it.get("track") or "?"] = now_ts

    # 只保留仍在雷达上的 key + 最近 100 个,防无限增长
    fresh["alerted"] = alerted[-100:]
    fresh["last_push_ts"] = last_push
    fresh["pushed_tracks"] = pushed_tracks
    fresh["last_good_level"] = cur_level
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


if __name__ == "__main__":
    # 自检:锁住 2026-08-13 那两个失效模式(用户 11 小时收到 4 条同主题推送)。
    import time as _t

    # ① 主题冷却:同一 track 在冷却期内不该再进 hot,但必须静默登记进 alerted
    now = _t.time()
    prev = {"alerted": [], "pushed_tracks": {"iran": now - 3600},   # 伊朗 1 小时前刚推过
            "last_push_ts": now - 4 * 3600, "risk_level": "watch",
            "last_good_level": "watch"}
    hot = [{"key": "k1", "track": "iran"}, {"key": "k2", "track": "quantum"}]
    pushed = dict(prev["pushed_tracks"])
    muted = [it for it in hot
             if now - float(pushed.get(it["track"], 0)) < _PUSH_COOLDOWN_TRACK]
    kept = [it for it in hot if it not in muted]
    assert [it["key"] for it in muted] == ["k1"], f"伊朗该被静音,实际 {muted}"
    assert [it["key"] for it in kept] == ["k2"], f"量子该留下,实际 {kept}"

    # ② 按 i 对齐:LLM 漏返一条时,缺的那条降级为 low,**其余不许错位**
    items = [{"title": f"t{n}"} for n in range(4)]
    ratings = [{"i": 1, "relevance": "high", "note_cn": "第一条"},
               {"i": 4, "relevance": "high", "note_cn": "第四条"}]   # 2、3 缺失
    by_i = {}
    for r in ratings:
        try:
            by_i[int(r["i"]) - 1] = r
        except (KeyError, TypeError, ValueError):
            continue
    got = [(by_i.get(i) or {}).get("note_cn", "") for i in range(4)]
    assert got == ["第一条", "", "", "第四条"], f"错位了: {got}"
    # 同样的输入用旧的 zip 逻辑会把「第四条」贴到第 2 条上 —— 正是 08-13 那个 bug
    old = [r.get("note_cn") for _, r in zip(items, ratings)] + ["", ""]
    assert old[1] == "第四条", "旧逻辑的错位没复现,断言写错了"

    print("geopolitics self-check OK(主题冷却 + 按 i 对齐,均已锁住)")
