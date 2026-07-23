"""
AI Decision Engine — the single brain of the dashboard.

Replaces the mechanical log-odds meta-model as the USER-FACING verdict.
One Claude call receives EVERY piece of structured data the system collects
and produces an executable trade plan:

    action            LONG_QBTX | SHORT_QBTZ | HOLD
    conviction        0-10
    trade_plan        entry / stop / target on QBTS + converted ETF prices + R:R
    key_drivers       what actually matters today, ranked
    upcoming_catalysts dated events that could move the stock
    invalidation      the price/condition that kills the thesis

Why this design:
  - The system's strength is DATA COLLECTION (price, options, 13F, news,
    short volume, ETF flow, earnings calendar, mined factors).
  - Mechanical weight-voting of weak signals produced mush ("BUY but HOLD").
  - A strong reasoning model, given ALL the evidence at once, weighs
    interactions a linear combiner can't (e.g. "the SMC lock is bearish but
    the macro calendar clears tomorrow — wait for the event, not the level").

Cost: one claude-sonnet call per publish (~$0.05). Cached by date.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_CLIENT = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
_CACHE_PATH = Path(__file__).parent.parent / "data" / "cache" / "daily_decision.json"
_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

# Fable 5 — Anthropic's most capable model. This is THE call that decides
# whether real money moves today; everything else (news triage, factor
# generation) stays on cheaper models. Fable was disabled for us once before
# (we ran Opus 4.8 in between), so the call falls back to Opus 4.8 on ANY
# primary-model failure (access revoked / safety refusal / no text) — the
# daily publish must never die because model access changed overnight.
_MODEL = "claude-fable-5"
_FALLBACK_MODEL = "claude-opus-4-8"

_SYSTEM = """你是一套经过 254 组回测锤炼的 QBTS 专用交易系统的每日决策大脑。你只交易一只
股票：QBTS（D-Wave Quantum）。执行工具：看多→买 QBTX(2×)，看空→买 QBTZ(−2×)，
无优势→观望。你收到的每份数据下面都标了它的证据等级，你必须按等级加权，
而不是把所有信号当同等证据投票。

════ 这只票已被验证的规律（2024-07→2026-07,双窗口费后回测,mining.md）════
A. 收益 DNA：1天弱延续(+0.12)；3-5天反转(−0.13,跌到5日新低=买点)；10-20天动量
   (+0.13)；60天过热必回吐(−0.14,【追高必死】)。彩票日结构:9成收益来自5个单日,
   钱几乎全在隔夜跳空——所以"在场"比"抓点"重要,仓位小才能活到彩票日。
B. 一级信号（回测显著,优先采信）：
   - 大盘红绿灯:QQQ<50日线 → 一切做多逻辑降档,清仓等是合法答案
   - 波动率目标仓位(0.6/vol,20-100%):唯一同时改善收益和回撤的仓位规则
   - crypto/量子昨日领先:BTC/IONQ/QTUM 昨日绿→今日顺风(t≈2.2-2.4);周末BTC定周一
   - 同行落后追赶:IONQ/RGTI 大涨3%+而 QBTS 落后→后5天 +11.7%(全系统最硬正腿)
   - 相对估值:QBTS 比 IONQ 贵1σ(40日z>1)→逆风清仓;便宜1.5σ→配对买点(榜首策略)
   - 特调双腿(用户自创,第十轮验证):「抄底建仓」(快%R上穿-80且慢<-50)后5天
     +17.4%,十轮最强进场;「止盈减仓」(快%R下穿-20且慢≥-20)后20天 −10%,真能标顶。
     执行口径=收盘确认,勿盘中预挂(第二十五轮:预挂吃诱多假突破均−16.6%,三口径全输)
   - RSI2<10 且 >200日线:后5天 +9.2%
   - 空头动向:FINRA 空量比 z>1=空头(聪明钱)拥挤→偏空;z<−1→顺风(t≈1.1,只当风向)
C. 已判死的推理路径（数据来了也不许当证据）：追大跳空、做空暴涨、
   "空头多=要逼空"、日内进出(负和)、60天过热追涨、周中日内 crypto 跟单
   (只有周一特权)、给反转单设紧止损(必须给隔夜±15%跳空的空间)。
D. 执行军规（第七轮实测）：QBTX 年拖累−24%/QBTZ−34%;持有≤5天用 QBTX,
   >5天建议正股,QBTZ 只做1-3天战术空且绝不过周——把这写进 entry_condition 相关建议。

════ 决策纪律 ════
1. 观望合法且常见。优势不明确绝不硬给方向——错误的高信心比观望贵得多。
2. conviction ≥7 必须有多个【一级信号】共振;单一信号最多 5;二级/三级信号
   只能微调,不能独立驱动方向。
3. 止损必须容纳隔夜跳空(单日±15%常见),反转类入场尤其要宽。
4. ETF 换算:QBTS 变动 X% ≈ QBTX +2X%/QBTZ −2X%。trade_plan 的 etf_* 三个价会被
   系统用实时报价覆盖,你只需把 qbts_entry/stop/target 定准。
5. 催化剂只列数据里能确认的(财报/宏观日历),不编日期。
6. key_drivers 按重要性排序,最多6条,每条 note 必须引用具体数字。
7. 全部中文,价格两位小数;面向用户的文字要像说话,绝不出现 JSON 字段名。
8. 宏观纪律(QBTS=高beta长久期资产):48h内有 CPI/PPI/FOMC → conviction 上限6、
   仓位减半或改为"数据落地再进";通胀升温=逆风驱动;FOMC 周方向押注打折。
9. conviction 与 action 一致性(严格):≤4→必须 HOLD;5-6→仓位≤12%且入场必须带
   确认触发;≥7→15-30%。三者永远自洽。
10. 价位工程:target 优先 naked POC/HVN,stop 放 LVN 之外,entry 参考价值区边缘;
   波动扩张期止损≥1.5×ATR 且仓位降档。
11. SMC playbook 是【纪律工具】不是收益引擎(回测:全保真40天仅1枪)——用它的
   方向锁和风控框架约束计划,但不要因为"结构偏空"就在没有一级信号确认时硬做空。
12. 多周期:日线定方向,1h 定时机;背离时入场条件写"等1h同向再进"。
14. vivienne_note —— 这一段是专门写给我女朋友 Vivienne 看的，她完全不懂股票和金融，请务必：
   - 用最朴实的日常中文，像男朋友温柔、耐心地跟她解释，可以自然亲昵（可称呼她 Vivienne 或"宝贝"）。
   - 绝对不要出现任何术语或英文：不许说 止损/目标价/盈亏比/仓位/ETF/QBTX/QBTZ/做多/做空/
     conviction/POC/看涨看跌/概率几成 等。一律换成大白话（例如"押它会涨""今天先不动""只用一点点钱试试"）。
   - 讲清三件事：①今天我们打算做什么（买一点 / 先不买不卖 / 把手里的卖掉）；②为什么（用她能懂的
     生活化说法，一句话）；③再简单安一下她的心（为什么不用太担心 / 为什么要这么谨慎）。
   - 3-5 句话，温暖、简短、不说教，不要堆数字和价格。
15. system_notes —— 每日「系统自检」，写给这套系统的维护者看（不是交易内容）：以外部
   审计者的挑剔眼光审视你收到的这份数据本身，报告 0-4 条：
   - 数据问题：互相矛盾的数字、明显过期还在被当新鲜用的数据、缺失/可疑的值、说不通的信号。
   - 改进建议：这套系统当下最值得做的改进（新数据源/该删的噪声信号/流程缺陷），说清为什么值得。
   有一说一：真没有就给空数组，绝不为凑数硬写；每条一句话，必须点名具体字段或数字。
   这些内容不影响今天的交易决定本身。
16. position_advice —— 若数据里有「用户实盘持仓」段，逐笔给操作建议（持有/加仓/减仓/清仓）：
   - reason 一句话，必须引用当天的具体信号或执行军规（QBTX 连续持有≤5天、QBTZ 只做
     1-3 天且绝不过周末、总投机仓≤总资产10%、反向杠杆是战术工具不是持仓）。
   - 证据打架时偏保守：先减仓后清仓，不轻易建议加仓；加仓只在一级信号确认时给。
   - 持仓建议与 action 主判断相互独立——主判断 HOLD 不代表已有持仓必须清，但持仓若
     违反军规（如 QBTZ 拿了超过 3 天）必须直说清仓。
   - 没有持仓段 → 空数组。

