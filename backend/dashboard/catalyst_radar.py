"""
📣 公司催化剂雷达 — QBTS 自身消息面的实时监测 + ntfy 推送。

Why (2026-07-27 的教训): QBTS 单日 +20.4%(收 $19.51,4716万股=2.6×天量),驱动力是
AT&T 签约扩大 D-Wave 量子计算在其全网运维的使用 + 同日转板纳斯达克。仪表盘上**没有
任何一个机械信号能提前或及时看见这件事** —— SMC/POC/%R/regime 全是价格派生量,
新闻模块(news.py)一天只在 09:00 ET 例行 publish 跑一次。等决策看到它时,跳空已经走完。

这个模块补的就是这段:照 `geopolitics.py` 同一套架构(它已经证明能用),但盯的是
**公司自身 + 板块同行**的催化剂,而不是地缘局势。

  company — D-Wave/QBTS 自身:商用合同、订单、产品发布、融资、管理层、上市地变更
  sector  — 量子板块同行(IONQ/RGTI/量子计算行业),板块性消息会整体带动 QBTS

Source: Google News RSS search(免费无 key,`when:1d` 窗口 —— 比地缘雷达的 2d 窄,
催化剂讲时效,48h 前的消息早就在价格里了)。一次 Haiku 调用做逐条 impact/direction/
中文注 + 整体 impact_level。

成本闸(同 geopolitics): RSS 免费随便拉;Haiku 只在**头条集合真的变了**或上次分析
>4h 才跑。所以平静日一天几乎不花钱,出大事那几跳才调模型。

推送纪律 —— 这里比地缘雷达更严,因为公司消息的「同一件事反复改写标题」比地缘更凶
(一条 PR 会被 20 家媒体转,每家标题都不一样 → md5 key 全不同 → 每跳推一条)。
2026-07-10 那个「一晚 20 条轰炸」就是这么来的。四道闸(③④是 2026-07-29 补的 ——
用户一天收到 3 条同一件 AT&T 的推送,①②对那两条天生无效):
  ① **故事级去重**(不是标题级): 剔掉无区分度的词后,与已推标题共享任一专名 =
     同一件事,静默登记不推。这才是根治 —— 光靠冷却时间会把真·突发也一起憋住。
  ② 冷却: 升到 breaking 立推;同级别的**不同**故事 ≥45min;降级根本不推
     (公司消息「没新消息了」不是一个值得响铃的事件,与地缘缓和不同)。
  ③ **要因不要果**(代码层): 「Why ... Stock Surged Today」「Should You Buy」这类
     描述价格结果的标题一律不推。提示词里早写了这条,但 Haiku 照样判 high ——
     按 2026-07-22 的教训,规则必须落在代码里(`is_price_result`)。
  ④ **无故事身份 = 只可能是转述**: 剔掉无区分度的词后专名集合为空的标题,
     连自己在讲什么都说不出来,不可能是一件新催化剂。

零决策权: 只进 snapshot + 决策 prompt 作事件背景,**不进 edge** —— news.py 已经占了
`_NEWS_WEIGHT=0.15`,同一个消息面计两次就是自欺。UNPROVEN,8/15 与其他信号同堂受审。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
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

_CACHE_PATH = Path(__file__).parent.parent / "data" / "cache" / "catalyst_radar.json"
_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

_FRESH_SECONDS     = 5 * 60      # 缓存 <5min 直接用(盘中节拍 10min,所以每跳都会真拉)
_REANALYZE_SECONDS = 4 * 3600    # 即便无新头条,分析 >4h 也重跑一次 Haiku
_PER_TRACK_LIMIT   = 10
_PROMPT_CAP        = 18          # 喂给 Haiku 的条数上限

# (track, 中文标签, Google News 检索式) — `when:1d` 限最近 24h
_TRACKS = [
    ("company", "公司",
     '"D-Wave Quantum" OR "D-Wave" QBTS OR QBTS stock'),
    ("sector", "板块同行",
     '"quantum computing" stock OR IonQ OR Rigetti OR "quantum computing" contract'),
]

_IMPACT_CN = {"breaking": "🔴 重大催化", "watch": "🟡 有消息", "quiet": "🟢 无事"}
_LEVEL_RANK = {"quiet": 0, "watch": 1, "breaking": 2}

# 与 geopolitics 同一处理:Haiku 挂了又无缓存时不伪造 "watch",标 unknown。
_UNKNOWN_LEVEL = "unknown"
_UNKNOWN_CN    = "⚪️ 分级不可用"
_DIR_CN = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}

_PUSH_COOLDOWN_SAME = 45 * 60    # 同级别的**不同**故事:距上次推送 ≥45min

# 故事级去重靠「共享的**罕见实体**」,不靠整体词重合率 —— 实测两条讲同一笔 AT&T
# 交易的标题("D-Wave Soars on AT&T Deal, NYSE Uplisting" vs "QBTS Stock Pops as
# AT&T Expands Partnership With D-Wave")整体 Jaccard 只有 0.2:同一件事的不同报道
# 共享的是**专名**(AT&T),动词和框架全都不一样。所以判据改成:剔掉所有"每条 QBTS
# 新闻都有"的词之后,只要还共享至少一个专名,就当同一件事。
_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "as",
    "at", "by", "with", "its", "it", "after", "from", "this", "that", "be",
    "says", "said", "new", "up", "down", "amid", "into", "over", "why", "how",
    "what", "just", "here", "more", "than", "not", "but", "can", "will", "has",
}
# 这些词在每条 QBTS 新闻里都出现(公司名/代码/行业)或纯属通用财经动词/名词 —— 对
# "是不是同一件事"零区分度,必须排除,否则任意两条 QBTS 新闻都会被判成同一故事。
_UBIQUITOUS = {
    "qbts", "wave", "dwave", "quantum", "computing", "inc", "corp", "nasdaq",
    "stock", "stocks", "shares", "share", "price", "market", "investors",
    "soars", "soar", "pops", "pop", "rises", "rise", "surges", "surge",
    "jumps", "jump", "climbs", "climb", "rallies", "rally", "gains", "gain",
    "falls", "fall", "drops", "drop", "sinks", "slides", "tumbles",
    "deal", "deals", "partnership", "agreement", "expands", "expand",
    "boost", "boosting", "buy", "sell", "hold", "today", "week", "year",
}


def _item_key(title: str) -> str:
    return hashlib.md5(title.lower().strip()[:80].encode("utf-8")).hexdigest()[:10]


def _stem(w: str) -> str:
    """极简词干:只砍 ed/ing/s。用来对齐 `_UBIQUITOUS` —— 枚举屈折形是填不完的坑,
    2026-07-29 就栽在表里有 surge/surges 却没有 **surged**,于是
    「Why D-Wave Quantum Stock Surged Today」的故事身份变成了 {surged},
    与「Soars on AT&T Deal」零交集 → 同一件事推了两遍。"""
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)]
    return w


# 「描述价格结果」的标题模式 —— 提示词里已经写了"要因不要果",但 LLM 不照做
# (2026-07-29 实测把「Why ... Stock Surged Today」判成 high)。按 2026-07-22
# 的教训:**提示词里的规则不会自执行,护栏要落在代码里。**
_PRICE_RESULT_RX = re.compile(
    r"(why\s+.*\b(surg|soar|jump|plung|tumbl|slid|rall|pop|climb|sink|drop|fall)"
    r"|\b(surged|soared|jumped|plunged|tumbled|slid|rallied|popped|climbed|sank|sunk)\b"
    r"|should\s+you\s+(buy|sell|hold)"
    r"|\bis\s+it\s+too\s+late\b"
    r"|\b(moved|moves)\s+a\s+\w+\s+stock\b"
    r"|\bstock\s+(is\s+)?(up|down)\s+\d"
    r"|\b\d+\s+(quantum\s+)?stocks?\s+to\s+(buy|watch)\b)", re.I)


def is_price_result(title: str) -> bool:
    """标题只在描述"股价怎么动了"或"该不该买" → 是果不是因,不配 high。"""
    return bool(_PRICE_RESULT_RX.search(title or ""))


def _entities(title: str) -> set[str]:
    """标题 → 专名集合(故事身份)。

    `&` 保留在词内 —— 否则 "AT&T" 会被切成 "at"+"t" 两个垃圾 token 双双出局,
    而它恰恰是那条新闻的故事身份本身(实测踩过)。
    比对前过词干,免得 surge/surged 这类屈折差异被当成两个不同的故事身份。
    """
    words = re.findall(r"[a-z0-9&]+", title.lower())
    out = set()
    for w in words:
        if len(w) < 3 or w in _STOPWORDS:
            continue
        s = _stem(w)
        if w in _UBIQUITOUS or s in _UBIQUITOUS or _stem(w) in {_stem(u) for u in _UBIQUITOUS}:
            continue
        out.add(s)
    return out


def _same_story(title: str, seen_titles: list[str]) -> bool:
    """与已推标题共享任一专名 → 同一件事的另一种写法,不重复响铃。

    公司新闻的经验规则:同一天里两条都点名同一个罕见专名(AT&T / 某国防部合同 /
    某可转债规模),几乎必然在讲同一件事。宁可偶尔漏推一条真·新消息,也不要把
    一条 PR 的 12 家转载各推一遍(2026-07-10 一晚 20 条的教训)。
    """
    t = _entities(title)
    if not t:
        return False
    return any(t & _entities(old) for old in seen_titles)


def _fetch_track(track: str, track_cn: str, query: str) -> list[dict]:
    q = urllib.parse.quote(f"{query} when:1d")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        root = ET.fromstring(resp.read())

    items = []
    for it in root.findall(".//item")[:_PER_TRACK_LIMIT]:
        title = (it.findtext("title") or "").strip()
        source = (it.findtext("source") or "").strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate") or "").astimezone(timezone.utc)
            published = pub.isoformat()[:16]
            age_h = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
        except Exception:
            published, age_h = "", None
        if not title:
            continue
        items.append({
            "key":       _item_key(title),
            "track":     track,
            "track_cn":  track_cn,
            "title":     title[:160],
            "source":    source[:40],
            "published": published,
            "age_h":     round(age_h, 1) if age_h is not None else None,
            "url":       (it.findtext("link") or "")[:400],
        })
    return items


def _fetch_all_tracks() -> list[dict]:
    items: list[dict] = []
    for track, track_cn, query in _TRACKS:
        try:
            items.extend(_fetch_track(track, track_cn, query))
        except Exception as e:
            logger.warning(f"catalyst RSS fetch failed for {track}: {e}")
    seen, dedup = set(), []
    for it in items:
        if it["key"] in seen:
            continue
        seen.add(it["key"])
        dedup.append(it)
    dedup.sort(key=lambda x: x["published"], reverse=True)
    return dedup[:_PROMPT_CAP]


_ANALYSIS_PROMPT = """你是给 QBTS(D-Wave Quantum,高贝塔量子股,通过 2× 杠杆 ETF QBTX/QBTZ 交易)盯消息面的分析师。
你的唯一任务:从一堆头条里挑出**真能驱动股价的催化剂**,并说清它意味着什么。

