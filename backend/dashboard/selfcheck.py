"""
全站 AI 系统自检(2026-07-16,用户要求把决策页的 system_notes 体检扩展到每个 tab)。

两层结构,确定性规则打底 + 一次 Haiku 语义层收尾:
  1. **规则层(免费)** — 把这套系统三周里真实踩过的坑写成硬检查:
     null/NaN 价格静默传染(07-15 dca)、宏观 actual==前值 的期错位回填(07-15 PPI)、
     同屏两个涨跌幅口径打架(07-15 量能段)、快照/复算过期、权重加不满 100 等。
  2. **Haiku 层(~$0.01/天)** — 每页一份压缩摘要喂给 Haiku 找规则想不到的
     跨字段矛盾。失败/无 key → 只出规则层,绝不阻断 publish。

产物挂在 dashboard_state.snapshot['site_check']:
  {"generated_at", "n_issues", "pages": {home/watch/dca/factors/challenge/spacex:
   [{"kind": 数据问题|改进建议, "note", "src": rule|ai}]}}
前端: 决策页汇总卡 + 每页 <SelfCheckCard page=…/> 只渲染自己的切片。
与决策自带的 system_notes 互补:那份是决策模型顺带审计当日 QBTS 数据,
这份是发布管道对全站六个页面的体检。
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_PAGES = ("home", "watch", "dca", "factors", "challenge", "spacex")
_MAX_PER_PAGE = 4


def _issue(kind: str, note: str, src: str = "rule") -> dict:
    return {"kind": kind, "note": note[:180], "src": src}


def _bad_num(v) -> bool:
    """None 或 NaN/inf — 静默传染类问题的统一判定。"""
    return v is None or (isinstance(v, float) and not math.isfinite(v))


def _age_hours(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 3600
    except Exception:
        return None


# ── 规则层:每页一个检查函数 ──────────────────────────────────────────────

def _check_home(snap: dict) -> list[dict]:
    out = []
    price = snap.get("price")
    if _bad_num(price) or (isinstance(price, (int, float)) and price <= 0):
        out.append(_issue("数据问题", f"QBTS 现价异常({price!r})——快照价格链路断了"))
    if not snap.get("decision"):
        out.append(_issue("数据问题", "今日 AI 决策缺失(decision=None)——检查 publish 日志"))
    # 宏观期错位回填(07-15 PPI 事故的残余守卫):已发布且 actual 恰好等于前值
    for e in (snap.get("macro") or {}).get("events", []):
        a, p = e.get("actual"), e.get("previous")
        if a and p and a == p and (e.get("hours_until") or 0) < 0 and e.get("forecast") not in (a, ""):
            out.append(_issue("数据问题",
                              f"宏观「{e.get('title')}」实际值({a})与前值完全相同且偏离预测"
                              f"({e.get('forecast')})——疑似期错位回填,需人工核实"))
    # 同屏两个涨跌幅口径(07-15 量能段事故的残余守卫)
    tc = snap.get("today_change")
    dr = ((snap.get("intraday") or {}).get("snapshot") or {}).get("day_ret")
    if isinstance(tc, (int, float)) and isinstance(dr, (int, float)) and abs(tc - dr) > 0.02:
        out.append(_issue("数据问题",
                          f"价格段今日 {tc*100:+.1f}% 与量能段当日 {dr*100:+.1f}% 相差"
                          f" >2pp——两处快照可能不同步"))
    return out


def _check_watch(scan: dict | None) -> list[dict]:
    if not scan:
        return [_issue("数据问题", "自选扫描 payload 缺失——/watch 页在吃旧数据")]
    out = []
    results = scan.get("results") or []
    if not results:
        out.append(_issue("数据问题", "自选扫描 0 个标的——篮子或抓取链路断了"))
    bad = [r.get("ticker") for r in results
           if _bad_num(r.get("price")) or (r.get("price") or 0) <= 0]
    if bad:
        out.append(_issue("数据问题", f"扫描卡价格为空/非法: {', '.join(map(str, bad))}"))
    age = _age_hours(scan.get("generated_at"))
    if age is not None and age > 36:
        out.append(_issue("数据问题", f"扫描数据已 {age:.0f} 小时未更新(>36h)"))
    return out


def _check_dca(dca: dict | None) -> list[dict]:
    if not dca:
        return [_issue("数据问题", "定投 payload 缺失——/dca 页在吃旧数据")]
    out = []
    cards = (dca.get("results") or []) + (dca.get("ballast_etfs") or [])
    # 07-15 事故同款:error 为空但核心字段是 null → NaN 静默传染
    bad = [r.get("ticker") for r in cards if not r.get("error")
           and (_bad_num(r.get("price")) or _bad_num(r.get("drawdown_pct"))
                or _bad_num(r.get("vs_200dma_pct")))]
    if bad:
        out.append(_issue("数据问题",
                          f"ETF 卡价格/回撤/200日线为空但无 error: {', '.join(map(str, bad))}"
                          "——NaN 静默传染(参见 07-15 dca 事故)"))
    w = sum(r.get("target_weight") or 0 for r in cards)
    if cards and abs(w - 100) > 1:
        out.append(_issue("数据问题", f"建议权重合计 {w}%,不是 100%"))
    return out


def _check_factors(snap: dict) -> list[dict]:
    rep = snap.get("strategy_replay")
    if not rep:
        return [_issue("数据问题", "策略复算(replay)缺失——/factors 页无战绩数据")]
    out = []
    if rep.get("as_of") and snap.get("as_of") and str(rep["as_of"]) < str(snap["as_of"])[:10]:
        out.append(_issue("数据问题",
                          f"策略复算停在 {rep['as_of']},快照已到 {str(snap['as_of'])[:10]}"
                          "——复算缓存未刷新"))
    for s in rep.get("strategies", []):
        st = s.get("stats") or {}
        wr = st.get("win_rate")
        if wr is not None and not (0 <= wr <= 1):
            out.append(_issue("数据问题", f"策略「{s.get('name')}」胜率越界: {wr}"))
        if _bad_num(st.get("ret_full")):
            out.append(_issue("数据问题", f"策略「{s.get('name')}」全期收益为空"))
    return out


def _check_challenge(ch: dict | None) -> list[dict]:
    if not ch:
        return []          # 挑战 bot 可整体关闭,缺失不算病
    out = []
    eq = ch.get("equity")
    if _bad_num(eq) or (isinstance(eq, (int, float)) and eq <= 0):
        out.append(_issue("数据问题", f"挑战账户 equity 异常({eq!r})"))
    # floor_line 可显式为 None(2026-07-21 用户拍板取消地板,跑到期)—— 此时不设下限,
    # 不能落回硬编码 4250 default,否则会对着"本就没有地板"的正常状态误报破线。
    floor = ch.get("floor_line") if "floor_line" in ch else ch.get("floor")
    if (floor is not None and isinstance(eq, (int, float)) and eq < floor
            and ch.get("status") not in ("halted", "stopped")):
        out.append(_issue("数据问题", f"equity ${eq:.0f} 已破 floor ${floor} 但状态未停手"))
    # 账本真恒等式(规则层,2026-07-22):pnl == equity − sleeve_start(始终成立,
    # 无论持仓与否)。07-22 Haiku 自创了 equity+pnl==sleeve_start 的错公式并误报
    # "未入账手续费"——确定性代数下沉规则层(同 07-16 跨页价格教训),LLM 不再管这条。
    pnl, start = ch.get("pnl"), ch.get("sleeve_start")
    if all(isinstance(v, (int, float)) for v in (eq, pnl, start)):
        if abs(pnl - (eq - start)) > 1.0:
            out.append(_issue("数据问题",
                              f"pnl({pnl:.2f}) ≠ equity({eq:.2f}) − sleeve_start({start:.0f})"
                              f",差 {abs(pnl - (eq - start)):.2f} —— 台账恒等式被破坏"))
    curve = ch.get("equity_curve") or []
    if curve:
        last = curve[-1]
        ts = (last.get("ts") or last.get("t")) if isinstance(last, dict) \
             else (last[0] if isinstance(last, (list, tuple)) and last else None)
        age = _age_hours(ts if isinstance(ts, str) else None)
        if age is not None and age > 96:
            out.append(_issue("数据问题", f"资金曲线已 {age/24:.0f} 天没有新点(bot 可能卡死)"))
    return out


def _check_spacex(sx: dict | None) -> list[dict]:
    if not sx:
        return [_issue("数据问题", "SpaceX payload 缺失——/spacex 页在吃旧数据")]
    out = []
    if not sx.get("decision"):
        out.append(_issue("改进建议", "SPCX 决策为 None(无 DEEPSEEK_API_KEY 或调用失败)"))
    age = _age_hours(sx.get("catalyst_asof"))
    if age is not None and age > 24 * 30:
        out.append(_issue("数据问题", "事件日历 catalyst_asof 超过 30 天未复核——解禁/财报日期需再验证"))
    return out


def _check_cross(snap: dict, scan: dict | None, sx: dict | None) -> list[tuple[str, dict]]:
    """跨页同票价格一致性(确定性,不托付给 LLM——毒测实证 Haiku 抓不稳这个)。
    同一 ticker 在两个页面价格相差 >2% → 双方页面各记一条。"""
    px: dict[str, dict[str, float]] = {}
    if isinstance(snap.get("price"), (int, float)) and snap["price"] > 0:
        px.setdefault("QBTS", {})["home"] = float(snap["price"])
    for r in (scan or {}).get("results") or []:
        if r.get("ticker") and isinstance(r.get("price"), (int, float)) and r["price"] > 0:
            px.setdefault(str(r["ticker"]), {})["watch"] = float(r["price"])
    sp = ((sx or {}).get("data") or {}).get("price")
    if isinstance(sp, (int, float)) and sp > 0:
        px.setdefault("SPCX", {})["spacex"] = float(sp)
    out: list[tuple[str, dict]] = []
    for tk, srcs in px.items():
        if len(srcs) < 2:
            continue
        vals = list(srcs.values())
        if min(vals) > 0 and max(vals) / min(vals) - 1 > 0.02:
            note = (f"{tk} 价格跨页打架: "
                    + " vs ".join(f"{p}=${v:,.2f}" for p, v in srcs.items())
                    + " ——同一票两处相差 >2%(参见 review-cross-source-consistency 教训)")
            for p in srcs:
                out.append((p if p in _PAGES else "home", _issue("数据问题", note)))
    return out


# ── Haiku 语义层 ─────────────────────────────────────────────────────────

_AI_PROMPT = """你是量化交易仪表盘的数据质检员。下面是六个页面数据的压缩摘要(JSON)。