输出格式：只输出一个 JSON 对象（不要 markdown 代码块，不要其他文字）：
{
  "action": "LONG_QBTX" | "SHORT_QBTZ" | "HOLD",
  "conviction": <0-10 整数>,
  "p_up_5d": <0-1 小数，你对未来5个交易日 QBTS 上涨的【真实概率判断】。这是预测、不是仓位——
             即使 action=HOLD，也要给出你诚实的方向概率，绝不要因为决定观望就把它压到 0.50 附近。
             真的毫无方向感才填 ~0.50；有几成把握就如实给（如 0.62 / 0.38）。系统会逐日记录这个值
             并在5天后用真实价格自动评判，这是检验系统到底有没有预测力的唯一信号——压平它=自废度量>,
  "bold_call_5d": "up"|"down" <强制二选一，没有中间选项：如果今天【必须】押未来5日方向，你押哪边？
             与 action 完全解耦——HOLD 照样要押。这是测量场不是钱：错了没有任何代价，
             真实资金的谨慎由 action/conviction 把关；这里拒绝表态才是唯一的错误答案。
             历史教训：过去21天 p_up 有 95% 挤在 [0.45,0.55] 骑墙区，导致整月方向能力
             不可测量。用你读到的全部证据（一级信号/宏观/地缘/SMC）咬牙选一边>,
  "summary": "<2-3 句话：今天的核心判断和为什么>",
  "trade_plan": {
    "qbts_entry": <入场触发价>, "qbts_stop": <止损价>, "qbts_target": <目标价>,
    "etf_ticker": "QBTX"|"QBTZ"|null, "etf_entry": <价>, "etf_stop": <价>, "etf_target": <价>,
    "rr_ratio": <盈亏比>, "suggested_position_pct": <建议仓位0-30>,
    "entry_condition": "<什么条件下入场，如'放量突破$27'或'直接市价'>"
  },
  "key_drivers": [
    {"name": "<驱动名>", "direction": "bullish"|"bearish", "strength": "强"|"中"|"弱", "note": "<含具体数字的一句话>"}
  ],
  "risks": ["<风险1>", "<风险2>"],
  "upcoming_catalysts": [
    {"date": "<YYYY-MM-DD 或 '未来N天'>", "event": "<事件>", "impact": "高"|"中"|"低", "note": "<一句话>"}
  ],
  "invalidation": "<什么情况下本计划作废，含具体价位>",
  "invalidation_price": <使计划作废的 QBTS 关键价位（数字）。LONG 时=跌破即作废的价位；
                         SHORT 时=涨破即作废的价位；HOLD 时=两个触发位中更接近现价的那个>,
  "vivienne_note": "<写给完全不懂股票的女朋友 Vivienne 看的一段大白话，要求见上面规则 14>",
  "position_advice": [
    {"ticker": "QBTS"|"QBTX"|"QBTZ", "advice": "持有"|"加仓"|"减仓"|"清仓",
     "reason": "<一句话，引用当天信号或执行军规，见规则 16；无持仓段给空数组>"}
  ],
  "system_notes": [
    {"kind": "数据问题"|"改进建议", "note": "<一句话，点名具体字段/数字，见规则 15；没有就给空数组>"}
  ]
}
HOLD 时 trade_plan 里 etf_ticker 用 null，但仍给出"若突破 $X 买 QBTX / 跌破 $Y 买 QBTZ"
的双向触发写进 entry_condition，让用户知道盘中该盯什么位。"""


def _build_user_msg(snapshot: dict, extras: dict | None = None) -> str:
    """Compact every data source into a structured Chinese briefing."""
    extras = extras or {}
    parts: list[str] = []

    # ── 价格与技术面 ──────────────────────────────────────────
    chart = snapshot.get("chart", {})
    price = snapshot.get("price", 0)
    parts.append(
        f"## 价格\n"
        f"QBTS 现价 ${price}，今日 {snapshot.get('today_change', 0)*100:+.2f}%，"
        f"数据截至 {snapshot.get('as_of', '?')[:10]}\n"
        f"ATR(14)≈${chart.get('atr_14', '?')}，52周高 ${chart.get('high_52w','?')} / 低 ${chart.get('low_52w','?')}"
    )
    etf = snapshot.get("etf_prices") or {}
    parts.append(f"QBTX(2×多) 现价 ${etf.get('qbtx','?')}    QBTZ(2×空) 现价 ${etf.get('qbtz','?')}")

    # ── 实时报价（含盘前盘后，日线数据尚未包含的最新变动）────
    lq = extras.get("live_quote")
    if lq and lq.get("quotes"):
        sess_cn = {"pre": "盘前", "regular": "盘中", "post": "盘后", "closed": "已收盘"}.get(lq.get("session"), "?")

        # 各标的的"最后成交"并不同步:反向杠杆 ETF 盘后成交稀疏,QBTZ 的最后一笔可能比
        # QBTS 旧几十分钟(实例 07-02:QBTS 19:59 -4.4% 而 QBTZ 停在 19:00 +5.0%,曾被
        # AI 自检误判为"QBTZ 报价有误")。带上成交时间,滞后 >15 分钟的明确标"旧价"。
        def _bt_min(q: dict) -> int | None:
            bt = str(q.get("bar_time") or "")
            try:
                return int(bt[11:13]) * 60 + int(bt[14:16])
            except (ValueError, IndexError):
                return None
        newest = max((m for m in (_bt_min(q) for q in lq["quotes"].values()) if m is not None),
                     default=None)
        rows = []
        fresh_chg: dict[str, float] = {}      # 仅收集"非旧价"的涨跌,做 2× 一致性自检
        asof_date = str(lq.get("asof_et") or "")[:10]
        for sym, q in lq["quotes"].items():
            chg = f"{q['change_pct']*100:+.2f}%" if q.get("change_pct") is not None else "—"
            bt, m = str(q.get("bar_time") or "")[11:16], _bt_min(q)
            # 跨日标注:周末/盘前 bar 是上一交易日的,只显示 HH:MM 会像"今天 19:59
            # 还在成交"——补日期防误读(AI 自检 07-12 报过周日快照像错标周六)
            bar_date = str(q.get("bar_time") or "")[:10]
            if bt and bar_date and asof_date and bar_date != asof_date:
                bt = f"{bar_date[5:]} {bt}(上一交易日)"
            note = ""
            if newest is not None and m is not None and newest - m > 15:
                note = f"（⚠️ 旧价:最后成交 {bt},比最新报价旧 {newest - m} 分钟 — 薄流动性 ETF 盘后成交稀疏,勿据此核对 2× 换算关系）"
            else:
                if bt:
                    note = f"（最后成交 {bt}）"
                if q.get("change_pct") is not None:
                    fresh_chg[sym] = q["change_pct"]
            rows.append(f"  {sym.upper()}: ${q['price']} ({chg} vs 上一收盘){note}")
        # 2× 一致性自检:07-10 实测两腿 prev_close 基准其实一致(fast_info ≈ 日线),
        # 偏差是薄流动性 ETF 的真实贴价偏离(07-09 收盘 QBTZ −5.70% vs 隐含 −5.04%)。
        # quote_pusher 现在带 implied_px(隐含公允价)/premium_pct —— 有它就报折溢价,
        # 失效价换算一律以隐含比率为基准,勿把贴价偏离当资金流信号。
        if "qbts" in fresh_chg:
            for etf, lev in (("qbtx", 2.0), ("qbtz", -2.0)):
                if etf in fresh_chg and abs(fresh_chg[etf] - lev * fresh_chg["qbts"]) > 0.008:
                    q_etf = lq["quotes"].get(etf) or {}
                    prem, ipx = q_etf.get("premium_pct"), q_etf.get("implied_px")
                    if prem is not None and ipx is not None:
                        rows.append(f"  （⚠️ {etf.upper()} 现价对 2× 隐含公允价 ${ipx} 折溢价 "
                                    f"{prem*100:+.1f}% — 薄流动性贴价偏离(prev_close 基准已核实一致),"
                                    f"失效价/目标价换算用隐含比率,勿把该偏离当异动信号）")
                    else:
                        rows.append(f"  （⚠️ {etf.upper()} 涨跌与 2× 换算差 "
                                    f"{abs(fresh_chg[etf] - lev*fresh_chg['qbts'])*100:.1f}pp — "
                                    f"薄流动性贴价偏离,方向以 QBTS 为准,勿用该差值推断异动）")
        parts.append(
            f"## ⚡ 实时报价（{sess_cn}，{lq.get('asof_et','?')} ET）— 上方日线数据未包含此变动，"
            f"以此为最新现实定价\n" + "\n".join(rows)
        )

    # ── 🚦 大盘红绿灯（一级信号 B-1 的直接读数,别再盲判）──────
    ml = snapshot.get("market_light")
    if ml and ml.get("qqq_vs_50dma") is not None:
        qqq, spy = ml["qqq_vs_50dma"], ml.get("spy_vs_50dma")
        light = "🔴 红灯(QQQ 低于 50 日线 → 一切做多逻辑降档,清仓等是合法答案)" if qqq < 0 \
            else "🟢 绿灯(QQQ 在 50 日线上方)"
        parts.append(
            f"## 🚦 大盘红绿灯（一级信号 B-1）\n"
            f"  {light}\n"
            f"  QQQ vs 50日线 {qqq*100:+.1f}% · SPY {(spy or 0)*100:+.1f}% · "
            f"VIX {ml.get('vix','?')} → 环境={ml.get('regime','?')}\n"
            f"  {ml.get('note','')}"
        )

    # 最近 10 根日线（趋势语境）
    candles = chart.get("candles", [])[-10:]
    if candles:
        rows = [f"  {datetime.fromtimestamp(c['time']).strftime('%m-%d')}: "
                f"O{c['open']} H{c['high']} L{c['low']} C{c['close']}" for c in candles]
        parts.append("## 最近10个交易日 OHLC\n" + "\n".join(rows))

    # ── 8 个经典策略 ──────────────────────────────────────────
    strat_lines = []
    for s in snapshot.get("strategies", []):
        if s.get("signal", 0) != 0 or s.get("confidence") != "low":
            strat_lines.append(f"  [{s['label']}/{s['confidence']}] {s['name']}: {s['rationale']}")
    if strat_lines:
        parts.append("## 经典策略信号（学术规则，仅供参考）\n" + "\n".join(strat_lines))

    # ── 挖矿 ML 因子（已验证 OOS）────────────────────────────
    mined = extras.get("mined_factors") or []
    if mined:
        rows = [f"  [{f.get('label','?')}] {f.get('name','?')} "
                f"(OOS Sharpe {f.get('oos_sharpe',0):.2f}, 命中率 {f.get('hit_rate',0)*100:.0f}%)"
                for f in mined if f.get("signal", 0) != 0]
        if rows:
            parts.append("## 量化因子今日信号（Walk-Forward 验证过的真实 alpha，权重应高于经典策略）\n"
                         + "\n".join(rows))

    # ── 新闻 ─────────────────────────────────────────────────
    news_items = (snapshot.get("news") or {}).get("items", [])[:8]
    if news_items:
        rows = []
        for n in news_items:
            ai = n.get("ai", {})
            rows.append(f"  [{ai.get('sentiment','?')}/{ai.get('impact','?')}] "
                        f"({n.get('published','')[:10]}) {n.get('title','')[:80]} — {ai.get('reasoning','')[:60]}")
        parts.append("## 近期新闻（已 AI 初筛）\n" + "\n".join(rows))

    # ── 🌍 地缘政治/政策雷达（伊朗战局/川普政策/量子政策）────────
    geo = snapshot.get("geopolitics")
    if geo and geo.get("risk_level"):
        rows = [f"  [{it.get('track_cn','?')}/{it.get('stance','?')}] "
                f"{it.get('title','')[:80]} — {it.get('note_cn','')}"
                for it in (geo.get("items") or [])
                if it.get("relevance") in ("high", "medium")][:6]
        # 交叉验证:新闻情绪(雷达)与市场定价(VIX/大盘)矛盾时明说,
        # 免得模型各信各的(AI 自检 07-12 报过两模块直接打架)
        ml_ = snapshot.get("market_light") or {}
        cross = ""
        if geo.get("risk_level") == "alert" and ml_.get("regime") == "risk_on":
            cross = (f"\n  ⚠️ 交叉验证:雷达 alert 但盘面并未定价该风险(VIX {ml_.get('vix')}、"
                     "大盘 risk-on)——两种解释:市场自满(风险真实,波动将至)或新闻滞后于"
                     "实际缓和。处理:以盘面为主、雷达降为『提高警觉』,不机械降信心;"
                     "但失效条件仍须写明「若 VIX 抬头/避险资产异动则按 alert 全额处理」。")
        elif geo.get("risk_level") == "calm" and ml_.get("regime") == "risk_off":
            cross = (f"\n  ⚠️ 交叉验证:雷达 calm 但盘面 risk-off(VIX {ml_.get('vix')})——"
                     "市场在担心雷达三条战线之外的东西(宏观/流动性),勿因地缘平静而放松。")
        parts.append(
            f"## 🌍 地缘政治/政策雷达 {geo.get('risk_cn','?')} — {geo.get('headline_cn','')}\n"
            f"  {geo.get('summary_cn','')}\n"
            + ("\n".join(rows) + "\n" if rows else "")
            + "  （QBTS 与伊朗战局/川普政策强联动 — 07-07 暴跌即谈判破裂所致。alert 级别下"
              "技术面买点先让位:降信心/缩仓位,并把「局势再升级」写进失效条件。）"
            + cross
        )

    # ── 期权流 ────────────────────────────────────────────────
    opt = snapshot.get("options")
    if opt:
        s = opt.get("snapshot", {})
        parts.append(f"## 期权流\n  {opt.get('rationale','')}\n"
                     f"  PCR_OI={s.get('pcr_oi','?')} PCR_VOL={s.get('pcr_vol','?')} "
                     f"Call换手率={s.get('call_churn','?')} Put换手率={s.get('put_churn','?')}")

    # ── 13F 机构持仓 ─────────────────────────────────────────
    hold = snapshot.get("holdings")
    if hold:
        s = hold.get("snapshot", {})
        # 陈旧度口径对齐 holdings.py:用主动持有人报告期(全体 max 会被月报共同基金
        # 洗白成"新鲜",与 rationale 里的推力衰减自相矛盾 —— AI 自检 07-20)
        rd = s.get("active_report_date") or s.get("report_date") or ""
        stale = ""
        if rd:
            try:
                age = (datetime.now().date() - datetime.fromisoformat(rd).date()).days
                stale = (f"\n  ⏳ 主动持有人报告期 {rd}（距今 {age} 天）——13F 法定滞后至季末后45天,"
                         f"{'数据已陈旧、推力已按陈旧度衰减(见上),作背景权重' if age > 75 else '相对新鲜'}。")
            except Exception:
                pass
        parts.append(f"## 13F 机构持仓\n  [{hold.get('label','?')}/{hold.get('confidence','?')}] {hold.get('rationale','')}\n"
                     f"  机构持仓比例 {s.get('institution_pct','?')}，机构数 {s.get('institution_count','?')}，"
                     f"主动管理人净变化 {s.get('active_avg_change','?')}{stale}")

    # ── 盘中量能 ─────────────────────────────────────────────
    intr = snapshot.get("intraday")
    if intr:
        parts.append(f"## 盘中量能\n  {intr.get('rationale','')}")

    # ── 散户情绪(Adanos Reddit buzz + sentiment)────────────────
    st = snapshot.get("sentiment")
    if st and st.get("sentiment_score") is not None:
        parts.append(f"## 散户情绪（Reddit，来自 Adanos）\n  {st.get('note','')}\n"
                     f"  （散户情绪是偏弱信号、常滞后甚至反向 —— 作情绪背景与拥挤度参考，别当方向依据）")

    # ── SMC 聪明钱结构分析 ───────────────────────────────────
    smc = snapshot.get("smc")
    if smc and smc.get("trend"):
        zone_lines = []
        for z in (smc.get("demand_zones") or []):
            zone_lines.append(f"    需求区[{z['kind']}] ${z['low']}–${z['high']}（{z['date']}）")
        for z in (smc.get("supply_zones") or []):
            zone_lines.append(f"    供给区[{z['kind']}] ${z['low']}–${z['high']}（{z['date']}）")
        sweep_lines = [f"    {s['note']}" for s in (smc.get("sweeps") or [])]
        le = smc.get("last_event")
        le_s = f"最近结构事件: {le['date']} {le['dir']} {le['kind']} @ ${le['level']:.2f}" if le else ""
        ltf = smc.get("ltf")
        conf_cn = {"aligned": "1h 与日线同向（入场时机已确认）",
                   "conflict": "1h 与日线背离（等 1h 回到同向再进，别逆低周期入场）",
                   "neutral": "1h 结构中性"}.get(smc.get("confluence", "neutral"), "")
        mtf_s = (f"\n  多周期: 日线={smc['trend']} / 1h={ltf['trend']} → {conf_cn}"
                 f"（高周期定方向，低周期定入场时机）") if ltf else ""
        parts.append(
            f"## SMC 聪明钱结构（订单块/FVG/流动性）\n"
            f"  结构趋势: {smc['trend']}  {le_s}\n"
            f"  价格位置: {smc.get('zone','?')}（区间 ${smc.get('range',{}).get('low','?')}–"
            f"${smc.get('range',{}).get('high','?')} 的 {smc.get('range_position',0)*100:.0f}%）\n"
            + ("  关键区域:\n" + "\n".join(zone_lines) + "\n" if zone_lines else "")
            + ("  流动性事件:\n" + "\n".join(sweep_lines) + "\n" if sweep_lines else "")
            + f"  SMC 综合: {smc.get('label','HOLD')} — {smc.get('rationale','')}"
            + mtf_s
        )

        # ── SMC 顺势纪律 Playbook（全局锁 → 降维中继 → 15m 扣扳机 → FVG）──
        pb = smc.get("playbook")
        if pb and pb.get("lock") and pb.get("rr_veto"):
            # 风控熔断:计划已自我否决 → 折叠成一行结论,不再输出完整交易计划
            # 与主决策打架(AI 自检 2026-07-09 的建议)。
            lock_cn = {"bull": "多头锁定", "bear": "空头锁定", "none": "无锁定"}[pb["lock"]]
            parts.append(
                f"## SMC 顺势纪律 Playbook\n"
                f"  【{lock_cn}】{pb.get('risk_note','RR<2 风控熔断')} → 本 playbook 今日无有效入场,"
                f"强制观望;方向锁仍有效({pb.get('lock_reason','')}),但不构成入场依据。"
            )
        elif pb and pb.get("lock"):
            chk = "\n".join(
                f"    [{'✓' if c['ok'] else '✗'}] {c['label']}：{c['detail']}"
                for c in (pb.get("checklist") or []))
            ez = pb.get("entry_zone")
            tp1, tp2 = pb.get("tp1"), pb.get("tp2")
            plan_lines = []
            if ez:
                plan_lines.append(f"    入场(共振区 {ez['basis']}): ${ez['low']}–${ez['high']}")
            if pb.get("stop") is not None:
                plan_lines.append(f"    止损: ${pb['stop']}")
            if tp1:
                plan_lines.append(f"    TP1(FVG磁吸): ${tp1['price']} — {tp1['basis']}")
            if tp2:
                plan_lines.append(f"    TP2: ${tp2['price']} — {tp2['basis']}")
            if pb.get("rr") is not None:
                plan_lines.append(f"    盈亏比 ≈ {pb['rr']}")
            lock_cn = {"bull": "多头锁定", "bear": "空头锁定", "none": "无锁定"}[pb["lock"]]
            parts.append(
                f"## SMC 顺势纪律 Playbook（这是本系统的【整体评判标准】，优先于零散信号）\n"
                f"  全局状态: 【{lock_cn}】（{pb.get('lock_reason','')}）——{pb.get('bias_note','')}\n"
                f"  当前阶段: 【{pb.get('state_cn','?')}】 建议动作={pb.get('action','wait')}"
                f"（满足条件 {pb.get('conditions_met','?')}）\n"
                f"  扣扳机清单（AND 逻辑，全 ✓ 才进场）:\n{chk}\n"
                + ("  交易计划:\n" + "\n".join(plan_lines) + "\n" if plan_lines else "")
                + "  纪律: 只在【锁定方向】找机会；价格未回到折价/溢价区+触及次级别中继OB前为【预警/等待】，"
                  "不可因零散看多/看空信号提前进场。15m CHoCH+VMC 点是最后的收盘确认扳机。"
            )

    # ── 成交量画像 / POC（价值区与磁吸位，直接用于设目标/止损）──────────
    vp = snapshot.get("volume_profile")
    if vp and vp.get("poc") is not None:
        where_cn = {"above": "上方", "below": "下方", "inside": "内"}.get(vp.get("price_vs_value"), "?")
        hvn_s = "、".join(f"${x}" for x in (vp.get("hvn") or [])[:3]) or "—"
        lvn_s = "、".join(f"${x}" for x in (vp.get("lvn") or [])[:3]) or "—"
        nk_up = "、".join(f"${x}" for x in (vp.get("naked_pocs_above") or [])[:3]) or "—"
        nk_dn = "、".join(f"${x}" for x in (vp.get("naked_pocs_below") or [])[:3]) or "—"
        parts.append(
            f"## 成交量画像 / POC（{vp.get('lookback_days','?')}日，{vp.get('note','')}）\n"
            f"  POC(价值中枢) ${vp['poc']}，价值区 VAL ${vp['val']} – VAH ${vp['vah']}，现价在价值区{where_cn}\n"
            f"  高成交节点 HVN(支撑/阻力): {hvn_s}；低成交真空 LVN(价格穿越快，勿设止损): {lvn_s}\n"
            f"  上方 naked POC(未回补磁吸): {nk_up}；下方 naked POC: {nk_dn}\n"
            f"  操作含义({vp.get('stance','?')}): {vp.get('action_hint','')}\n"
            f"  → 设目标优先用 naked POC / 邻近 HVN；止损放在 LVN 之外；入场参考价值区边缘"
        )

    # ── Intrabar Profile（最近一根日线 bar 内部:吸收/投降/派发,辅助确认腿）────
    ib = snapshot.get("intrabar_profile")
    if ib and ib.get("available"):
        strip = ib.get("delta_strip") or []
        strip_s = "".join("🟢" if s.get("sign", 0) > 0 else "🔴" for s in strip)
        disagree = ";⚠️净delta方向与读数背离,降级参考" if ib.get("delta_disagree") else ""
        parts.append(
            f"## 日内画像 Intrabar（{ib.get('bar_date')} 单bar内部,{ib.get('note','')}）\n"
            f"  日内VPOC ${ib.get('intrabar_poc')}(区间位置{ib.get('poc_position')}),"
            f"收盘位置CLV {ib.get('clv')},净delta {ib.get('net_delta_pct',0)*100:+.0f}%"
            f"(买{ib.get('up_vol_pct',0)*100:.0f}%/卖{ib.get('down_vol_pct',0)*100:.0f}%)\n"
            f"  读数【{ib.get('read')}·{ib.get('stance')}】: {ib.get('read_note','')}{disagree}\n"
            f"  近{len(strip)}日delta趋势: {strip_s}(🟢买盘主导/🔴卖盘主导)\n"
            f"  → 辅助地图非独立信号:价格到需求/供给区时用它判『吸收 vs 投降』作确认腿,"
            f"别单凭它开仓(1h 近似,无 tick;方向已在 B 级信号里定)"
        )

    # ── 空头动向（原挤空燃料，2026-07-04 依第五轮实证翻转）────
    sq = snapshot.get("squeeze")
    if sq and sq.get("rationale"):
        ctx = f"\n  背景：{sq['context']}" if sq.get("context") else ""
        parts.append(
            f"## 空头动向（FINRA 空量比，方向已实证翻转）\n  {sq['rationale']}{ctx}\n"
            f"  （注：QBTS 的空头实测是聪明钱——空量比飙升(z>1)是**偏空**信号，不是挤空燃料；"
            f"空头撤退(z<-1)是顺风。证据强度 t≈1.1 未过显著性门槛，只作风向参考、"
            f"永远不要单凭它给方向。经典策略 Short Flow (Informed Shorts) 与本节同一数据源"
            f"同一方向，勿当成两个独立确认。）"
        )

    # ── 相对强度 / 领先落后 ───────────────────────────────────
    rs = snapshot.get("relative_strength")
    if rs and rs.get("rationale"):
        parts.append(f"## 相对强度（vs 量子篮子 + 风险偏好）\n  {rs['rationale']}")

    # ── 一级信号即时读数（当日新算 champs['today'] 优先;台账字段仅兜底旧快照）──
    ch = snapshot.get("champs") or {}
    td = ch.get("today") or {}

    def _fresh(key, ledger, field):
        v = td.get(key)
        return v if v is not None else (ch.get(ledger) or {}).get(field)

    lv1 = []
    bw = snapshot.get("btc_weekend")
    if bw and bw.get("weekend_ret") is not None:
        lv1.append(f"周末BTC定周一: 周末BTC {bw['weekend_ret']*100:+.1f}% "
                   + ("🟢 → 周一顺风(回测开→收+2.9%、t=3.57;当日收盘前了结,不过夜)。"
                      "执行知识(2026-07-20实测,近1年n=27):温和绿(0~2%)胜率71%、收对收均值+3.5%;"
                      "高点时刻已迁移——2026年绿周一高点仅2/11在开盘首小时,典型出现在盘中"
                      "10:30–14:30 ET(2025年靠跳空开盘冲高的旧剧本已被交易掉),上涨日仅18%开盘即高点"
                      "→ 开盘没冲不代表信号失败,别追开盘价;高点→收盘平均回吐4~5%,"
                      "止盈用限价挂单吃盘中高点优于等收盘"
                      if bw.get("green") else
                      "🔴 → 周一不做多,夜盘也不(历史此情形周一日内均值−3.0%)"))
    tj = td.get("tj_sig") or (ch.get("tj") or {}).get("sig") or {}
    if tj:
        legs = [nm for k, nm in (("buy_base", "🟢抄底建仓触发"), ("sell_trim", "🔴止盈减仓触发"),
                                 ("sell_clear", "⚠️破位清仓触发")) if tj.get(k)]
        trig = tj.get("buy_trigger_px")
        # 第二十五轮(2026-07-20)执行口径审判:盘中预挂单三口径全输收盘确认
        # (假突破单均值−16.6%,全是诱多日;买贵2.37%/次是过滤器的合理价格)
        trig_s = (f";抄底腿预计触发价≈${trig}(收盘高于此价≈快%R上穿-80,仅作观察位——"
                  f"⚠️第二十五轮回测:必须等收盘确认才进,盘中触及别预挂买单(盘中穿了"
                  f"收盘缩回=诱多,历史均值−16.6%;收盘确认口径复利+122% vs 预挂−49%))"
                  if trig else "")
        lv1.append(f"特调双腿: 快%R {tj.get('fast')} / 慢%R {tj.get('slow')} → "
                   + ("、".join(legs) if legs else "无触发") + trig_s)
    z40 = _fresh("z40", "veto", "z40")
    if z40 is not None:
        lv1.append(f"相对估值: QBTS vs IONQ 价差 40日z={z40:+.1f}"
                   + ("(贵1σ+,一级逆风)" if z40 > 1.0 else "(未超贵)"))
    btc_green = _fresh("btc_green", "btc", "btc_green")
    if btc_green is not None:
        lv1.append(f"BTC 昨日{'🟢涨(顺风)' if btc_green else '🔴跌(逆风)'}")
    qtum_green = _fresh("qtum_green", "qtum", "qtum_green")
    if qtum_green is not None:
        lv1.append(f"QTUM 量子板块昨日{'🟢涨' if qtum_green else '🔴跌'}")
    clv = _fresh("clv", "clv", "clv")
    if clv is not None:
        lv1.append(f"昨日收盘位置 CLV={clv:+.2f}"
                   f"({'强收盘,今日顺风' if clv > 0.3 else '非强收盘'})")
    if lv1:
        parts.append("## 一级信号即时读数（回测验证过的高权重信号,与决策纪律 B 级清单对应）\n  "
                     + "\n  ".join(lv1))

    # ── 波动率 regime（决定止损宽度与仓位档位）────────────────
    reg = snapshot.get("regime")
    if reg and reg.get("rationale"):
        vt = reg.get("vol_target") or {}
        vt_s = ""
        if vt.get("position_pct"):
            # 一年窗口实测唯一同时改善收益与回撤的 sizing 规则 — 作为仓位上限参考
            vt_s = (f"\n  {vt.get('note','')}\n"
                    f"  纪律:你给的 suggested_position_pct 不应显著超过这个敞口参考"
                    f"(它按波动自动缩放,是回测验证过的仓位天花板,不是方向观点)。")
        parts.append(f"## 波动率 Regime\n  {reg['rationale']}{vt_s}")

    # ── Nadaraya-Watson 包络（非重绘均值回归带）────────────────
    nw = snapshot.get("nw_envelope")
    if nw and nw.get("active"):
        parts.append(
            f"## Nadaraya-Watson 包络（非重绘核回归均值回归带）\n  {nw['rationale']}\n"
            f"  → 现价贴近下轨=拉伸偏便宜的均值回归买点;贴近上轨=拉伸偏贵、利于止盈/减仓。"
            f"这是均值回归类信号,与趋势/突破类证据可能相左——若与 SMC 趋势/动量背离,"
            f"把它当作【入场时机/止盈位】的参考,而非单独的方向依据,且因其用因果核(不重绘),"
            f"真实胜率低于 TradingView 重绘版回测,勿据此单独给高 conviction。")

    # ── 历史战绩与教训（系统自我反省）────────────────────────
    journal = extras.get("journal")
    if journal and journal.get("records"):
        rows = []
        for r in journal["records"][:8]:
            res = r.get("result")
            if res and res.get("correct") is not None and r.get("action") == "HOLD":
                # HOLD 判读(07-22 起):决策日 |QBTS|≥3% = 漏判(双向工具在架)。
                # 展示当日波动而非 5 日漂移 —— ✗ 判的是"错过了当天的行情"。
                mark = "✓" if res["correct"] else "✗"
                d0 = res.get("day0_ret_pct")
                d0_s = f"当日{d0*100:+.1f}%" if d0 is not None else "当日?"
                rows.append(f"  {mark} {r['date']} HOLD(信心{r['conviction']}) "
                            f"→ {d0_s}{'' if res['correct'] else '(≥3%,漏判——观望不是免费的)'}")
            elif res and res.get("correct") is not None:
                mark = "✓" if res["correct"] else "✗"
                rows.append(f"  {mark} {r['date']} {r['action']}(信心{r['conviction']}) "
                            f"→ {res['outcome']} {res['ret_pct']*100:+.1f}%")
            elif res:
                rows.append(f"  · {r['date']} {r['action']}(信心{r['conviction']}) → 观望期")
            else:
                rows.append(f"  ⏳ {r['date']} {r['action']}(信心{r['conviction']}) → 待评判")
        acc = journal.get("accuracy")
        n_g = journal.get("n_graded") or 0
        acc_s = (f"方向准确率 {acc*100:.0f}%（{journal['n_correct']}/{n_g};{_hit_ci(acc, n_g)}）"
                 if acc is not None and n_g > 0 else "暂无足够样本")
        lessons = journal.get("lessons") or []
        lessons_s = ("\n  ⚠️ 近期错误的教训（认真吸取，避免重蹈覆辙）:\n"
                     + "\n".join(f"    - {x}" for x in lessons)) if lessons else ""

        # 错过成本对冲(2026-07-22):台账只给模型看✗亏损,却从不展示连续观望期间
        # 市场走掉的行情——06-15→07-17 21天20次HOLD 眼看 QBTS −37% 的单边段,唯一
        # 教训条目还是那笔止损过紧的✗空单,负反馈只教"动=亏、不动=安全"。这里把
        # 连续观望的机会成本和"表态vs行动长期背离"摆到模型眼前,让不作为不再隐形。
        recs_new = journal["records"]  # newest first
        inact_s = ""
        hold_run = []
        for r in recs_new:
            if r.get("action") == "HOLD":
                hold_run.append(r)
            else:
                break
        if len(hold_run) >= 3:
            p_new, p_old = _num(hold_run[0].get("price")), _num(hold_run[-1].get("price"))
            if p_new and p_old and p_old > 0:
                moved = (p_new / p_old - 1) * 100
                if abs(moved) >= 8:
                    inact_s += (f"\n  ⚠️ 连续观望成本:你已连续 {len(hold_run)} 个决策日 HOLD,"
                                f"期间 QBTS 从 ${p_old:.2f} 走到 ${p_new:.2f}"
                                f"（{moved:+.1f}%）。观望在优势不明时合法,但连续观望期间"
                                f"市场走出单边行情=你的门槛可能设错了。这不是催你交易——"
                                f"是要求你今天在 summary 里正面回答:这段行情为什么不值得参与?")
        bc_run = []
        for r in recs_new:
            bc = r.get("bold_call_5d")
            if bc and bc == (recs_new[0].get("bold_call_5d") or None) and r.get("action") == "HOLD":
                bc_run.append(bc)
            else:
                break
        if len(bc_run) >= 3:
            dir_cn = "跌" if bc_run[0] == "down" else "涨"
            inact_s += (f"\n  ⚠️ 表态与行动背离:你已连续 {len(bc_run)} 天押注「{dir_cn}」"
                        f"却全部 HOLD。若方向证据真实存在且持续,解释为什么它够你表态"
                        f"却不够你下一张小仓位战术单(规则9的5-6档就是为这种场景设的);"
                        f"若证据其实不足,就把 p_up_5d 老实拉回 0.50 附近。长期骑墙="
                        f"系统只敢看不敢做,台账正在记录这个背离。")
        parts.append(f"## 你自己的历史决策战绩\n  {acc_s}\n" + "\n".join(rows) + lessons_s + inact_s)

    # ── 宏观日历（CPI/PPI/FOMC 等）──────────────────────────
    macro = snapshot.get("macro")
    if macro and macro.get("events"):
        rows = []
        for e in macro["events"]:
            star = "🔴" if e.get("nuclear") else "·"
            if e.get("actual"):
                fc = f"（✅已公布 实际 {e['actual']} vs 预测 {e['forecast'] or '—'} / 前值 {e['previous'] or '—'}）"
            elif e.get("forecast") and (e.get("hours_until") or 0) < 0:
                # 已发布但实际值未回填(FF/FRED 滞后, 09:00 publish 常撞上 08:30 数据) —
                # 07-14 模型把前值 0.5% 当成当日 CPI 公布值喊"爆表",实际 -0.4% 方向全反
                fc = (f"（🕐已发布·实际值尚未回填 — 预测 {e['forecast']} / 前值 {e['previous']};"
                      f"前值是上期数据,严禁当作今日公布值;未知实际值前不得据此定方向）")
            elif e.get("forecast"):
                fc = f"（预测 {e['forecast']} / 前值 {e['previous']}）"
            else:
                fc = ""
            co = (e.get("coef") or {}).get("label")
            rows.append(f"  {star} {e['date']} {e['time_et']}ET [{e['impact']}] {e['title']}{fc}"
                        + (f"〔{co}〕" if co and e.get("nuclear") else ""))
        risk_line = f"  ⚠️ {macro['risk_note']}" if macro.get("risk_window") else f"  {macro.get('risk_note','')}"
        coef_line = (
            "  （宏观日影响系数·第十五轮实测 2022-08~2026-07,事件日|ret|÷平日,*=显著:"
            "非农/失业率 SPY×1.56*·QTUM×1.46* > CPI SPY×1.44 > FOMC SPY×1.31(余波常落在次日);"
            "PPI/核心PCE/GDP/零售/JOLTS ≈×1.0 连大盘都不动。"
            "关键:QBTS 单票在所有宏观日系数均≈1.0——6.3%/日固有波动淹没宏观脉冲,"
            "别只因『数据日』缩 QBTS 仓;正确用法=把非农/CPI/FOMC 当【大盘方向的潜在翻转点】,"
            "公布后看 SPY/QQQ/VIX 反应定基调,而非提前恐惧。）"
        )
        parts.append("## 宏观经济日历（未来14天，🔴=重磅）\n" + "\n".join(rows)
                     + "\n" + risk_line + "\n" + coef_line)

    # ── 财报日历 ─────────────────────────────────────────────
    # 缺数据时显式说缺(AI 自检 07-20:段落静默消失 → 模型只能从新闻猜财报临近)
    earnings = extras.get("earnings_dates") or []
    future = [d for d in earnings if d >= datetime.now().strftime("%Y-%m-%d")][:2]
    if future:
        try:
            days_to = (datetime.fromisoformat(future[0]).date() - datetime.now().date()).days
            cd = f"（{days_to} 天后）"
        except ValueError:
            cd = ""
        parts.append(f"## 财报日历（已确认日期）\n  下次财报: {', '.join(future)}{cd}"
                     "——财报是 QBTS 单票最大的已知波动源,临近时其权重高于任何宏观日。")
    else:
        parts.append("## 财报日历\n  ⚠️ 财报日期未获取到（数据源失败或暂无排期）"
                     "——若新闻提示财报临近,以新闻为准,并在 system_notes 标注此数据缺口。")

    # ── SEC 增发/稀释文件(供给冲击,价格信号看不见的事件面)──────
    dil = extras.get("dilution")
    if dil and dil.get("risk"):
        recent = "、".join(f"{h['form']}({h['date']})" for h in dil.get("recent", []))
        tag = "🔴 实际增发" if dil.get("level") == "high" else "🟠 货架/登记"
        age = dil.get("age_days")
        age_s = f"（最近一份距今 {age} 天）" if age is not None else ""
        parts.append(f"## ⚠️ SEC 增发/稀释文件（来自 EDGAR，机械信号看不见的供给面）\n"
                     f"  {tag}{age_s}：{recent}\n  {dil.get('note','')}\n"
                     f"  纪律：只有近期实际增发(🔴)才会立即压顶、削弱上方目标;货架登记(🟠)只是注册容量,"
                     f"越旧越只是背景——按上面 note 的时效判断权重,别对一份几个月前、期间没动用的货架大幅打折做多。")

    # ── SEC 8-K 重大事件(公司行为,媒体覆盖薄、新闻流会漏)──────
    sev_icon = {"high": "🔴", "warn": "🟠", "info": "·"}
    sec_ev = extras.get("sec_events")
    if sec_ev and sec_ev.get("events"):
        rows = []
        for ev in sec_ev["events"]:
            its = "、".join(i["label"] for i in ev.get("items", [])) or "未标注条目"
            rows.append(f"  {sev_icon.get(ev.get('sev'), '·')} {ev['date']} {ev['form']}: {its}")
        parts.append("## 📄 SEC 8-K 重大事件（近14天，EDGAR 原始文件——新闻流常漏的公司行为）\n"
                     + "\n".join(rows)
                     + "\n  纪律：🔴(稀释/控制权/财报问题)按供给冲击或信任冲击对待;🟠(换所/高管/合同)"
                       "先判性质再定权重——如换所不换 ticker 属行政中性,别脑补方向;·(业绩公告/FD)通常已被新闻覆盖。")

    # ── 内部人卖出(Form 4 一手数据,专治新闻的多票聚合口径)──────
    ins = extras.get("insider_form4")
    if ins and ins.get("total_usd"):
        owners = "、".join(f"{o['name']} ${o['usd']/1e6:.1f}M" for o in (ins.get("by_owner") or [])[:3])
        pf = ins.get("pct_float")
        parts.append(
            f"## 👤 内部人卖出（Form 4,近{ins['window_days']}天,QBTS 本票一手数据）\n"
            f"  合计 ${ins['total_usd']/1e6:.1f}M"
            + (f"（占流通市值 {pf:.2f}%）" if pf is not None else "")
            + f" · {ins['n_filings']} 份申报 · 主要卖方: {owners}\n"
            f"  纪律：若新闻里出现「QBTS/IONQ/RGTI 合计抛售 $X 亿」这类**多票聚合**数字,"
            f"一律以上面这个本票口径为准——聚合数字对单票没有信息量,别按它定方向。"
            f"高管常有 10b5-1 预设计划,占流通 <1% 属常规减持,不等于看空信号。")

    # ── 量化元模型（机械加权参考值）──────────────────────────
    edge = snapshot.get("edge")
    if edge and not edge.get("error"):
        line = (f"## 量化元模型参考（log-odds 机械加权，仅作交叉验证）\n"
                f"  {edge.get('label','?')} · P(up)={edge.get('p_up',0)*100:.0f}% · "
                f"EV={edge.get('expected_return_pct',0)*100:+.1f}%")
        # 用它自己的实盘校准记录给读数定性(AI 自检 07-16):n≥15 且 Wilson95% 上界
        # <50% = 显著劣于随机 → 顺向引用禁令。只改标注不改权重——权重重推等 8/15 审判。
        cal0 = extras.get("calibration") or {}
        n0, hr0 = cal0.get("n_graded", 0), cal0.get("overall_hit_rate")
        if n0 >= 15 and hr0 is not None:
            import math as _math
            _z = 1.96
            _den = 1 + _z * _z / n0
            _ctr = hr0 + _z * _z / (2 * n0)
            _mrg = _z * _math.sqrt(hr0 * (1 - hr0) / n0 + _z * _z / (4 * n0 * n0))
            if (_ctr + _mrg) / _den < 0.5:
                line += (f"\n  ⚠️ 此元模型历史 {n0} 条命中率 {hr0*100:.0f}%"
                         f"(Wilson95%上界 {(_ctr+_mrg)/_den*100:.0f}%<50%)——显著劣于随机。"
                         f"它的 BUY/SELL 本日只可作【反向或零权重】参考,严禁当顺向交叉验证;"
                         f"权重正式重推等 8/15 审判。")
        parts.append(line)

    # ── 历史校准 ─────────────────────────────────────────────
    cal = extras.get("calibration")
    if cal and cal.get("n_graded", 0) >= 5:
        hr = cal["overall_hit_rate"]
        parts.append(f"## 系统历史预测表现\n  {cal['n_graded']} 条已评判，"
                     f"方向命中率 {hr*100:.0f}%（{_hit_ci(hr, cal['n_graded'])}）\n"
                     f"  （评判口径:此命中率只统计【量化元模型 edge 的非观望信号】——"
                     f"信号方向 vs 其后 5 个交易日实际涨跌;你(决策)的 HOLD 不计入此数,"
                     f"HOLD 的影子评判(按 p_up_5d)在决策台账里另行记录。两套数字口径不同,"
                     f"别互相换算;样本仍小,按 CI 读,勿当定论）")

    # ── 💼 用户实盘持仓(真金)→ position_advice ───────────────
    upos = snapshot.get("user_positions") or []
    if upos:
        from datetime import date as _date
        qbts_now, qbtx_now, qbtz_now = _anchor_prices(snapshot, extras)
        now_px = {"QBTS": qbts_now, "QBTX": qbtx_now, "QBTZ": qbtz_now}
        rows = []
        for p in upos:
            t = p.get("ticker")
            qty, cost = _num(p.get("qty")), _num(p.get("cost"))
            if not t or not qty or not cost:
                continue
            line = f"{t}: {qty:g} 股 @ ${cost:.2f}"
            try:
                # 用美东"今天"——Lambda 是 UTC,美东周日晚 today() 已翻到周一,
                # 持有天数虚高 1 天会直接影响军规判定(AI 自检 07-12 报过)
                from zoneinfo import ZoneInfo as _ZI
                _today_et = datetime.now(_ZI("America/New_York")).date()
                held = (_today_et - _date.fromisoformat(str(p.get("date"))[:10])).days
                line += f"(买入 {p['date']},已持有 {held} 个日历日)"
            except Exception:
                pass
            px = now_px.get(t)
            if px:
                # 杠杆腿现价来自隐含公允价时标注口径,与实时报价行的成交价同屏
                # 不一致会被(自检/读者)当矛盾
                q_ = (((extras or {}).get("live_quote") or {}).get("quotes") or {}).get(t.lower()) or {}
                fair_tag = "(隐含公允价)" if q_.get("implied_px") and abs(px - q_["implied_px"]) < 1e-6 else ""
                line += f" · 现价 ${px:.2f}{fair_tag} · 浮动 {px / cost - 1:+.1%}(${(px - cost) * qty:+,.0f})"
            rows.append(line)
        if rows:
            parts.append("## 用户实盘持仓（真金！请按规则 16 逐笔在 position_advice 给操作建议，"
                         "重点核对持有天数是否违反执行军规）\n  " + "\n  ".join(rows))

    parts.append("请综合以上全部证据，按 system prompt 的 JSON 格式输出今天的交易决定。")
    return "\n\n".join(parts)


def _hit_ci(p: float, n: int) -> str:
    """命中率的 Wilson 95% CI 表述 — 小样本命中率噪声极大(36%@13 → 16–62%,横跨50%),
    不给区间,模型会把它当"显著低于抛硬币"来推理(AI 自检 2026-07-03 就这么错了)。"""
    z = 1.96
    den = 1 + z * z / n
    ctr = (p + z * z / (2 * n)) / den
    hw = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    lo, hi = (ctr - hw) * 100, (ctr + hw) * 100
    sig = ("尚不构成统计显著（区间含50%）,仅作背景参考,勿据此大幅调整信心"
           if lo < 50 < hi else "样本已具参考力")
    return f"95%置信区间 {lo:.0f}–{hi:.0f}% — {sig}"


def _num(x) -> float | None:
    """Coerce to a finite float, else None (so '—' renders instead of a guess)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _anchor_prices(snapshot: dict, extras: dict | None) -> tuple[float | None, float | None, float | None]:
    """A consistent (QBTS, QBTX, QBTZ) price trio captured at one moment.

    Prefer the live quote (all three symbols print together) so ETF conversion
    is anchored to *simultaneous* prices; otherwise fall back to the same-session
    closes. Mixing a live QBTS with a stale ETF close would skew the conversion,
    so ETF prices only come from live when QBTS itself is live.

    杠杆腿优先用 implied_px(隐含公允价 = 自身上一收盘 × 2×QBTS涨跌,quote_pusher
    计算):QBTX/QBTZ 薄流动性,最后成交价常带 ±1pp 级贴价偏离(07-09 实测 1.6pp),
    直接当锚会让换算出的失效价/目标价系统性偏移(AI 自检 07-10 报过)。
    """
    quotes = ((extras or {}).get("live_quote") or {}).get("quotes") or {}
    def _q(sym: str, fair_first: bool = False) -> float | None:
        q = quotes.get(sym) or {}
        p = _num(q.get("implied_px")) if fair_first else None
        if p is None or p <= 0:
            p = _num(q.get("price"))
        return p if (p is not None and p > 0) else None
    q_qbts, q_qbtx, q_qbtz = _q("qbts"), _q("qbtx", True), _q("qbtz", True)

    etf = snapshot.get("etf_prices") or {}
    s_qbts = _num(snapshot.get("price"))
    s_qbtx = _num(etf.get("qbtx"))
    s_qbtz = _num(etf.get("qbtz"))

    qbts = q_qbts or s_qbts
    qbtx = (q_qbtx if q_qbts else None) or s_qbtx
    qbtz = (q_qbtz if q_qbts else None) or s_qbtz
    return qbts, qbtx, qbtz


