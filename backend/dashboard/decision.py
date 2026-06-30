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
    interactions a linear combiner can't (e.g. "high short ratio is bullish
    ONLY because 13F shows institutions accumulating — squeeze fuel").

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

# Opus 4.8 — the strongest reasoning model available to us. This is THE call
# that decides whether real money moves today; everything else (news triage,
# factor generation) stays on cheaper models. (Was claude-fable-5 until that
# model was disabled for us; Opus 4.8 is the current top-tier replacement.)
_MODEL = "claude-opus-4-8"

_SYSTEM = """你是一名管理自有资金的资深对冲基金经理，专精高波动小盘股的事件驱动交易。
你只交易一只股票：QBTS（D-Wave Quantum，量子计算）。执行工具：
  - 看多 → 买 QBTX（2× 做多 ETF）
  - 看空 → 买 QBTZ（2× 做空 ETF）
  - 无明确优势 → 观望（HOLD 也是仓位）

你会收到系统采集的全部结构化数据。你的任务是像基金经理晨会一样：权衡所有证据的
相互作用（不是简单投票），输出一个可直接执行的交易决定。

重要原则：
1. 观望是合法且常见的决定。优势不明确时绝不硬给方向——错误的高信心比观望贵得多。
2. conviction ≥7 必须有多个独立证据共振；单一信号最多给 5。
3. 止损必须考虑 QBTS 的隔夜跳空风险（历史上单日 ±15% 常见），不要给太紧的止损。
4. ETF 价格换算：QBTS 变动 X% ≈ QBTX 变动 +2X%，QBTZ 变动 -2X%。
   注意：trade_plan 里的 etf_entry/etf_stop/etf_target 会由系统用实时 ETF 报价自动换算并覆盖，
   你只需把 QBTS 的 qbts_entry/qbts_stop/qbts_target 三个价位定准确即可（这才是关键输入）。
   另外 QBTX/QBTZ 是「每日再平衡」2× ETF，多日持仓有波动衰减，别把持仓周期设得太长。
5. 催化剂只列你能从数据中确认的（财报日期、近期 8-K 节奏、宏观日历提供的数据），
   不确定的事不要编造日期。
6. key_drivers 按重要性排序，最多 6 条，每条 note 必须引用具体数字。
7. 所有文字用中文，价格保留两位小数。面向用户的文字字段（summary、entry_condition、
   invalidation、各 note 等）要像跟人说话一样自然，绝不能出现 JSON 字段名本身
   （如写"按 entry_condition 执行"是错的，应直接用中文描述那个条件）。
8. 宏观纪律（QBTS 是高 beta 长久期资产，宏观流动性预期对它的影响常大于个股新闻）：
   - 未来 48h 内有 CPI/PPI/FOMC 等重磅数据 → conviction 上限 6，建议仓位减半，
     或把入场条件设为"数据落地后确认方向再进"。
   - CPI/PPI 预测值显著高于前值（通胀升温）→ 对高 beta 成长股是逆风，计入 bearish 驱动。
   - FOMC 临近一周内，方向性押注要打折——把会议日期写进 upcoming_catalysts 和失效条件。
9. conviction 与 action 的一致性纪律（必须严格遵守）：
   - conviction ≤4 → action 必须是 HOLD（优势太弱，不值得交易成本和心理成本）
   - conviction 5-6 → 轻仓试探档：suggested_position_pct 必须 ≤12%，
     且 entry_condition 必须带确认触发（如放量突破某价位），不允许"直接市价全仓"
   - conviction ≥7 → 标准档：suggested_position_pct 15-30%
   这样 conviction、仓位、入场方式三者永远自洽，用户不会看到"低信心却喊买入"。
10. 成交量画像纪律（设具体价位时优先于纯技术猜测）：
   - qbts_target 优先选 naked POC 或邻近 HVN（成交量证明的磁吸/阻力位），而不是凭感觉取整数。
   - qbts_stop 放在 LVN（低成交真空带）之外——价格穿 LVN 极快，止损设在里面易被一笔扫掉。
   - qbts_entry 参考价值区边缘：折价区(VAL 下方)利于做多入场，溢价区(VAH 上方)做多要防回归。
11. 波动率 regime 纪律：扩张期(高百分位)→止损放宽到 ≥1.5×ATR 且仓位降一档；
   收缩期→可收紧止损但提防低波后的假突破。止损宽度必须和当前 regime 自洽。
12. 挤空燃料纪律：燃料是"弹药"不是"扳机"。燃料高 + 结构/价格确认看多 → 可提升做多优先级与目标；
   但只有高燃料、无价格确认时，不得据此单独给出方向性高 conviction。
13. 多周期纪律：日线定方向，1h 定入场时机。若 1h 与日线背离(confluence=conflict)，
   把 entry_condition 设为"等 1h 回到与日线同向再进"，不要逆着低周期结构市价入场。
14. vivienne_note —— 这一段是专门写给我女朋友 Vivienne 看的，她完全不懂股票和金融，请务必：
   - 用最朴实的日常中文，像男朋友温柔、耐心地跟她解释，可以自然亲昵（可称呼她 Vivienne 或"宝贝"）。
   - 绝对不要出现任何术语或英文：不许说 止损/目标价/盈亏比/仓位/ETF/QBTX/QBTZ/做多/做空/
     conviction/POC/看涨看跌/概率几成 等。一律换成大白话（例如"押它会涨""今天先不动""只用一点点钱试试"）。
   - 讲清三件事：①今天我们打算做什么（买一点 / 先不买不卖 / 把手里的卖掉）；②为什么（用她能懂的
     生活化说法，一句话）；③再简单安一下她的心（为什么不用太担心 / 为什么要这么谨慎）。
   - 3-5 句话，温暖、简短、不说教，不要堆数字和价格。

输出格式：只输出一个 JSON 对象（不要 markdown 代码块，不要其他文字）：
{
  "action": "LONG_QBTX" | "SHORT_QBTZ" | "HOLD",
  "conviction": <0-10 整数>,
  "p_up_5d": <0-1 小数，你对未来5个交易日 QBTS 上涨的【真实概率判断】。这是预测、不是仓位——
             即使 action=HOLD，也要给出你诚实的方向概率，绝不要因为决定观望就把它压到 0.50 附近。
             真的毫无方向感才填 ~0.50；有几成把握就如实给（如 0.62 / 0.38）。系统会逐日记录这个值
             并在5天后用真实价格自动评判，这是检验系统到底有没有预测力的唯一信号——压平它=自废度量>,
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
  "vivienne_note": "<写给完全不懂股票的女朋友 Vivienne 看的一段大白话，要求见上面规则 14>"
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
        rows = []
        for sym, q in lq["quotes"].items():
            chg = f"{q['change_pct']*100:+.2f}%" if q.get("change_pct") is not None else "—"
            rows.append(f"  {sym.upper()}: ${q['price']} ({chg} vs 上一收盘)")
        parts.append(
            f"## ⚡ 实时报价（{sess_cn}，{lq.get('asof_et','?')} ET）— 上方日线数据未包含此变动，"
            f"以此为最新现实定价\n" + "\n".join(rows)
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
        rd = s.get("report_date") or ""
        stale = ""
        if rd:
            try:
                age = (datetime.now().date() - datetime.fromisoformat(rd).date()).days
                stale = (f"\n  ⏳ 申报季度截至 {rd}（距今 {age} 天）——13F 法定滞后至季末后45天,"
                         f"{'数据已陈旧、可能与当前持仓不符,作背景权重' if age > 75 else '相对新鲜'}。")
            except Exception:
                pass
        parts.append(f"## 13F 机构持仓\n  [{hold.get('label','?')}/{hold.get('confidence','?')}] {hold.get('rationale','')}\n"
                     f"  机构持仓比例 {s.get('institution_pct','?')}，机构数 {s.get('institution_count','?')}，"
                     f"主动管理人净变化 {s.get('active_avg_change','?')}{stale}")

    # ── 盘中量能 ─────────────────────────────────────────────
    intr = snapshot.get("intraday")
    if intr:
        parts.append(f"## 盘中量能\n  {intr.get('rationale','')}")

    # ── Reddit ────────────────────────────────────────────────
    red = snapshot.get("reddit")
    if red and red.get("auth_mode") == "oauth":
        s = red.get("snapshot", {})
        parts.append(f"## Reddit 散户讨论\n  {red.get('rationale','')}\n"
                     f"  7日提及 {s.get('n_total_7d','?')} 条，24h {s.get('n_last_24h','?')} 条，"
                     f"速度 {s.get('velocity','?')}×")

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
        if pb and pb.get("lock"):
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

    # ── 挤空燃料（合成短仓+期权+13F）──────────────────────────
    sq = snapshot.get("squeeze")
    if sq and sq.get("fuel_score") is not None:
        parts.append(
            f"## 挤空燃料（合成指标，勿重复计数）\n  {sq.get('rationale','')}\n"
            f"  （注：本分数由上面的「期权流」+「13F 机构持仓」合成而来，不是独立证据——"
            f"权衡时把它和那两项当作同一条线索，不要当成三个独立确认。）"
        )

    # ── 相对强度 / 领先落后 ───────────────────────────────────
    rs = snapshot.get("relative_strength")
    if rs and rs.get("rationale"):
        parts.append(f"## 相对强度（vs 量子篮子 + 风险偏好）\n  {rs['rationale']}")

    # ── 波动率 regime（决定止损宽度与仓位档位）────────────────
    reg = snapshot.get("regime")
    if reg and reg.get("rationale"):
        parts.append(f"## 波动率 Regime\n  {reg['rationale']}")

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
            if res and res.get("correct") is not None:
                mark = "✓" if res["correct"] else "✗"
                rows.append(f"  {mark} {r['date']} {r['action']}(信心{r['conviction']}) "
                            f"→ {res['outcome']} {res['ret_pct']*100:+.1f}%")
            elif res:
                rows.append(f"  · {r['date']} {r['action']}(信心{r['conviction']}) → 观望期")
            else:
                rows.append(f"  ⏳ {r['date']} {r['action']}(信心{r['conviction']}) → 待评判")
        acc = journal.get("accuracy")
        acc_s = f"方向准确率 {acc*100:.0f}%（{journal['n_correct']}/{journal['n_graded']}）" if acc is not None else "暂无足够样本"
        lessons = journal.get("lessons") or []
        lessons_s = ("\n  ⚠️ 近期错误的教训（认真吸取，避免重蹈覆辙）:\n"
                     + "\n".join(f"    - {x}" for x in lessons)) if lessons else ""
        parts.append(f"## 你自己的历史决策战绩\n  {acc_s}\n" + "\n".join(rows) + lessons_s)

    # ── 宏观日历（CPI/PPI/FOMC 等）──────────────────────────
    macro = snapshot.get("macro")
    if macro and macro.get("events"):
        rows = []
        for e in macro["events"]:
            star = "🔴" if e.get("nuclear") else "·"
            if e.get("actual"):
                fc = f"（✅已公布 实际 {e['actual']} vs 预测 {e['forecast'] or '—'} / 前值 {e['previous'] or '—'}）"
            elif e.get("forecast"):
                fc = f"（预测 {e['forecast']} / 前值 {e['previous']}）"
            else:
                fc = ""
            rows.append(f"  {star} {e['date']} {e['time_et']}ET [{e['impact']}] {e['title']}{fc}")
        risk_line = f"  ⚠️ {macro['risk_note']}" if macro.get("risk_window") else f"  {macro.get('risk_note','')}"
        parts.append("## 宏观经济日历（未来14天，🔴=重磅）\n" + "\n".join(rows) + "\n" + risk_line)

    # ── 财报日历 ─────────────────────────────────────────────
    earnings = extras.get("earnings_dates") or []
    if earnings:
        future = [d for d in earnings if d >= datetime.now().strftime("%Y-%m-%d")][:2]
        if future:
            parts.append("## 财报日历（已确认日期）\n  下次财报: " + ", ".join(future))

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

    # ── 量化元模型（机械加权参考值）──────────────────────────
    edge = snapshot.get("edge")
    if edge and not edge.get("error"):
        parts.append(f"## 量化元模型参考（log-odds 机械加权，仅作交叉验证）\n"
                     f"  {edge.get('label','?')} · P(up)={edge.get('p_up',0)*100:.0f}% · "
                     f"EV={edge.get('expected_return_pct',0)*100:+.1f}%")

    # ── 历史校准 ─────────────────────────────────────────────
    cal = extras.get("calibration")
    if cal and cal.get("n_graded", 0) >= 5:
        parts.append(f"## 系统历史预测表现\n  {cal['n_graded']} 条已评判，"
                     f"方向命中率 {cal['overall_hit_rate']*100:.0f}%")

    parts.append("请综合以上全部证据，按 system prompt 的 JSON 格式输出今天的交易决定。")
    return "\n\n".join(parts)


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
    """
    quotes = ((extras or {}).get("live_quote") or {}).get("quotes") or {}
    def _q(sym: str) -> float | None:
        p = _num((quotes.get(sym) or {}).get("price"))
        return p if (p is not None and p > 0) else None
    q_qbts, q_qbtx, q_qbtz = _q("qbts"), _q("qbtx"), _q("qbtz")

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

    # R:R from the levels (2× leverage cancels, so QBTS R:R == ETF R:R)
    if valid:
        risk, reward = abs(entry - stop), abs(target - entry)
        tp["rr_ratio"] = round(reward / risk, 2) if risk > 1e-9 else None

    # Deterministic ETF prices from the REAL current ETF quote.
    qbts_now, qbtx_now, qbtz_now = _anchor_prices(snapshot, extras)
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
    "required": ["action", "conviction", "p_up_5d", "summary", "trade_plan",
                 "key_drivers", "risks", "upcoming_catalysts", "invalidation",
                 "invalidation_price", "vivienne_note"],
    "properties": {
        "action": {"type": "string", "enum": ["LONG_QBTX", "SHORT_QBTZ", "HOLD"]},
        "conviction": {"type": "integer"},
        "p_up_5d": {"type": "number"},
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
    },
}