字段语义(先读——把口径差异当 bug 是首日 4/4 全误报的教训):
- day_ret = 较昨收(含跳空缺口); intraday_ret = 较开盘(不含跳空)。两者本就不同,差值≈跳空。
- as_of = 行情数据的交易日(日期); generated_at = 发布时的墙钟时间(UTC)。收盘后发布,
  generated_at 晚于/跨日于 as_of 完全正常。
- catalyst_asof = 事件日历上次人工复核的日期,静态字段,30 天内都正常(有独立守卫)。
- 不同数据源的同一价格允许 ±0.1% 的舍入/时点差,不算矛盾。
- challenge 的恒等式只有两条,不许自创别的公式(07-22 曾自创 equity+pnl==sleeve_start
  误报"未入账手续费"):① pnl == equity − sleeve_start(永远成立,规则层已自动检查,
  你不用管)② 空仓时 equity == sleeve_cash;持仓时 equity == sleeve_cash + pos_value
  (pos_value 是持仓市值,digest 已直接给出)。pnl<0 只是浮亏/已实现亏损,不是数据矛盾。

只报你能说出【具体伤害】的矛盾。该报的例子:同一 ticker 在两个页面价格相差 >2%;
交易记录买入日期晚于卖出日期;负价格/胜率>100%/权重合计明显≠100;标记在场但敞口为 0;
equity 与 cash+持仓明显对不上。
宁缺勿滥:凡是能用口径/舍入/时区/缓存节奏解释的都不要报;拿不准就不报。
不要评论策略好坏,不要复述已在 known_issues 里的问题。
输出 JSON 数组(无 markdown 围栏),最多 4 条,没有就输出 []:
[{"page": "home|watch|dca|factors|challenge|spacex", "kind": "数据问题|改进建议", "note": "<中文一句话,引用具体数字>"}]"""


def _digest(snap: dict, scan, dca, ch, sx, known: dict) -> str:
    """每页抽最容易互相打架的字段,总量控制在 ~几 KB。"""
    def _f(v, nd=4):
        return round(v, nd) if isinstance(v, (int, float)) and math.isfinite(v) else v
    d = {
        "home": {
            "as_of": snap.get("as_of"), "price": _f(snap.get("price")),
            "today_change": _f(snap.get("today_change")),
            "intraday": (snap.get("intraday") or {}).get("snapshot"),
            "decision": {k: (snap.get("decision") or {}).get(k)
                         for k in ("action", "conviction", "entry", "stop", "target")},
            "macro_events": [{k: e.get(k) for k in ("date", "title", "forecast",
                                                    "previous", "actual", "hours_until")}
                             for e in (snap.get("macro") or {}).get("events", [])[:8]],
        },
        "watch": scan and {
            "generated_at": scan.get("generated_at"),
            "cards": [{k: _f(r.get(k)) for k in ("ticker", "price", "score", "zone")}
                      for r in (scan.get("results") or [])[:12]],
        },
        "dca": dca and {
            "etfs": [{k: _f(r.get(k)) for k in ("ticker", "price", "today_change", "pe",
                                                "drawdown_pct", "vs_200dma_pct",
                                                "target_weight", "error")}
                     for r in (dca.get("results") or []) + (dca.get("ballast_etfs") or [])],
        },
        "factors": {
            "as_of": (snap.get("strategy_replay") or {}).get("as_of"),
            "strategies": [{"name": s.get("name"), **(s.get("stats") or {})}
                           for s in (snap.get("strategy_replay") or {}).get("strategies", [])],
        },
        # 字段名对齐 challenge2.py 实际 schema(cash→sleeve_cash/floor→floor_line;
        # 07-17 自检误报'cash 为 null'就是这里映射错)
        "challenge": ch and {"equity": _f(ch.get("equity")),
                             "sleeve_cash": _f(ch.get("sleeve_cash")),
                             "pnl": _f(ch.get("pnl")),
                             # 空仓事实必须显式给出:缺它时 equity==cash+pnl<0 被误判
                             # "持仓未计入"(07-20 误报——空仓+已实现亏损本是正常状态)
                             "in_position": bool(ch.get("position")),
                             # 持仓市值直接给出,免得 LLM 拿 equity/cash 自创代数
                             "pos_value": (_f(ch["equity"] - ch["sleeve_cash"])
                                           if ch.get("position") and
                                           all(isinstance(ch.get(k), (int, float))
                                               for k in ("equity", "sleeve_cash"))
                                           else None),
                             "sleeve_start": _f(ch.get("sleeve_start")),
                             "cooldown_date": ch.get("cooldown_date"),
                             "status": ch.get("status"),
                             "floor_line": _f(ch.get("floor_line")),
                             "updated_at": ch.get("updated_at")},
        "spacex": sx and {
            "as_of": (sx.get("data") or {}).get("as_of"),
            "price": _f((sx.get("data") or {}).get("price")),
            "decision_action": (sx.get("decision") or {}).get("action"),
            "catalyst_asof": sx.get("catalyst_asof"),
        },
        "known_issues": {p: [i["note"][:60] for i in v] for p, v in known.items() if v},
    }
    return json.dumps(d, ensure_ascii=False, default=str)


def _ai_layer(digest: str) -> list[dict]:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return []
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=800,
            system=_AI_PROMPT,
            messages=[{"role": "user", "content": digest}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            text = text[4:] if text.startswith("json") else text
            text = text.rsplit("```", 1)[0]
        items = json.loads(text.strip())
        out = []
        for it in items[:6]:
            page = it.get("page")
            if page in _PAGES and it.get("note"):
                kind = it.get("kind") if it.get("kind") in ("数据问题", "改进建议") else "数据问题"
                out.append((page, _issue(kind, str(it["note"]), src="ai")))
        return out
    except Exception as e:
        logger.warning(f"selfcheck AI layer skipped: {e}")
        return []


# ── 入口 ─────────────────────────────────────────────────────────────────

def build_site_check(snap: dict, scan: dict | None = None, dca: dict | None = None,
                     challenge: dict | None = None, spacex: dict | None = None) -> dict:
    pages: dict[str, list[dict]] = {
        "home":      _check_home(snap or {}),
        "watch":     _check_watch(scan),
        "dca":       _check_dca(dca),
        "factors":   _check_factors(snap or {}),
        "challenge": _check_challenge(challenge),
        "spacex":    _check_spacex(spacex),
    }
    for page, iss in _check_cross(snap or {}, scan, spacex):
        pages[page].append(iss)
    try:
        for page, iss in _ai_layer(_digest(snap or {}, scan, dca, challenge, spacex, pages)):
            pages[page].append(iss)
    except Exception as e:
        logger.warning(f"selfcheck AI layer failed: {e}")
    pages = {p: v[:_MAX_PER_PAGE] for p, v in pages.items()}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_issues": sum(len(v) for v in pages.values()),
        "pages": pages,
    }