def _conv_etf(level: float, qbts_now: float, etf_now: float, lev_sign: int) -> float:
    """Convert a QBTS price level to the leveraged-ETF price.

    A 2× ETF moves 2× the underlying's *daily* % change, so over the entry
    instant this is exact; lev_sign = +1 for QBTX (2× long), -1 for QBTZ (2×
    short). NOTE: daily-rebalanced ETFs decay on multi-day holds, so stop/target
    are best-estimates that drift if the level is reached days later, not same-day.
    """
    chg = level / qbts_now - 1.0
    return round(etf_now * (1.0 + lev_sign * 2.0 * chg), 2)


def _sanitize_decision(decision: dict, snapshot: dict, extras: dict | None) -> dict:
    """Harden the model's numbers before money rides on them.

    - conviction ≤4 must be HOLD (prompt rule 9) — enforce, don't trust the model.
    - HOLD has no single entry/stop/target → null the plan numbers.
    - validate stop/target geometry (plan_valid flags the UI when it's wrong).
    - recompute R:R from the levels (never trust the model's arithmetic).
    - OVERWRITE the ETF entry/stop/target deterministically from the real
      current ETF price — these are the prices the user actually transacts on.
    - clamp suggested_position_pct to the conviction tier.
    """
    tp = dict(decision.get("trade_plan") or {})
    conv = int(decision.get("conviction", 0) or 0)
    action = decision.get("action")

    # bold_call_5d 兜底:模型漏给/非法时从 p_up 推导(≥0.5→up),台账必须天天有表态
    if decision.get("bold_call_5d") not in ("up", "down"):
        p = _num(decision.get("p_up_5d"))
        decision["bold_call_5d"] = "up" if (p is None or p >= 0.5) else "down"

    # conviction ≤4 → HOLD (no edge worth the cost)
    if action in ("LONG_QBTX", "SHORT_QBTZ") and conv <= 4:
        action = "HOLD"
        decision["action"] = "HOLD"

    if action == "HOLD":
        tp["etf_ticker"] = None
        for k in ("qbts_entry", "qbts_stop", "qbts_target",
                  "etf_entry", "etf_stop", "etf_target", "rr_ratio"):
            tp[k] = None
        tp["suggested_position_pct"] = 0
        decision["trade_plan"] = tp
        decision["plan_valid"] = True
        return decision

    entry, stop, target = _num(tp.get("qbts_entry")), _num(tp.get("qbts_stop")), _num(tp.get("qbts_target"))
    valid = entry is not None and stop is not None and target is not None
    if valid:
        valid = (stop < entry < target) if action == "LONG_QBTX" else (target < entry < stop)
    decision["plan_valid"] = bool(valid)

    # Regime-floor the stop distance — 2026-06-25 SHORT_QBTZ post-mortem: regime
    # said "expansion, 87th pctl, stops need ≥1.5×ATR" in the SAME day's prompt,
    # but the model's numeric stop came in at only ~1.03×ATR and got whipsawed out
    # 2 days later (-10.4%) right before the thesis played out to target. Prose
    # guidance in the prompt is not self-enforcing — widen the stop in code so a
    # regime-violating stop can't silently ride through.
    qbts_now, qbtx_now, qbtz_now = _anchor_prices(snapshot, extras)
    if valid:
        reg = snapshot.get("regime") or {}
        atr_pct = _num(reg.get("atr_pct"))
        if atr_pct and qbts_now:
            min_mult = 1.5 if reg.get("regime") == "expansion" else 1.0
            floor_dist = min_mult * atr_pct * qbts_now
            cur_dist = abs(entry - stop)
            if cur_dist < floor_dist:
                widened = round(entry - floor_dist, 2) if action == "LONG_QBTX" else round(entry + floor_dist, 2)
                logger.info(
                    f"stop widened to regime floor: {stop} -> {widened} "
                    f"(regime={reg.get('regime')}, {min_mult}x ATR14={atr_pct*qbts_now:.2f})")
                stop = widened
                tp["qbts_stop"] = stop

    # R:R from the levels (2× leverage cancels, so QBTS R:R == ETF R:R)
    if valid:
        risk, reward = abs(entry - stop), abs(target - entry)
        tp["rr_ratio"] = round(reward / risk, 2) if risk > 1e-9 else None
    if action == "LONG_QBTX":
        tp["etf_ticker"], etf_now, sign = "QBTX", qbtx_now, +1
    else:
        tp["etf_ticker"], etf_now, sign = "QBTZ", qbtz_now, -1
    if valid and qbts_now and qbts_now > 0 and etf_now and etf_now > 0:
        tp["etf_entry"]  = _conv_etf(entry,  qbts_now, etf_now, sign)
        tp["etf_stop"]   = _conv_etf(stop,   qbts_now, etf_now, sign)
        tp["etf_target"] = _conv_etf(target, qbts_now, etf_now, sign)
    else:
        # Can't compute reliably → show '—' rather than a hallucinated price.
        tp["etf_entry"] = tp["etf_stop"] = tp["etf_target"] = None

    # Position sizing must respect the conviction tier (rule 9).
    pct = _num(tp.get("suggested_position_pct")) or 0.0
    tp["suggested_position_pct"] = int(max(0.0, min(pct, 12.0 if conv <= 6 else 30.0)))

    decision["trade_plan"] = tp
    return decision