def generate_decision(snapshot: dict, extras: dict | None = None) -> dict:
    """One Claude call → parsed decision dict. Raises on hard failure.

    Uses structured outputs (`output_config.format`) so the model is constrained
    to valid, schema-shaped JSON — no fragile regex de-fencing / comma-stripping.
    """
    user_msg = _build_user_msg(snapshot, extras)

    resp = _CLIENT.messages.create(
        model=_MODEL,
        max_tokens=8000,   # thinking + JSON answer share the budget — leave headroom
        # Opus 4.8 has thinking OFF by default; turn it on so this decision gets
        # the same deliberate reasoning the old always-on model gave it.
        thinking={"type": "adaptive"},
        system=_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
        output_config={"format": {"type": "json_schema", "schema": _DECISION_SCHEMA}},
    )
    # Thinking blocks stream first; the text block is now guaranteed valid JSON.
    text = next(
        (b.text for b in resp.content if getattr(b, "type", "") == "text"),
        "",
    ).strip()
    if not text:
        # A safety refusal (stop_reason="refusal") yields no schema-shaped text.
        raise ValueError(f"no text block in model response (stop_reason={resp.stop_reason})")
    decision = json.loads(text)

    # Minimal guard — structured outputs already enforces the shape.
    if decision.get("action") not in ("LONG_QBTX", "SHORT_QBTZ", "HOLD"):
        raise ValueError(f"bad action: {decision.get('action')}")
    decision["conviction"] = max(0, min(10, int(decision.get("conviction", 0))))

    # Harden the numbers (R:R, geometry, position tier) and OVERWRITE the ETF
    # entry/stop/target with deterministic conversions from the real ETF price —
    # the user buys QBTX/QBTZ directly, so those prices must be exact, not guessed.
    decision = _sanitize_decision(decision, snapshot, extras)
    return decision


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