对下面每条新闻标题,输出:
  - impact    : "high" | "medium" | "low" — 对 QBTS 股价的驱动力。
      high   = 公司层面的硬事件:商用合同/大客户签约、重大订单、产品或技术突破、
               财报、融资或增发、并购、上市地/指数变更、监管处罚、管理层变动;
               或板块级的重大共振(同行拿下标志性合同、国家级量子预算落地)。
      medium = 有信息量但不改变基本面:分析师评级、板块轮动评论、同行一般性进展。
      low    = 纯观点/复述/旧闻改写/「该不该买」这类内容农场稿。
  - direction : "bullish" | "bearish" | "neutral" — 对 QBTS 股价方向。
  - note_cn   : ≤40字中文,说清「这条对股价意味着什么」,要点名具体主体和数字。

然后给整体:
  - impact_level : "breaking"(有 high 级新催化剂,今日价格可能被它主导)
                 | "watch"(有值得注意的消息,但不足以主导价格)
                 | "quiet"(没有真катализ,都是噪音稿)。
  - headline_cn  : ≤30字,一句话概括当前最重要的那条(没有就写「无重大消息」)。
  - summary_cn   : 2-3句中文:①最重要的消息是什么 ②对 QBTS 的具体含义(方向+幅度量级+
                   该防什么)。没有重大消息就直说「消息面平静」,不要硬凑。