# Structured-output schema — Opus 4.8's `output_config.format` constrains the
# model to schema-shaped JSON, so we no longer hand-clean fences / trailing
# commas. Every object needs additionalProperties:false + all keys in required;
# optional fields are made nullable (no min/max constraints — unsupported).
_NUM = {"type": ["number", "null"]}
_DECISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "conviction", "p_up_5d", "bold_call_5d", "summary", "trade_plan",
                 "key_drivers", "risks", "upcoming_catalysts", "invalidation",
                 "invalidation_price", "vivienne_note", "position_advice",
                 "system_notes"],
    "properties": {
        "action": {"type": "string", "enum": ["LONG_QBTX", "SHORT_QBTZ", "HOLD"]},
        "conviction": {"type": "integer"},
        "p_up_5d": {"type": "number"},
        "bold_call_5d": {"type": "string", "enum": ["up", "down"]},
        "summary": {"type": "string"},
        "trade_plan": {
            "type": "object", "additionalProperties": False,
            "required": ["qbts_entry", "qbts_stop", "qbts_target", "etf_ticker",
                         "etf_entry", "etf_stop", "etf_target", "rr_ratio",
                         "suggested_position_pct", "entry_condition"],
            "properties": {
                "qbts_entry": _NUM, "qbts_stop": _NUM, "qbts_target": _NUM,
                "etf_ticker": {"enum": ["QBTX", "QBTZ", None]},  # enum-only: a type+enum mix is rejected
                "etf_entry": _NUM, "etf_stop": _NUM, "etf_target": _NUM,
                "rr_ratio": _NUM, "suggested_position_pct": _NUM,
                "entry_condition": {"type": "string"},
            },
        },
        "key_drivers": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["name", "direction", "strength", "note"],
                "properties": {
                    "name": {"type": "string"},
                    "direction": {"type": "string", "enum": ["bullish", "bearish"]},
                    "strength": {"type": "string", "enum": ["强", "中", "弱"]},
                    "note": {"type": "string"},
                },
            },
        },
        "risks": {"type": "array", "items": {"type": "string"}},
        "upcoming_catalysts": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["date", "event", "impact", "note"],
                "properties": {
                    "date": {"type": "string"},
                    "event": {"type": "string"},
                    "impact": {"type": "string", "enum": ["高", "中", "低"]},
                    "note": {"type": "string"},
                },
            },
        },
        "invalidation": {"type": "string"},
        "invalidation_price": _NUM,
        "vivienne_note": {"type": "string"},
        "position_advice": {   # 💼 用户实盘持仓逐笔建议(无持仓段 = 空数组)
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["ticker", "advice", "reason"],
                "properties": {
                    "ticker": {"type": "string", "enum": ["QBTS", "QBTX", "QBTZ"]},
                    "advice": {"type": "string", "enum": ["持有", "加仓", "减仓", "清仓"]},
                    "reason": {"type": "string"},
                },
            },
        },
        "system_notes": {   # 每日系统自检:AI 主动报告数据问题/改进建议(给维护者,非交易内容)
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["kind", "note"],
                "properties": {
                    "kind": {"type": "string", "enum": ["数据问题", "改进建议"]},
                    "note": {"type": "string"},
                },
            },
        },
    },
}


