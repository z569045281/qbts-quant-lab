"""📋 板块读数台账 —— 给决策 prompt 里「有发言权但没人记分」的那三分之二记账。

出身(2026-07-31,用户点单"那三分之二要开始记分"):噪音审计数出来的账 ——
决策 prompt 每天一万字、26 个板块喂给 LLM,其中只有 8 个源在 `audit.py` §1 有
命中率记分卡(edge 元模型的那 8 个)。剩下的 SMC 结构 / playbook / NW 包络 /
成交量画像 / 日内画像 / 空头动向 / 地缘雷达 / SEC 三件套 —— **天天在影响判断,
从来没人问过它们对不对**。

这个模块只做一件事:**每天把每个板块的表态原样存进决策台账**,之后用与
`bold_call` 完全同一套多视界评分(`journal._horizon_grades`)给它们打分。

━━ 六条纪律(预注册,看到结果后不得更改)━━━━━━━━━━━━━━━━━━━━

① **零决策权。** 不进 edge、不进 prompt、不进任何闸门。它是记分员,不是球员。
   记分员下场踢球 = 自证预言(与 `dip_buy.py` 同一条出身纪律)。

② **表态怎么导出,今天就写死。** 每个板块的 stance 规则写在下面 `_RULES` 里,
   **一律读板块自己已经算好的 `signal` / `stance` 字段,不新造判据**。
   看到结果之后改导出规则 = 事后套线,这是 `audit.py` 从第一天就预注册要防的。

③ **没有方向的板块就老实写 `None`,不许硬凑一个方向。**
   宏观日历、财报日历、波动率 regime、事件日熔断、8-K —— 这些天然不是方向信号,
   给它们编一个 up/down 只会往台账里灌噪音。它们唯一能测的问题是"拿掉它决策会不会变"
   (消融测试,每天要多烧一次 LLM 调用),那是另一件事,不在本模块范围。

④ **判决线沿用判决主体那三条,一条不放宽**(`audit._HORIZON_RULE`):
   n≥30 · Wilson 95% 下界 > 同期基线(不是 50%)· 技巧为正且不是四视界里的孤例。
   全部板块在跨过这三条之前一律 UNPROVEN,**不得**用本台账的中间数字改任何权重。

⑤ **已经在别处记分的不重复记。** edge 的 8 个源在 audit §1;clv/btc/qtum/tj/volreg/
   veto/swing 七匹纸面马在 audit §3;深坑抄底在 `dip_buy.py` 自己的台账。
   同一件事记两本账,只会让"共识"看起来比实际厚。

⑥ **缺席也是数据。** 板块当天没数据 → `stance=None, read="(缺)"`,照样存。
   一个隔三差五就拿不到数的板块,本身就是它不该有发言权的证据。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

Stance = str | None      # "up" | "down" | "neutral" | None(天然无方向/缺数据)


def _sig(v: Any) -> Stance:
    """板块自己算好的 signal(-1/0/+1)→ 表态。这是唯一允许的通用导出。"""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return "up" if n > 0 else ("down" if n < 0 else "neutral")


# ══ 板块名册 ══════════════════════════════════════════════════════
# (key, 中文名, 取数函数 → (stance, read))
# 取数函数拿到的是 (snapshot, extras);任何异常都由 collect() 兜成 (None, "(错)")。

def _smc_structure(s, _e):
    v = s.get("smc") or {}
    if not v.get("trend"):
        return None, "(缺)"
    return _sig(v.get("signal")), f"trend={v.get('trend')} · {v.get('label') or '?'}"


def _smc_playbook(s, _e):
    pb = ((s.get("smc") or {}).get("playbook")) or {}
    act = pb.get("action")
    if not act:
        return None, "(缺)"
    # wait/预警 不是方向表态 —— 记 neutral,别记成"看空"
    side = {"long": "up", "short": "down"}.get(str(act).lower())
    return (side or "neutral"), f"action={act} · lock={pb.get('lock')} · {pb.get('state_cn') or ''}"


def _nw(s, _e):
    v = s.get("nw_envelope") or {}
    if not v.get("active"):
        return None, "(缺)"
    return _sig(v.get("signal")), f"stance={v.get('stance')} · 位置{v.get('position_pct') or v.get('position')}"


def _volume_profile(s, _e):
    v = s.get("volume_profile") or {}
    if not v.get("poc"):
        return None, "(缺)"
    return _sig(v.get("signal")), f"{v.get('price_vs_value') or v.get('stance') or '?'} · POC {v.get('poc')}"


def _intrabar(s, _e):
    v = s.get("intrabar_profile") or {}
    if not v.get("available"):
        return None, "(缺)"
    st = {"偏多": "up", "偏空": "down"}.get(v.get("stance"), "neutral")
    return st, f"{v.get('read')} · CLV {v.get('clv')} · delta {v.get('net_delta_pct')}"


def _squeeze(s, _e):
    v = s.get("squeeze") or {}
    if v.get("signal") is None:
        return None, "(缺)"
    return _sig(v.get("signal")), f"空量比 z={v.get('short_z')} · {v.get('stance_cn') or ''}"


def _geopolitics(s, _e):
    v = s.get("geopolitics") or {}
    lvl = v.get("risk_level")
    if not lvl:
        return None, "(缺)"
    # 升温=看空 / 缓和=看多 / 其余中性。这是雷达自己的口径,不是我新造的判据。
    # ⚠️ 与 mining.md 第三十一轮为 8/15 预注册的五条线是**同一个被告**:
    # 那边测的是"升温后是不是真的跌",这里是同一问题的日频台账版。
    # 两边结论必须一致;若打架,以第三十一轮预注册的线为准。
    st = {"alert": "down", "calm": "up"}.get(lvl, "neutral")
    return st, f"{v.get('risk_cn') or lvl}"


def _catalyst(s, _e):
    v = s.get("catalyst") or {}
    lvl = v.get("impact_level")
    if not lvl:
        return None, "(缺)"
    # 催化剂**没有内生方向** —— 一条"重大催化"可以是 AT&T 扩单,也可以是集体诉讼。
    # 按纪律③记 None,只留级别供日后分层。
    return None, f"级别={lvl}(天然无方向)"


def _regime(s, _e):
    v = s.get("regime") or {}
    if not v.get("regime"):
        return None, "(缺)"
    return None, f"{v.get('regime')} · ATR% {v.get('atr_pct')}(天然无方向)"


def _event_day(s, _e):
    v = s.get("event_day")
    return None, ("熔断中" if v else "非事件日") + "(天然无方向)"


def _macro(s, _e):
    evs = ((s.get("macro") or {}).get("events")) or []
    hot = [e for e in evs if e.get("nuclear") or e.get("impact") == "高"]
    return None, f"未来14天 {len(evs)} 项(重磅 {len(hot)})(天然无方向)"


def _earnings(_s, e):
    d = (e or {}).get("earnings_dates") or []
    return None, (f"下次 {d[0]}" if d else "(缺)") + "(天然无方向)"


def _dilution(_s, e):
    v = (e or {}).get("dilution") or {}
    if not v.get("risk"):
        return None, "(缺)"
    # 用模块自己的分级,不新造判据:high=近期实际增发(供给面利空),
    # 其余(货架/登记)按 decision.py 里写死的纪律"只是注册容量"→ 中性。
    lvl = v.get("level")
    return ("down" if lvl == "high" else "neutral"), f"level={lvl} · 距今 {v.get('age_days')} 天"


def _sec_events(_s, e):
    v = (e or {}).get("sec_events") or []
    # 8-K 的 item 有好有坏(换所 / 重大协议 / 退市警告),不给方向。
    return None, f"{len(v)} 份 8-K(天然无方向)"


def _insider(_s, e):
    v = (e or {}).get("insider_form4") or {}
    if not v.get("total_usd"):
        return None, "(缺)"
    # `fetch_insider_form4` **只抓卖出**(transactionCode='S'),所以"有记录=看空"
    # 会是一个永远只有一个取值的常数,测不出任何东西。用 decision.py 里已经写死
    # 的那条门槛当判据:占流通 <1% 属常规减持(多为 10b5-1 预设)→ 中性;
    # ≥1% 才算真的减持压力。阈值来自 prompt 纪律原文,不是我新定的。
    pf = v.get("pct_float")
    if pf is None:
        return None, f"${v['total_usd']/1e6:.1f}M · 占流通未知"
    return ("down" if float(pf) >= 1.0 else "neutral"), \
           f"${v['total_usd']/1e6:.1f}M · 占流通 {float(pf):.2f}%"


_RULES: list[tuple[str, str, Callable]] = [
    ("smc_structure",  "SMC 聪明钱结构",   _smc_structure),
    ("smc_playbook",   "SMC 顺势 playbook", _smc_playbook),
    ("nw_envelope",    "NW 包络",          _nw),
    ("volume_profile", "成交量画像/POC",    _volume_profile),
    ("intrabar",       "日内画像 Intrabar", _intrabar),
    ("squeeze",        "空头动向(FINRA)",   _squeeze),
    ("geopolitics",    "地缘政治雷达",      _geopolitics),
    ("catalyst",       "公司催化剂雷达",    _catalyst),
    ("regime",         "波动率 Regime",     _regime),
    ("event_day",      "事件日熔断",        _event_day),
    ("macro",          "宏观日历",          _macro),
    ("earnings",       "财报日历",          _earnings),
    ("sec_dilution",   "SEC 增发/稀释",     _dilution),
    ("sec_events",     "SEC 8-K",          _sec_events),
    ("insider",        "内部人 Form 4",     _insider),
]

NAMES: dict[str, str] = {k: cn for k, cn, _ in _RULES}

# 天然无方向 = 本台账测不了它。列出来是为了别让人误以为"没上榜就是没在用"。
NO_DIRECTION = {"catalyst", "regime", "event_day", "macro", "earnings", "sec_events"}


def collect(snapshot: dict, extras: dict | None = None) -> dict[str, dict]:
    """把今天每个板块的表态收成一张表。纯函数,无 I/O,任何板块炸了都不影响其它。"""
    out: dict[str, dict] = {}
    for key, _cn, fn in _RULES:
        try:
            stance, read = fn(snapshot or {}, extras or {})
        except Exception as e:                       # 单个板块坏掉不许拖垮台账
            logger.warning("readings: %s failed: %s", key, e)
            stance, read = None, "(错)"
        if stance not in ("up", "down", "neutral", None):
            logger.warning("readings: %s 给了非法表态 %r → 记 None", key, stance)
            stance = None
        out[key] = {"stance": stance, "read": str(read)[:120]}
    return out


def horizon_grades(readings: dict | None, fwd_h: dict) -> dict[str, dict]:
    """每个**有方向**的板块表态在各视界上的对错。

    与 `journal._horizon_grades` 同一口径:`up` 对上涨、`down` 对下跌;
    `neutral` / `None` 不参与评分(不是"错",是"没表态")。
    """
    out: dict[str, dict] = {}
    for key, v in (readings or {}).items():
        st = (v or {}).get("stance")
        if st not in ("up", "down"):
            continue
        out[key] = {h: ((st == "up") == (r > 0)) for h, r in fwd_h.items()}
    return out