规则:
- 同一件事被多家媒体转载,只给最原始最具体的一条 high,其余降级为 low(重复报道不是新催化剂)。
- 「XX 股票暴涨/暴跌」这种**描述价格结果**的标题不是催化剂,是结果 —— 一律 low,
  除非它同时给出了原因。我们要的是因,不是果。
- 内容农场稿(Zacks/Motley Fool 的「3 只该买的量子股」)一律 low。
- 不确定就保守(medium 而非 high)。宁可漏推,不可乱响铃。

只输出 JSON(无 markdown 围栏):
{"impact_level": "...", "headline_cn": "...", "summary_cn": "...",
 "items": [{"impact": "...", "direction": "...", "note_cn": "..."}, ...]}
items 数组与输入同序同长。"""


def _analyze(items: list[dict]) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    lines = "\n".join(
        f"{i+1}. [{it['track_cn']}] ({it['published'][5:16]}"
        + (f", {it['age_h']}h前" if it.get("age_h") is not None else "")
        + f") {it['title']} — {it['source']}"
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


def get_catalyst_snapshot(force_refresh: bool = False) -> dict | None:
    """Public entry. Returns the radar payload (None only if everything failed)."""
    cached = None
    if _CACHE_PATH.exists():
        try:
            cached = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            cached = None

    now = time.time()
    if cached and not force_refresh and now - cached.get("_ts", 0) < _FRESH_SECONDS:
        return cached["payload"]

    try:
        items = _fetch_all_tracks()
    except Exception as e:
        logger.warning(f"catalyst RSS fetch failed entirely: {e}")
        return cached["payload"] if cached else None
    if not items:
        return cached["payload"] if cached else None

    # 头条没变且分析还新鲜 → 跳过 Haiku(只更新时间戳)
    if cached and not force_refresh:
        old_keys = {it["key"] for it in cached["payload"].get("items", [])}
        if (all(it["key"] in old_keys for it in items)
                and now - cached.get("_analyzed", 0) < _REANALYZE_SECONDS):
            cached["_ts"] = now
            _CACHE_PATH.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
            return cached["payload"]

    try:
        ai = _analyze(items)
        ratings = ai.get("items") or []
        for it, r in zip(items, ratings):
            it["impact"]    = r.get("impact", "low")
            it["direction"] = r.get("direction", "neutral")
            it["note_cn"]   = str(r.get("note_cn", ""))[:60]
        for it in items[len(ratings):]:
            it.update({"impact": "low", "direction": "neutral", "note_cn": ""})
        level = ai.get("impact_level") if ai.get("impact_level") in _IMPACT_CN else "watch"
        payload = {
            "as_of":        datetime.now(timezone.utc).isoformat(),
            "impact_level": level,
            "impact_cn":    _IMPACT_CN[level],
            "headline_cn":  str(ai.get("headline_cn", ""))[:60],
            "summary_cn":   str(ai.get("summary_cn", ""))[:400],
            "items":        items,
        }
    except Exception as e:
        logger.warning(f"catalyst Haiku analysis failed: {e}")
        if cached:
            return cached["payload"]
        # 级别标 unknown(不是 watch),**且这一份绝不写缓存** —— 写了会被上面
        # 「头条没变 + _analyzed 还新鲜」那条捷径认成有效分析,一次瞬时 API
        # 失败就把雷达焊死 4 小时。不写 = 下一跳(10min 后)自动重试。
        for it in items:
            it.update({"impact": "medium", "direction": "neutral", "note_cn": ""})
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "impact_level": _UNKNOWN_LEVEL, "impact_cn": _UNKNOWN_CN,
            "headline_cn": "AI 分级不可用,仅原始头条",
            "summary_cn": "", "items": items,
        }

    _CACHE_PATH.write_text(json.dumps(
        {"_ts": now, "_analyzed": now, "payload": payload}, ensure_ascii=False),
        encoding="utf-8")
    return payload


# ── 盘中刷新 + ntfy 推送(QuoteFunction 每分钟调,10min 节拍)────────────────


def _should_refresh(now_et: datetime) -> bool:
    """分钟槽位 %10==3 → 3/13/23/33/43/53 分。

    错开所有既有槽位:%5==0(SMC 重算)、%5==4(游击战出场)、%15==2(挑战 bot)、
    %30==8(地缘雷达)。这几个分钟对 5 取模恒为 3,对 15 取模 ∈{3,8,13},
    对 30 取模 ∈{3,13,23} —— 一个都不撞。
    """
    return now_et.minute % 10 == 3


def _last_good(prev: dict | None) -> str | None:
    """上一次**真实**分级出来的级别(跳过 unknown 那些跳)。见 geopolitics 同名函数。"""
    p = prev or {}
    lg = p.get("last_good_level")
    if lg:
        return lg
    il = p.get("impact_level")
    return il if il and il != _UNKNOWN_LEVEL else None


def maybe_catalyst_refresh(prev: dict | None, now_et: datetime) -> dict | None:
    """Carry-forward off-tick; on-tick refresh + push. Never raises past itself."""
    if not _should_refresh(now_et):
        return prev
    try:
        fresh = get_catalyst_snapshot()
    except Exception as e:
        logger.warning(f"catalyst refresh failed: {e}")
        return prev
    if not fresh:
        return prev

    fresh = dict(fresh)
    if fresh.get("impact_level") == _UNKNOWN_LEVEL:
        # 这一跳没有判断:条目的 impact 全是兜底填的,不能拿来挑 hot;级别也
        # 不能参与 escalated 比较。push 状态 + 最后一次真实级别原样带走。
        fresh["alerted"]         = list((prev or {}).get("alerted") or [])
        fresh["alerted_titles"]  = list((prev or {}).get("alerted_titles") or [])
        fresh["last_push_ts"]    = float((prev or {}).get("last_push_ts") or 0)
        fresh["last_good_level"] = _last_good(prev)
        return fresh

    alerted = list((prev or {}).get("alerted") or [])
    alerted_titles = list((prev or {}).get("alerted_titles") or [])
    last_push = float((prev or {}).get("last_push_ts") or 0)
    now_ts = time.time()

    prev_level = _last_good(prev)          # 跳过 unknown,拿最后一次真实级别比
    cur_level = fresh.get("impact_level")
    escalated = bool(prev) and prev_level and \
        _LEVEL_RANK.get(cur_level, 0) > _LEVEL_RANK.get(prev_level, 0)

    # 候选 = high 影响 且 key 没推过 且 不是已推故事的改写版 且 不是"果" 且 有故事身份
    #
    # 最后那条(`_entities` 非空)是第三道闸,专治前两道天生管不着的一类:
    # 「Why D-Wave Quantum Stock Surged Today」这种转述稿**通篇不提 AT&T**,
    # 剔掉无区分度的词之后专名集合是**空的** —— 一条自己都说不出在讲什么的标题,
    # 不可能是一件新的催化剂,只可能是对已发生之事的复述。
    # (2026-07-29:用户一天收到 3 条同一件 AT&T 的推送,其中两条就是这样溜过去的。)
    hot = [it for it in fresh.get("items", [])
           if it.get("impact") == "high"
           and not is_price_result(it.get("title", ""))     # 代码层护栏,不信 LLM
           and _entities(it.get("title", ""))               # 无故事身份 = 只可能是转述
           and it["key"] not in alerted
           and not _same_story(it["title"], alerted_titles)]


    def _register(batch):
        for it in batch:
            alerted.append(it["key"])
            alerted_titles.append(it["title"])

    if prev is None:
        # 首次运行不推(避免部署即轰炸),只登记现有 high 条目
        _register(hot)
    elif hot:
        # 升级到 breaking 立推;否则同级别不同故事等 45min。
        # 降级不推 —— 公司消息「没新消息了」不值得响铃(与地缘缓和不同)。
        cooldown = 0 if escalated else _PUSH_COOLDOWN_SAME
        if now_ts - last_push < cooldown:
            _register(hot)                    # 静默登记,卡片照常更新
        else:
            lines = [f"{fresh.get('impact_cn','?')} {fresh.get('headline_cn','')}"]
            for it in hot[:3]:
                d = _DIR_CN.get(it.get("direction", "neutral"), "")
                age = f"{it['age_h']}h前 " if it.get("age_h") is not None else ""
                lines.append(f"· [{it['track_cn']}/{d}] {age}{it['title'][:70]}")
                if it.get("note_cn"):
                    lines.append(f"  → {it['note_cn']}")
            if fresh.get("summary_cn"):
                lines.append(fresh["summary_cn"])
            lines.append("(消息面雷达·零决策权,不构成交易信号)")
            from dashboard.notify import push as _ntfy
            pri = "high" if cur_level == "breaking" else "default"
            # 标题保持 ASCII —— HTTP header 是 latin-1,中文放 UTF-8 正文
            if _ntfy("QBTS Catalyst Radar", "\n".join(lines),
                     tags="loudspeaker", priority=pri):
                _register(hot)
                last_push = now_ts

    fresh["alerted"] = alerted[-100:]
    fresh["alerted_titles"] = alerted_titles[-40:]      # 标题比 key 占地方,少留些
    fresh["last_push_ts"] = last_push
    fresh["last_good_level"] = cur_level
    return fresh


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    snap = get_catalyst_snapshot(force_refresh=True)
    if not snap:
        print("catalyst snapshot failed")
    else:
        print(f"{snap['impact_cn']} — {snap['headline_cn']}")
        print(snap["summary_cn"], "\n")
        for it in snap["items"]:
            mark = {"high": "★", "medium": "·", "low": " "}.get(it.get("impact"), " ")
            print(f" {mark} [{it['track_cn']}/{it.get('impact')}/{it.get('direction')}] "
                  f"{it['title'][:75]}")
            if it.get("note_cn"):
                print(f"     → {it['note_cn']}")