def generate_decision(snapshot: dict, extras: dict | None = None) -> dict:
    """One Claude call → parsed decision dict. Raises on hard failure.

    Uses structured outputs (`output_config.format`) so the model is constrained
    to valid, schema-shaped JSON — no fragile regex de-fencing / comma-stripping.
    """
    user_msg = _build_user_msg(snapshot, extras)

    def _one_call(model: str) -> str:
        resp = _CLIENT.messages.create(
            model=model,
            max_tokens=16000,  # Fable 的 thinking 更长;thinking + JSON 共享预算,留足头房
            # Fable 5 thinking 常开,adaptive 是唯一合法的显式配置(Opus 4.8 同样接受,
            # 所以主/备两个模型可以共用这一套参数)。
            thinking={"type": "adaptive"},
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            output_config={"format": {"type": "json_schema", "schema": _DECISION_SCHEMA}},
        )
        # Thinking blocks stream first; the text block is guaranteed valid JSON.
        text = next(
            (b.text for b in resp.content if getattr(b, "type", "") == "text"),
            "",
        ).strip()
        if not text:
            # A safety refusal (stop_reason="refusal") yields no schema-shaped text.
            raise ValueError(f"no text block in model response (stop_reason={resp.stop_reason})")
        return text

    # 主模型任何失败(权限被收回 / 安全拒答 / 空响应)→ 立即用 Opus 4.8 重打同一发。
    # Fable 曾经被禁用过一次;每日 publish 不允许因为模型可用性变化而死掉。
    try:
        text, model_used = _one_call(_MODEL), _MODEL
    except (anthropic.APIError, ValueError) as e:
        logger.warning("decision: %s failed (%s) — falling back to %s",
                       _MODEL, str(e)[:200], _FALLBACK_MODEL)
        text, model_used = _one_call(_FALLBACK_MODEL), _FALLBACK_MODEL
    decision = json.loads(text)
    decision["model"] = model_used            # observability:实际是谁做的决策
    decision["system_notes"] = (decision.get("system_notes") or [])[:4]
    decision["position_advice"] = (decision.get("position_advice") or [])[:6]

    # Minimal guard — structured outputs already enforces the shape.
    if decision.get("action") not in ("LONG_QBTX", "SHORT_QBTZ", "HOLD"):
        raise ValueError(f"bad action: {decision.get('action')}")
    decision["conviction"] = max(0, min(10, int(decision.get("conviction", 0))))

    # Harden the numbers (R:R, geometry, position tier) and OVERWRITE the ETF
    # entry/stop/target with deterministic conversions from the real ETF price —
    # the user buys QBTX/QBTZ directly, so those prices must be exact, not guessed.
    decision = _sanitize_decision(decision, snapshot, extras)
    return decision


def _invert_v1_shadow(snapshot: dict) -> dict | None:
    """反向影子(2026-07-21,用户拍板 · 承 AI 自检建议):把原始 v1 元模型
    (2026-07-17 前上线版,22 条已判 21% 命中、Wilson95% 上界 38%<50%,显著劣于
    随机)的表态整个倒过来,当零决策权的测量对照——若 v1 稳定地"错",反过来押
    可能有正 edge;但这只是假设,n 太小(21~24)不能排除只是小样本噪声,不能
    默认成立。纯机械(edge.compute_edge_v1,不调任何 LLM,$0),从不进真决策
    或 edge.py 的 compute_edge(v2)。8/15 与 Fable/DeepSeek 同框判分。"""
    v1 = snapshot.get("edge_v1_shadow")
    if not v1 or v1.get("error") or v1.get("p_up") is None:
        return None
    p_up_v1 = float(v1["p_up"])
    v1_call = "up" if p_up_v1 > 0.5 else "down"        # v1 的原始(未反向)表态
    inv_call = "down" if v1_call == "up" else "up"      # 本影子实际下注的方向
    return {
        "source_model": "v1(原始未改元模型,已判21%命中·劣于随机)",
        "v1_p_up": round(p_up_v1, 4),
        "v1_call": v1_call,
        "bold_call_5d": inv_call,      # 与 bold_call_5d/ds_bold_call 同名同口径,journal 复用同一套 fwd5 评分
        "p_up_5d": round(1 - p_up_v1, 4),
        "note": "v1 表态整体反向,零决策权测量;8/15 判是真反向alpha还是巧合",
    }


_DS_MODEL = "deepseek-v4-pro"
_DS_URL = "https://api.deepseek.com/chat/completions"


def generate_shadow_decision(snapshot: dict, extras: dict | None = None) -> dict | None:
    """DeepSeek V4 Pro 影子决策(2026-07-13,用户要求 Claude/DeepSeek 切换对照)。

    同一份 system+user prompt、同一套 _sanitize 硬化;零决策权 —— 不推送、不驱动
    交易、不进 edge;唯一的记账是 journal 顺带记它的 bold_call_5d 每日评分,
    8/15 与 Fable 同框宣判(影子考场)。无 DEEPSEEK_API_KEY 或任何失败 → None,
    主决策完全不受影响。成本 ~$0.02/天(V4 Pro $0.435/M in)。
    """
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        return None
    try:
        import requests
        r = requests.post(_DS_URL, timeout=150, headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        }, json={
            "model": _DS_MODEL,
            "messages": [{"role": "system", "content": _SYSTEM},
                         {"role": "user", "content": _build_user_msg(snapshot, extras)}],
            # prompt 本身已要求"只输出一个 JSON 对象"(json_object 模式的前置条件)
            "response_format": {"type": "json_object"},
            "max_tokens": 8000,
            "stream": False,
        })
        r.raise_for_status()
        text = (r.json()["choices"][0]["message"]["content"] or "").strip()
        if text.startswith("```"):                     # 保险:围栏剥离
            text = text.split("```", 2)[1]
            text = text[4:] if text.startswith("json") else text
            text = text.rsplit("```", 1)[0]
        d = json.loads(text)
        if d.get("action") not in ("LONG_QBTX", "SHORT_QBTZ", "HOLD"):
            raise ValueError(f"bad action: {d.get('action')}")
        d["conviction"] = max(0, min(10, int(d.get("conviction", 0) or 0)))
        d["system_notes"] = (d.get("system_notes") or [])[:4]
        d["position_advice"] = (d.get("position_advice") or [])[:6]
        d["model"] = _DS_MODEL
        d["shadow"] = True
        return _sanitize_decision(d, snapshot, extras)
    except Exception as e:
        logger.warning(f"deepseek shadow decision failed: {e}")
        return None


def get_or_generate_decision(
    snapshot: dict,
    force_refresh: bool = False,
    extras: dict | None = None,
) -> tuple[dict | None, str | None, bool]:
    """
    Returns (decision, generated_at_iso, was_fresh).
    Cached per calendar day — repeated dashboard loads cost $0.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if not force_refresh and _CACHE_PATH.exists():
        try:
            cached = json.loads(_CACHE_PATH.read_text())
            if cached.get("date") == today:
                return cached["decision"], cached["generated_at"], False
            # Stale (different day) — still return it rather than None,
            # caller can decide to force-refresh.
            return cached["decision"], cached["generated_at"], False
        except Exception:
            pass

    try:
        decision = generate_decision(snapshot, extras)
    except Exception as e:
        logger.warning(f"Decision generation failed: {e}")
        return None, None, False

    # DeepSeek 影子决策挂在主决策上随缓存/payload/前端一路带过去;失败=没有,零影响
    ds = generate_shadow_decision(snapshot, extras)
    if ds:
        decision["shadow_ds"] = ds

    # v1 反向影子(2026-07-21 用户拍板,承 AI 自检建议):零成本(纯机械,不调模型),
    # 零决策权,只记账供 8/15 判是否是真反向alpha还是小样本噪声
    v1inv = _invert_v1_shadow(snapshot)
    if v1inv:
        decision["shadow_v1_inverse"] = v1inv

    # NOTE: the intraday consistency guard (flip-flop detection) lives in
    # journal.record() — it reads/writes Supabase, so a phone tap on the deployed
    # site, a local run, and a cloud Lambda all share one running action list.
    # A local cache file would NOT (Lambda /tmp is wiped per cold start).
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")   # tz-aware UTC → 前端转本地
    try:
        _CACHE_PATH.write_text(json.dumps(
            {"date": today, "generated_at": now_iso, "decision": decision},
            ensure_ascii=False, indent=2,
        ))
    except Exception as e:
        logger.warning(f"Decision cache write failed: {e}")
    return decision, now_iso, True


def get_cached_decision() -> tuple[dict | None, str | None]:
    if not _CACHE_PATH.exists():
        return None, None
    try:
        cached = json.loads(_CACHE_PATH.read_text())
        return cached.get("decision"), cached.get("generated_at")
    except Exception:
        return None, None
