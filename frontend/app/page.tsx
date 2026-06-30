"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { MiniChart } from "./_components/mini-chart";
import { ControlPanel } from "./_components/control-panel";
import { RetrospectivePanel } from "./_components/retrospective-panel";
import { getSnapshot, getLiveQuote, type Snapshot, type Decision, type LiveQuote } from "./_lib/data";
import { fmtLocalDateTime, parseUtc, etMelbSuffix, epochMelbTime, macroSurprise } from "./_lib/format";

const SESSION_BADGE: Record<LiveQuote["session"], { label: string; cls: string }> = {
  pre:     { label: "盘前", cls: "bg-amber-100 text-amber-700"   },
  regular: { label: "盘中", cls: "bg-emerald-100 text-emerald-700" },
  post:    { label: "盘后", cls: "bg-violet-100 text-violet-700" },
  closed:  { label: "已收盘", cls: "bg-gray-100 text-gray-500"   },
};

/* ─────────────────────────────────────────────────────────────────────────
   ONE-SCREEN decision dashboard.
   Everything the user needs daily, in glance order:
     1. 行动：买QBTX / 买QBTZ / 观望 + 信心
     2. 交易计划：入场 / 止损 / 目标 / 盈亏比 / 仓位
     3. 为什么：关键驱动（带数字）
     4. 接下来盯什么：催化剂 + 失效条件
     5. 背景：今日要闻（压缩） + 60日小图
   ───────────────────────────────────────────────────────────────────────── */

/* Action display is tiered by conviction so the headline never overstates
   the edge: 5-6 = light probe (轻仓试探), 7+ = standard size. The backend
   prompt enforces the same tiers on position size, keeping words ≡ numbers. */
function getActionMeta(action: Decision["action"], conviction: number) {
  const probe = conviction <= 6;   // 5-6 → 试探档（≤4 的非 HOLD 不该出现）
  switch (action) {
    case "LONG_QBTX":
      return probe
        ? { title: "轻仓试多 QBTX", sub: "小仓位试探 · 确认信号后再加仓",
            cls: "text-emerald-700 bg-emerald-50/60 border-emerald-200", bar: "bg-emerald-400" }
        : { title: "买入 QBTX", sub: "做多 QBTS（2× 杠杆）",
            cls: "text-emerald-700 bg-emerald-50 border-emerald-300", bar: "bg-emerald-500" };
    case "SHORT_QBTZ":
      return probe
        ? { title: "轻仓试空 QBTZ", sub: "小仓位试探 · 确认信号后再加仓",
            cls: "text-red-700 bg-red-50/60 border-red-200", bar: "bg-red-400" }
        : { title: "买入 QBTZ", sub: "做空 QBTS（2× 反向）",
            cls: "text-red-700 bg-red-50 border-red-300", bar: "bg-red-500" };
    default:
      return { title: "观望", sub: "今日无明确优势，等待触发",
               cls: "text-[#525461] bg-[#F6F6F8] border-[#D9D9DE]", bar: "bg-gray-400" };
  }
}

/* 信心刻度图例 */
const CONVICTION_LEGEND = "0-4 观望 · 5-6 轻仓试探 · 7-8 标准仓 · 9+ 重仓";

/* 页面版本号 — 右下角显示，发版时手动 bump */
const APP_VERSION = "1.0";

function fmtPx(n: number | null | undefined): string {
  return typeof n === "number" && isFinite(n) ? `$${n.toFixed(2)}` : "—";
}

/* 带正负号的金额(模拟盈亏用) */
function fmtSignedUsd(n: number): string {
  return `${n >= 0 ? "+" : "−"}$${Math.abs(n).toFixed(2)}`;
}

/* 期望值(每单位风险):用系统自己的胜率估计 × 盈亏比。
   p_up_5d=未来5日上涨概率;做空时赢面=1−p_up。RR=回报/风险。
   EV = p赢×RR − (1−p赢)。<0 = 按它自己的概率长期重复做都不划算。
   注意:p_up 仍在测量期、未被验证 —— 这是"软"参考,不是硬熔断。 */
function tradeEv(action: Decision["action"], pUp: number, rr: number | null | undefined): number | null {
  if (rr == null || !isFinite(rr) || rr <= 0) return null;
  if (action !== "LONG_QBTX" && action !== "SHORT_QBTZ") return null;
  const pWin = action === "LONG_QBTX" ? pUp : 1 - pUp;
  return pWin * rr - (1 - pWin);
}

/* 给 Vivienne（完全不懂术语）看的极简动作 + 万一模型没生成 note 时的兜底文案 */
function vivienneAction(action: Decision["action"] | undefined) {
  switch (action) {
    case "LONG_QBTX":
      return { emoji: "📈", line: "今天买一点点（我们押它会涨）",
        fallback: "今天我打算用一点点钱买进，赌它接下来会涨～只用很少的钱试试，就算看错了也亏不到哪去，别担心。" };
    case "SHORT_QBTZ":
      return { emoji: "📉", line: "今天买一点点（我们押它会跌）",
        fallback: "今天我打算押它会跌来赚一点，一样只动用很少的钱。放心，万一猜错亏的也有限，不会伤到我们。" };
    default:
      return { emoji: "☕", line: "今天先不买也不卖，安心等等",
        fallback: "今天行情看不太清楚，我们就先按兵不动，钱稳稳放着最安心。等出现好机会我再出手，不急的～" };
  }
}

export default function Dashboard() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [live, setLive] = useState<LiveQuote | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSnap(await getSnapshot());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  // Live quote: fetch immediately, then poll every 30s.
  useEffect(() => {
    let stop = false;
    const tick = async () => {
      const q = await getLiveQuote();
      if (!stop && q) setLive(q);
    };
    tick();
    const id = setInterval(tick, 30_000);
    return () => { stop = true; clearInterval(id); };
  }, []);

  // ── Decision-chart props (memoized so the 30s live-poll re-render doesn't
  // re-init the chart). Stable refs come straight off `snap`; the two derived
  // objects below are the only ones built fresh, so they're memoized. ──────────
  const chartMarkers = useMemo(() =>
    (snap?.journal?.records ?? [])
      .filter(r => r.action !== "HOLD" && r.result)
      .map(r => ({
        time: Math.floor(Date.parse(r.date + "T00:00:00Z") / 1000),
        action: r.action,
        correct: r.result?.correct ?? null,
      })),
    [snap?.journal]);
  const chartPlan = useMemo(() => {
    const dd = snap?.decision;
    return dd && dd.action !== "HOLD" && dd.plan_valid !== false
      ? { entry: dd.trade_plan.qbts_entry, stop: dd.trade_plan.qbts_stop,
          target: dd.trade_plan.qbts_target, action: dd.action }
      : null;
  }, [snap?.decision]);

  if (loading && !snap) {
    return (
      <main className="max-w-[1200px] mx-auto px-6 py-10">
        <div className="flex items-center gap-2 text-sm text-[#525461]">
          <span className="inline-block w-2.5 h-2.5 rounded-full bg-[#006FFF] animate-pulse" />
          读取最新决策…
        </div>
      </main>
    );
  }
  if (error && !snap) {
    return (
      <main className="max-w-[1200px] mx-auto px-6 py-10">
        <div className="bg-white rounded-xl border border-red-200 p-6 max-w-xl">
          <div className="text-sm font-semibold text-[#F03A3E] mb-2">⚠️ 加载失败</div>
          <pre className="text-xs font-mono text-[#525461] bg-red-50 rounded-md px-3 py-2 whitespace-pre-wrap">{error}</pre>
          <button onClick={refresh}
                  className="mt-4 px-3 py-1.5 text-xs bg-[#006FFF] text-white rounded-md hover:bg-blue-600">
            重试
          </button>
        </div>
      </main>
    );
  }
  if (!snap) return null;

  const d = snap.decision ?? null;
  const meta = d ? getActionMeta(d.action, d.conviction) : null;
  const todayUp = snap.today_change >= 0;
  const genAt = fmtLocalDateTime(snap.decision_generated_at);   // UTC → 浏览器本地时区

  // ── Plan vitality check: compare LIVE price against the plan's kill level.
  // A displayed plan whose invalidation has been breached is worse than no
  // plan — flag it dead in red instead of letting a stale "buy at $26" stand.
  const liveQbts = live?.quotes?.qbts;
  const liveFresh = live && (Date.now() / 1000 - live.asof_epoch) < 180;
  let planBreached = false;
  if (d && liveFresh && liveQbts) {
    const kill = d.invalidation_price ?? d.trade_plan?.qbts_stop;
    if (typeof kill === "number") {
      if (d.action === "LONG_QBTX"  && liveQbts.price <= kill) planBreached = true;
      if (d.action === "SHORT_QBTZ" && liveQbts.price >= kill) planBreached = true;
    }
  }
  const decisionGenDate = parseUtc(snap.decision_generated_at);
  const decisionAgeH = decisionGenDate
    ? (Date.now() - decisionGenDate.getTime()) / 3_600_000
    : null;
  const planStale = decisionAgeH !== null && decisionAgeH > 36;
  // CHoCH 早期预警:最近一次结构事件是 CHoCH(性格转变)= 反转苗头但尚未被 BOS 确认。
  // 纯提示,不参与决策信号 —— 填补"等确认所以进场晚"的空窗。
  const choch = snap.smc?.last_event?.kind === "CHoCH" ? snap.smc.last_event : null;
  // SMC 顺势纪律 Playbook(全局锁→降维中继→15m 扣扳机→FVG)= 系统的整体评判标准。
  // 盘中由每分钟心跳每 ~5min 刷新写进 live_quote,比每日快照新 → 有则优先用 live 那份。
  const livePb = live?.smc?.playbook ?? null;
  const pb = livePb ?? snap.smc?.playbook ?? null;
  const pbLive = !!livePb;

  // 模拟持仓:当前未平方向单的浮动盈亏(用实时 QBTS 价 vs 入场,按标的、未计 2× 杠杆)
  const jPaper = snap.journal?.paper ?? null;
  const jLiveQ = live?.quotes?.qbts?.price;
  let jUnreal: number | null = null;
  if (jPaper?.open && typeof jLiveQ === "number" && jPaper.open.entry > 0) {
    const { action, entry } = jPaper.open;
    jUnreal = (action === "SHORT_QBTZ" ? (entry - jLiveQ) : (jLiveQ - entry)) / entry * jPaper.trade_usd;
  }

  const newsTop = (snap.news?.items ?? [])
    .filter(n => n.ai?.impact !== "low")
    .slice(0, 5);

  return (
    <main className="max-w-[1200px] mx-auto px-4 sm:px-6 py-5 sm:py-6 space-y-4">

      {/* ══ 控制台：出决策 / 实时报价按钮（仅本地后端可达时显示）═══════════ */}
      <ControlPanel onPublished={refresh} />

      {/* ══ 0. 计划状态警报 ═══════════════════════════════════════════════ */}
      {planBreached && d && (
        <div className="bg-red-600 text-white rounded-xl px-5 py-3.5 flex items-start gap-3 shadow-md">
          <span className="text-xl leading-none mt-0.5">🚨</span>
          <div className="text-sm leading-relaxed">
            <span className="font-bold">本交易计划已失效</span> — 实时价
            ${liveQbts!.price.toFixed(2)} 已
            {d.action === "LONG_QBTX" ? "跌破" : "涨破"}失效位
            ${(d.invalidation_price ?? d.trade_plan?.qbts_stop)?.toFixed(2)}。
            下方计划仅作历史参考，请勿按其执行；在本地运行
            <code className="mx-1 px-1 rounded bg-white/20 font-mono text-xs">python publish.py</code>
            生成新决策。
          </div>
        </div>
      )}
      {!planBreached && planStale && d && (
        <div className="bg-amber-50 border border-amber-300 text-amber-800 rounded-xl px-5 py-3 text-sm">
          ⏳ 本决策生成于 {Math.round(decisionAgeH!)} 小时前，市场可能已变化 — 建议重新运行
          <code className="mx-1 px-1 rounded bg-amber-100 font-mono text-xs">publish.py</code> 更新。
        </div>
      )}

      {/* ══ CHoCH 早期反转预警 — 结构性格转变但未被 BOS 确认时提示，不发交易信号 ═══ */}
      {choch && (
        <div className="bg-indigo-50 border border-indigo-200 text-indigo-800 rounded-xl px-5 py-3 text-sm leading-relaxed flex items-start gap-2">
          <span className="text-base leading-none mt-0.5">🔭</span>
          <div>
            <span className="font-semibold">早期{choch.dir === "bullish" ? "见底" : "见顶"}预警</span>
            ：{choch.date} 在 ${choch.level.toFixed(2)} 出现
            <span className="font-semibold">{choch.dir === "bullish" ? "看涨" : "看跌"} CHoCH</span>
            （结构性格转变，可能{choch.dir === "bullish" ? "见底转涨" : "见顶转跌"}的苗头）。
            <span className="text-indigo-500"> 这是早期提示、<b>尚未被 BOS 确认</b>，系统不会据此发交易信号 —— 仅供你提前留意，要不要抢跑自己定。</span>
          </div>
        </div>
      )}

      {/* ══ 💌 给 Vivienne 的（大白话，无术语）══════════════════════════════ */}
      <section className="rounded-2xl border border-rose-200 bg-gradient-to-br from-rose-50 to-pink-50/40 p-5 shadow-sm">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-base">💌</span>
          <span className="text-sm font-semibold text-rose-700">给 Vivienne 的</span>
          <span className="ml-auto text-[10px] text-rose-300 font-mono">{snap.as_of?.slice(0, 10)}</span>
        </div>
        {(() => {
          const v = vivienneAction(d?.action);
          return (
            <>
              <div className="flex items-center gap-2.5 mb-2.5">
                <span className="text-2xl leading-none">{v.emoji}</span>
                <span className="text-lg font-bold text-gray-800">{v.line}</span>
              </div>
              <p className="text-[15px] leading-relaxed text-gray-700 whitespace-pre-line">
                {d?.vivienne_note ?? v.fallback}
              </p>
              <div className="mt-3 text-[10px] text-rose-300">💕 这是 Vivienne 专属的解释卡，下面是给我看的技术细节</div>
            </>
          );
        })()}
      </section>

      {/* ══ 1. HERO：价格 + 行动 ══════════════════════════════════════════ */}
      <section className="bg-white rounded-2xl border border-[#EDEDF0] overflow-hidden shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] items-stretch">
          {/* 价格区 — live quote preferred, snapshot fallback */}
          <div className="p-6">
            {(() => {
              const lq = live?.quotes?.qbts;
              const fresh = live && (Date.now() / 1000 - live.asof_epoch) < 180; // <3min
              const price  = fresh && lq ? lq.price : snap.price;
              const chgPct = fresh && lq && lq.change_pct != null ? lq.change_pct : snap.today_change;
              const up = chgPct >= 0;
              const badge = fresh && live ? SESSION_BADGE[live.session] : null;
              const lqx = fresh ? live?.quotes?.qbtx : null;
              const lqz = fresh ? live?.quotes?.qbtz : null;
              return (
                <div className="flex items-baseline gap-3 flex-wrap">
                  <span className="text-xs text-[#525461] uppercase tracking-wider">QBTS</span>
                  <span className="text-4xl font-bold text-gray-900">${price.toFixed(2)}</span>
                  <span className={`text-xl font-semibold ${up ? "text-emerald-600" : "text-[#F03A3E]"}`}>
                    {up ? "▲" : "▼"} {Math.abs(chgPct * 100).toFixed(2)}%
                  </span>
                  {badge && (
                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${badge.cls}`}>
                      {badge.label} · {live!.asof_et.slice(11, 16)} ET
                      {epochMelbTime(live!.asof_epoch) ? ` (墨 ${epochMelbTime(live!.asof_epoch)})` : ""}
                    </span>
                  )}
                  <span className="text-xs text-gray-400 font-mono">
                    QBTX {fmtPx(lqx?.price ?? snap.etf_prices?.qbtx)} · QBTZ {fmtPx(lqz?.price ?? snap.etf_prices?.qbtz)}
                  </span>
                </div>
              );
            })()}
            {/* 一段话总结 */}
            {d ? (
              <p className="mt-3 text-[15px] leading-relaxed text-gray-800">{d.summary}</p>
            ) : (
              <p className="mt-3 text-sm text-gray-400">
                还没有 AI 决策 — 在本地运行 <code className="font-mono bg-gray-100 px-1 rounded">python publish.py</code> 生成。
              </p>
            )}
            <div className="mt-2 text-[10px] text-gray-400">
              数据截至 {snap.as_of?.slice(0, 10)}{genAt ? ` · 决策生成于 ${genAt}` : ""} · 由 Claude 综合全部信号生成 · 非投资建议
            </div>
          </div>

          {/* 行动卡 */}
          {d && meta && (
            <div className={`md:w-[300px] border-t-2 md:border-t-0 md:border-l-2 ${meta.cls} p-6 flex flex-col items-center justify-center text-center`}>
              <div className="text-xs uppercase tracking-widest opacity-70 mb-1">今日行动</div>
              <div className="text-4xl font-bold">{meta.title}</div>
              <div className="text-xs opacity-75 mt-1">{meta.sub}</div>
              {/* 信心条 */}
              <div className="w-full mt-4">
                <div className="flex justify-between text-[10px] opacity-70 mb-1">
                  <span>信心 {d.conviction}/10</span>
                  <span>P(up,5d) {(d.p_up_5d * 100).toFixed(0)}%</span>
                </div>
                <div className="h-2 bg-white/70 rounded-full overflow-hidden border border-current/10">
                  <div className={`h-full ${meta.bar}`} style={{ width: `${d.conviction * 10}%` }} />
                </div>
                <div className="text-[9px] opacity-50 mt-1.5 text-center">{CONVICTION_LEGEND}</div>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* 当日一致性护栏 — 今天多次生成结果反复 → 视为无明确优势 */}
      {d?.intraday_unstable && (
        <div className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          ⚠️ <span className="font-semibold">今日判断不稳定</span>：今天多次生成,结果在{" "}
          <span className="font-mono">
            {(d.intraday_actions ?? [])
              .map(a => (a === "LONG_QBTX" ? "做多" : a === "SHORT_QBTZ" ? "做空" : "观望"))
              .join(" → ")}
          </span>{" "}
          之间反复。模型本身带随机性,信心临界点上会翻面 —— <span className="font-semibold">这本身就说明今天没有清晰优势</span>。
          建议<span className="font-semibold">视为观望</span>,别在反复的答案里挑你想要的那个。
        </div>
      )}

      {d && (
        <>
          {/* ══ 2. 交易计划 + 3. 关键驱动 ══════════════════════════════════ */}
          <section className="grid grid-cols-1 lg:grid-cols-[380px_1fr] gap-4">
            {/* 交易计划 */}
            <div className="bg-white rounded-2xl border border-[#EDEDF0] p-5">
              <div className="text-xs font-semibold text-[#525461] uppercase tracking-wider mb-3">
                📋 交易计划
              </div>
              {/* 方向 — 一眼看清是做多还是做空、实际买哪个 ETF */}
              <div className={`text-sm font-semibold rounded-lg px-3 py-2 mb-3 ${
                d.action === "LONG_QBTX" ? "bg-emerald-50 text-emerald-700"
                : d.action === "SHORT_QBTZ" ? "bg-red-50 text-red-700"
                : "bg-[#F6F6F8] text-[#525461]"}`}>
                {d.action === "LONG_QBTX" ? "📈 做多 QBTS — 买入 QBTX"
                 : d.action === "SHORT_QBTZ" ? "📉 做空 QBTS — 买入 QBTZ"
                 : "⏸️ 观望 — 暂不持仓"}
              </div>
              {/* HOLD has no single entry/stop/target — show the watch state
                  instead of an empty price table (which reads as "broken"). */}
              {d.action === "HOLD" ? (
                <div className="text-sm text-[#525461] bg-[#F6F6F8] rounded-lg px-3 py-3 leading-relaxed">
                  📭 <span className="font-semibold text-gray-700">观望中 · 暂不持仓</span>
                  <div className="mt-1 text-xs">
                    满足入场条件(见下方「展开看细节」)后再按对应方向进场;在此之前没有入场 / 止损 / 目标价,仓位 0%。
                  </div>
                </div>
              ) : d.plan_valid === false ? (
                /* Geometry check failed (stop/target on the wrong side) — never
                   show numbers the user might trade on; tell them to regenerate. */
                <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-3 leading-relaxed">
                  ⚠️ <span className="font-semibold">计划价位不自洽</span>(止损/目标方向异常),已隐藏以防误用。
                  <div className="mt-1 text-xs">请重新运行 <code className="font-mono bg-red-100 px-1 rounded">publish.py</code> 生成新计划。</div>
                </div>
              ) : (
                <>
                  <table className="w-full text-sm">
                    <tbody>
                      {d.trade_plan.etf_ticker && (
                        <tr className="border-b border-[#F0F0F2]">
                          <td className="py-1.5 text-[#525461] text-xs">
                            <span className="font-semibold text-gray-700">{d.trade_plan.etf_ticker}</span> 入场 / 止损 / 目标
                          </td>
                          <td className="py-1.5 text-right font-mono">
                            {fmtPx(d.trade_plan.etf_entry)} / <span className="text-[#F03A3E]">{fmtPx(d.trade_plan.etf_stop)}</span> / <span className="text-emerald-600">{fmtPx(d.trade_plan.etf_target)}</span>
                          </td>
                        </tr>
                      )}
                      <tr className="border-b border-[#F0F0F2]">
                        <td className="py-1.5 text-[#525461] text-xs">盈亏比</td>
                        <td className="py-1.5 text-right font-mono font-semibold">
                          1 : {d.trade_plan.rr_ratio?.toFixed(1) ?? "—"}
                        </td>
                      </tr>
                      <tr>
                        <td className="py-1.5 text-[#525461] text-xs">建议仓位</td>
                        <td className="py-1.5 text-right font-mono font-semibold">
                          {d.trade_plan.suggested_position_pct}% 资金
                        </td>
                      </tr>
                    </tbody>
                  </table>
                  {/* 负 EV 软警告:用系统自己的胜率估计 × 盈亏比 */}
                  {(() => {
                    const ev = tradeEv(d.action, d.p_up_5d, d.trade_plan.rr_ratio);
                    if (ev == null || ev >= 0) return null;
                    const pWin = d.action === "LONG_QBTX" ? d.p_up_5d : 1 - d.p_up_5d;
                    return (
                      <div className="mt-3 text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2 leading-relaxed">
                        ⚠️ <span className="font-semibold">期望值为负(EV≈{ev.toFixed(2)})</span>：
                        按系统自己的概率({(pWin * 100).toFixed(0)}% 赢面)× 盈亏比 1:{d.trade_plan.rr_ratio?.toFixed(1)},
                        长期重复做这种赔率赚不回来 —— 赔率太薄或胜算不够,这种更该观望。
                        <span className="block text-red-400 mt-0.5">(胜率仍在验证期,仅作软参考)</span>
                      </div>
                    );
                  })()}
                </>
              )}
              {/* 失效条件 */}
              <div className="mt-3 text-xs text-[#B45309] bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 leading-relaxed">
                ⚠️ <span className="font-semibold">失效条件：</span>{d.invalidation}
              </div>

              {/* 展开看细节 — 把 HVN/BOS/ATR/镜像价位这些收起来,默认不挡视线 */}
              <details className="mt-3 group">
                <summary className="text-[11px] text-[#525461] cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden hover:text-gray-700 flex items-center gap-1">
                  <span className="transition-transform group-open:rotate-90">▸</span>
                  展开看细节(入场条件 · 波动档 · QBTS 价位 · 杠杆说明)
                </summary>
                <div className="mt-2 space-y-2">
                  <div className="text-xs text-gray-700 bg-[#F6F6F8] rounded-lg px-3 py-2 leading-relaxed">
                    <span className="font-semibold">入场条件：</span>{d.trade_plan.entry_condition}
                  </div>
                  {snap.regime?.regime && (
                    <div className="text-[11px] text-[#525461] bg-[#F6F6F8] rounded-lg px-3 py-1.5 leading-snug flex items-start gap-1.5">
                      <span className={`shrink-0 px-1.5 py-0.5 rounded font-bold ${
                        snap.regime.regime === "expansion" ? "bg-amber-100 text-amber-700"
                        : snap.regime.regime === "contraction" ? "bg-blue-50 text-blue-600"
                        : "bg-gray-100 text-gray-500"}`}>
                        🌡️ 波动{snap.regime.regime === "expansion" ? "扩张" : snap.regime.regime === "contraction" ? "收缩" : "正常"}
                        {snap.regime.atr_pct_percentile != null && ` ${snap.regime.atr_pct_percentile.toFixed(0)}%位`}
                      </span>
                      <span className="text-gray-500">{snap.regime.stop_hint}</span>
                    </div>
                  )}
                  {d.action !== "HOLD" && d.plan_valid !== false && (
                    <div className="text-xs text-[#525461] bg-[#F6F6F8] rounded-lg px-3 py-2 font-mono flex justify-between gap-2">
                      <span className="shrink-0">QBTS 入场/止损/目标</span>
                      <span className="text-right">
                        {fmtPx(d.trade_plan.qbts_entry)} / <span className="text-[#F03A3E]">{fmtPx(d.trade_plan.qbts_stop)}</span> / <span className="text-emerald-600">{fmtPx(d.trade_plan.qbts_target)}</span>
                      </span>
                    </div>
                  )}
                  {d.trade_plan.etf_ticker && d.action !== "HOLD" && (
                    <div className="text-[10px] text-gray-400 leading-snug px-1">
                      {d.trade_plan.etf_ticker} 价位由实时报价按 2× 自动换算(入场时刻精确);杠杆 ETF 每日再平衡,持仓多日有衰减,止损/目标价仅为近似参考。
                    </div>
                  )}
                </div>
              </details>
            </div>

            {/* 关键驱动 + 风险 */}
            <div className="bg-white rounded-2xl border border-[#EDEDF0] p-5">
              <div className="text-xs font-semibold text-[#525461] uppercase tracking-wider mb-3">
                🧭 为什么 — 关键驱动
              </div>
              <div className="space-y-2">
                {d.key_drivers.map((k, i) => (
                  <div key={i} className="flex items-start gap-2.5">
                    <span className={`shrink-0 mt-0.5 text-sm ${k.direction === "bullish" ? "text-emerald-600" : "text-[#F03A3E]"}`}>
                      {k.direction === "bullish" ? "▲" : "▼"}
                    </span>
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-medium text-gray-900">{k.name}</span>
                      <span className={`ml-2 text-[10px] px-1.5 py-0.5 rounded font-semibold
                        ${k.strength === "强" ? "bg-violet-100 text-violet-700"
                          : k.strength === "中" ? "bg-blue-50 text-blue-600"
                          : "bg-gray-100 text-gray-500"}`}>
                        {k.strength}
                      </span>
                      <p className="text-xs text-[#525461] mt-0.5 leading-snug">{k.note}</p>
                    </div>
                  </div>
                ))}
              </div>
              {d.risks?.length > 0 && (
                <div className="mt-4 pt-3 border-t border-[#F0F0F2]">
                  <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1.5">主要风险</div>
                  <ul className="space-y-1">
                    {d.risks.map((r, i) => (
                      <li key={i} className="text-xs text-[#525461] leading-snug">• {r}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </section>

          {/* ══ 4. 未来催化剂 ═══════════════════════════════════════════════ */}
          {d.upcoming_catalysts?.length > 0 && (
            <section className="bg-white rounded-2xl border border-[#EDEDF0] p-5">
              <div className="text-xs font-semibold text-[#525461] uppercase tracking-wider mb-3">
                📅 接下来盯什么
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2.5">
                {d.upcoming_catalysts.map((c, i) => (
                  <div key={i} className="border border-[#EDEDF0] rounded-lg px-3 py-2.5 bg-[#FAFBFC]">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-mono font-semibold text-gray-900">{c.date}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold
                        ${c.impact === "高" ? "bg-red-100 text-red-700"
                          : c.impact === "中" ? "bg-amber-100 text-amber-700"
                          : "bg-gray-100 text-gray-500"}`}>
                        {c.impact}冲击
                      </span>
                    </div>
                    <div className="text-sm font-medium text-gray-900">{c.event}</div>
                    <div className="text-xs text-[#525461] mt-0.5 leading-snug">{c.note}</div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}

      {/* ══ 4.5 宏观日历（原始数据直显，独立于 AI 决策）═══════════════════ */}
      {snap.macro && snap.macro.events.length > 0 && (
        <section className={`rounded-2xl border p-5 ${
          snap.macro.risk_window
            ? "bg-red-50/60 border-red-200"
            : "bg-white border-[#EDEDF0]"}`}>
          <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
            <div className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
              🌐 宏观日历 · 未来14天
            </div>
            <div className={`text-xs font-medium ${snap.macro.risk_window ? "text-red-700" : "text-gray-400"}`}>
              {snap.macro.risk_window ? `⚠️ ${snap.macro.risk_note}` : snap.macro.risk_note}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {snap.macro.events.map((e, i) => (
              <div key={i}
                   className={`rounded-lg border px-3 py-2 text-xs ${
                     e.nuclear
                       ? "bg-white border-red-300"
                       : "bg-white border-[#EDEDF0]"}`}>
                <div className="flex items-center gap-1.5">
                  {e.nuclear && <span className="text-red-500">🔴</span>}
                  <span className="font-mono font-semibold text-gray-900">
                    {e.date.slice(5)} {e.time_et}ET{etMelbSuffix(e.date, e.time_et)}
                  </span>
                  <span className="font-medium text-gray-800">{e.title}</span>
                  {typeof e.hours_until === "number" && e.hours_until >= 0 && e.hours_until <= 48 && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded font-bold bg-red-500 text-white">
                      {e.hours_until < 1 ? "即将发布" : `${Math.round(e.hours_until)}小时后`}
                    </span>
                  )}
                  {typeof e.hours_until === "number" && e.hours_until < 0 && e.hours_until > -24 && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded font-semibold bg-gray-200 text-gray-600">
                      已公布
                    </span>
                  )}
                  {(() => {
                    const s = macroSurprise(e.title, e.forecast, e.actual);
                    if (!s) return null;
                    const cls = s.tone === "bad" ? "bg-red-100 text-red-700"
                              : s.tone === "good" ? "bg-green-100 text-green-700"
                              : "bg-gray-100 text-gray-500";
                    return (
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${cls}`}>
                        {s.label}
                      </span>
                    );
                  })()}
                </div>
                {(e.forecast || e.previous || e.actual) && (
                  <div className="text-[10px] text-gray-500 mt-0.5 font-mono">
                    预测 {e.forecast || "—"} · 前值 {e.previous || "—"}
                    {e.actual && ` · 实际 ${e.actual}`}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ══ 4.7 SMC 结构 + 历史战绩 ═══════════════════════════════════════ */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* SMC 聪明钱结构 */}
        {snap.smc && (
          <div className="bg-white rounded-2xl border border-[#EDEDF0] p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
                🧠 SMC 聪明钱结构
              </span>
              <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold ${
                snap.smc.signal > 0 ? "bg-emerald-100 text-emerald-700"
                : snap.smc.signal < 0 ? "bg-red-100 text-red-700"
                : "bg-gray-100 text-gray-500"}`}>
                {snap.smc.signal > 0 ? "偏多" : snap.smc.signal < 0 ? "偏空" : "中性"}
              </span>
            </div>
            {/* ── 顺势纪律 Playbook(整体评判标准):全局锁 → 降维中继 → 15m 扣扳机 → FVG ── */}
            {pb && (
              <div className="mb-3 rounded-xl border border-[#EDEDF0] bg-[#FAFAFB] p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px] font-semibold text-[#525461] uppercase tracking-wider">
                    ⚖️ 顺势纪律 Playbook
                    {pbLive && (
                      <span className="ml-1.5 inline-flex items-center gap-1 text-[9px] font-bold text-emerald-600 normal-case">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />盘中实时
                      </span>
                    )}
                  </span>
                  <span className="text-[10px] text-gray-400">满足 {pb.conditions_met}</span>
                </div>
                <div className="flex flex-wrap items-center gap-2 mb-2">
                  <span className={`px-2 py-1 rounded-md text-xs font-bold ${
                    pb.lock === "bull" ? "bg-emerald-600 text-white"
                    : pb.lock === "bear" ? "bg-red-600 text-white"
                    : "bg-gray-400 text-white"}`}>
                    {pb.lock === "bull" ? "多头锁定" : pb.lock === "bear" ? "空头锁定" : "无锁定"}
                  </span>
                  <span className={`px-2 py-1 rounded-md text-xs font-bold ${
                    pb.state === "TRIGGER" ? "bg-emerald-100 text-emerald-800 ring-1 ring-emerald-300"
                    : pb.state === "ARMED" ? "bg-amber-100 text-amber-800 ring-1 ring-amber-300"
                    : pb.state === "WAIT" ? "bg-blue-50 text-blue-700"
                    : "bg-gray-100 text-gray-500"}`}>
                    {pb.state === "TRIGGER" ? "🎯 " : pb.state === "ARMED" ? "⏳ " : ""}{pb.state_cn}
                  </span>
                  {pb.lock_reason && (
                    <span className="text-[10px] text-gray-400 font-mono">{pb.lock_reason}</span>
                  )}
                </div>
                <p className="text-[11px] text-[#525461] leading-snug mb-2">{pb.bias_note}</p>
                {/* 扣扳机清单(AND 逻辑,全 ✓ 才进场) */}
                <div className="space-y-1 mb-2">
                  {pb.checklist.map((c) => (
                    <div key={c.key} className="flex items-start gap-1.5 text-[11px] leading-snug">
                      <span className={c.ok ? "text-emerald-600 font-bold" : "text-gray-300"}>
                        {c.ok ? "✓" : "○"}
                      </span>
                      <span className={c.ok ? "text-[#1A1A1E] font-medium shrink-0" : "text-gray-400 shrink-0"}>
                        {c.label}
                      </span>
                      <span className="text-gray-400 ml-auto text-right">{c.detail}</span>
                    </div>
                  ))}
                </div>
                {/* 交易计划:共振入场 / 止损 / FVG 磁吸止盈 */}
                {(pb.entry_zone || pb.tp1) && (
                  <div className="grid grid-cols-2 gap-1.5 text-[11px] pt-2 border-t border-[#EDEDF0]">
                    {pb.entry_zone && (
                      <div className="col-span-2 flex items-center justify-between px-2 py-1 rounded-md bg-violet-50 text-violet-700">
                        <span className="font-medium">🎯 共振入场 [{pb.entry_zone.basis}]</span>
                        <span className="font-mono">${pb.entry_zone.low.toFixed(2)} – ${pb.entry_zone.high.toFixed(2)}</span>
                      </div>
                    )}
                    {pb.stop != null && (
                      <div className="flex items-center justify-between px-2 py-1 rounded-md bg-red-50 text-red-700">
                        <span className="font-medium">止损</span><span className="font-mono">${pb.stop.toFixed(2)}</span>
                      </div>
                    )}
                    {pb.rr != null && (
                      <div className="flex items-center justify-between px-2 py-1 rounded-md bg-gray-50 text-gray-600">
                        <span className="font-medium">盈亏比</span><span className="font-mono">{pb.rr.toFixed(1)}</span>
                      </div>
                    )}
                    {pb.tp1 && (
                      <div className="col-span-2 flex items-center justify-between px-2 py-1 rounded-md bg-emerald-50 text-emerald-700">
                        <span className="font-medium">TP1 · {pb.tp1.basis}</span>
                        <span className="font-mono">${pb.tp1.price.toFixed(2)}</span>
                      </div>
                    )}
                    {pb.tp2 && (
                      <div className="col-span-2 flex items-center justify-between px-2 py-1 rounded-md bg-emerald-50/50 text-emerald-600">
                        <span className="font-medium">TP2 · {pb.tp2.basis}</span>
                        <span className="font-mono">${pb.tp2.price.toFixed(2)}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
            <div className="flex flex-wrap gap-2 mb-3 text-xs">
              <span className={`px-2 py-1 rounded-md font-medium ${
                snap.smc.trend === "bullish" ? "bg-emerald-50 text-emerald-700"
                : snap.smc.trend === "bearish" ? "bg-red-50 text-red-700"
                : "bg-gray-50 text-gray-600"}`}>
                结构 {snap.smc.trend === "bullish" ? "看多" : snap.smc.trend === "bearish" ? "看空" : "中性"}
              </span>
              {snap.smc.last_event && (
                <span className="px-2 py-1 rounded-md bg-violet-50 text-violet-700 font-medium">
                  {snap.smc.last_event.date} {snap.smc.last_event.dir === "bullish" ? "↗" : "↘"} {snap.smc.last_event.kind} @ ${snap.smc.last_event.level.toFixed(2)}
                </span>
              )}
              <span className="px-2 py-1 rounded-md bg-blue-50 text-blue-700 font-medium">
                {snap.smc.zone} {(snap.smc.range_position * 100).toFixed(0)}%
              </span>
              {/* 多周期共振 (1h vs 日线) */}
              {snap.smc.ltf && snap.smc.confluence && (
                <span className={`px-2 py-1 rounded-md font-medium ${
                  snap.smc.confluence === "aligned" ? "bg-emerald-50 text-emerald-700"
                  : snap.smc.confluence === "conflict" ? "bg-amber-50 text-amber-700"
                  : "bg-gray-50 text-gray-500"}`}>
                  1h {snap.smc.ltf.trend === "bullish" ? "↗" : snap.smc.ltf.trend === "bearish" ? "↘" : "→"}
                  {snap.smc.confluence === "aligned" ? " 同向" : snap.smc.confluence === "conflict" ? " 背离" : " 中性"}
                </span>
              )}
            </div>
            {/* 相对强度 — 一行(prompt 已用，此处只给用户一个语境标注) */}
            {snap.relative_strength?.rationale && (
              <div className="text-[11px] text-[#525461] bg-[#F6F6F8] rounded-md px-2.5 py-1.5 mb-2 leading-snug">
                📊 {snap.relative_strength.rationale}
              </div>
            )}
            {/* 关键区域 */}
            <div className="space-y-1.5 text-xs">
              {snap.smc.supply_zones.map((z, i) => (
                <div key={`s${i}`} className="flex items-center justify-between px-2.5 py-1.5 rounded-md bg-red-50/60 border border-red-100">
                  <span className="text-red-700 font-medium">▼ 供给区 [{z.kind}]</span>
                  <span className="font-mono text-gray-700">${z.low.toFixed(2)} – ${z.high.toFixed(2)}</span>
                </div>
              ))}
              {snap.smc.demand_zones.map((z, i) => (
                <div key={`d${i}`} className="flex items-center justify-between px-2.5 py-1.5 rounded-md bg-emerald-50/60 border border-emerald-100">
                  <span className="text-emerald-700 font-medium">▲ 需求区 [{z.kind}]</span>
                  <span className="font-mono text-gray-700">${z.low.toFixed(2)} – ${z.high.toFixed(2)}</span>
                </div>
              ))}
              {snap.smc.sweeps.slice(-2).map((s, i) => (
                <div key={`w${i}`} className="text-[11px] text-[#525461] px-2.5 py-1">
                  💧 {s.note}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 历史战绩 */}
        <div className="bg-white rounded-2xl border border-[#EDEDF0] p-5">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
              📒 历史决策战绩
            </span>
            <div className="flex flex-col items-end gap-0.5">
              {snap.journal?.accuracy != null && (
                <span className={`text-sm font-bold font-mono ${
                  snap.journal.accuracy >= 0.55 ? "text-emerald-600"
                  : snap.journal.accuracy >= 0.45 ? "text-amber-500" : "text-[#F03A3E]"}`}>
                  实盘命中 {(snap.journal.accuracy * 100).toFixed(0)}%
                  <span className="text-[10px] text-gray-400 ml-1">
                    ({snap.journal.n_correct}/{snap.journal.n_graded})
                  </span>
                </span>
              )}
              {snap.journal?.shadow_accuracy != null && (
                <span className="text-[10px] text-gray-400 font-mono" title="含观望日的方向影子判断 — 即使空仓也评判当时的多空倾向是否正确">
                  含观望影子 {(snap.journal.shadow_accuracy * 100).toFixed(0)}%
                  ({snap.journal.n_shadow_correct}/{snap.journal.n_shadow})
                </span>
              )}
            </div>
          </div>
          {jPaper && (
            <div className="mb-3 rounded-lg bg-[#F6F6F8] px-3 py-2.5 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-gray-700">📊 模拟持仓 · 每次 ${jPaper.trade_usd.toLocaleString()} 跟随决策</span>
                <span className="text-[10px] text-gray-400">假钱 · 按标的方向,未计 2× 杠杆</span>
              </div>
              <div className="mt-1.5 font-mono">
                已实现累计{" "}
                <b className={jPaper.realized >= 0 ? "text-emerald-600" : "text-[#F03A3E]"}>{fmtSignedUsd(jPaper.realized)}</b>
                <span className="text-gray-400 ml-1">
                  ({jPaper.n_trades} 笔已平{jPaper.win_rate != null ? ` · 胜率 ${(jPaper.win_rate * 100).toFixed(0)}%` : ""})
                </span>
              </div>
              {jPaper.open ? (
                <div className="mt-1 font-mono">
                  当前持仓：
                  <span className={jPaper.open.action === "SHORT_QBTZ" ? "text-red-700 font-semibold" : "text-emerald-700 font-semibold"}>
                    {jPaper.open.action === "SHORT_QBTZ" ? "做空" : "做多"}
                  </span>
                  <span className="text-gray-500"> 入场 ${jPaper.open.entry}（{jPaper.open.date.slice(5)}）</span>
                  {jUnreal != null && (
                    <> · 浮动 <b className={jUnreal >= 0 ? "text-emerald-600" : "text-[#F03A3E]"}>{fmtSignedUsd(jUnreal)}</b></>
                  )}
                </div>
              ) : (
                <div className="mt-1 text-gray-400">当前空仓（最近决策为观望或已平）</div>
              )}
              {jPaper.n_trades < 10 && (
                <div className="mt-1 text-[10px] text-amber-600">⚠️ 样本极少（{jPaper.n_trades} 笔）——系统多数日子观望、方向单稀少,这个数字还说明不了问题</div>
              )}
            </div>
          )}
          {!snap.journal || snap.journal.records.length === 0 ? (
            <div className="text-xs text-gray-400 py-6 text-center">
              暂无记录 — 从下一次决策开始，每个判断都会被记录并在 5 个交易日后评判
            </div>
          ) : (
            <div className="space-y-2">
              {snap.journal.records.slice(0, 6).map(r => {
                const res = r.result;
                const actionLabel = r.action === "LONG_QBTX" ? "做多" : r.action === "SHORT_QBTZ" ? "做空" : "观望";
                return (
                  <div key={r.id} className="border border-[#F0F0F2] rounded-lg px-3 py-2">
                    <div className="flex items-center gap-2 text-xs">
                      <span className="font-mono text-gray-500">{r.date.slice(5)}</span>
                      <span className={`font-semibold ${
                        r.action === "LONG_QBTX" ? "text-emerald-700"
                        : r.action === "SHORT_QBTZ" ? "text-red-700" : "text-gray-600"}`}>
                        {actionLabel}
                      </span>
                      <span className="text-gray-400">信心{r.conviction} · ${r.price}</span>
                      <span className="ml-auto">
                        {r.status === "pending" ? (
                          <span className="text-[10px] text-gray-400">⏳ 待评判</span>
                        ) : res?.correct === true ? (
                          <span className="text-xs font-bold text-emerald-600">✓ {res.ret_pct != null ? `${(res.ret_pct*100).toFixed(1)}%` : ""}</span>
                        ) : res?.correct === false ? (
                          <span className="text-xs font-bold text-[#F03A3E]">✗ {res.ret_pct != null ? `${(res.ret_pct*100).toFixed(1)}%` : ""}</span>
                        ) : (
                          <span className="text-[10px] text-gray-400">— 观望</span>
                        )}
                      </span>
                    </div>
                    {res?.reflection && (
                      <div className="mt-1.5 text-[11px] text-amber-700 bg-amber-50 rounded px-2 py-1 leading-snug">
                        💡 反思：{res.reflection}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* 🔮 月度复盘按钮 — 一个月后解锁 */}
          <RetrospectivePanel />
        </div>

        {/* 成交量画像 / POC */}
        {snap.volume_profile?.poc != null && (
          <div className="bg-white rounded-2xl border border-[#EDEDF0] p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
                📊 成交量画像 / POC
              </span>
              <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold ${
                snap.volume_profile.price_vs_value === "above" ? "bg-emerald-100 text-emerald-700"
                : snap.volume_profile.price_vs_value === "below" ? "bg-red-100 text-red-700"
                : "bg-gray-100 text-gray-500"}`}>
                现价{snap.volume_profile.price_vs_value === "above" ? "在价值区上方"
                  : snap.volume_profile.price_vs_value === "below" ? "在价值区下方" : "在价值区内"}
              </span>
            </div>
            {/* 价值区刻度 */}
            <div className="flex items-center justify-between text-xs mb-3 px-1">
              <span className="text-red-600 font-mono">VAL ${snap.volume_profile.val.toFixed(2)}</span>
              <span className="font-mono font-bold text-violet-700">POC ${snap.volume_profile.poc.toFixed(2)}</span>
              <span className="text-emerald-600 font-mono">VAH ${snap.volume_profile.vah.toFixed(2)}</span>
            </div>
            {/* 操作提示 — 把磁吸位翻译成明确的突破/跌破触发 */}
            {snap.volume_profile.action_hint && (
              <div className="flex items-start gap-2 text-xs bg-indigo-50/70 border border-indigo-100 rounded-lg px-3 py-2 mb-3 leading-snug">
                <span className={`shrink-0 px-1.5 py-0.5 rounded font-bold ${
                  snap.volume_profile.stance === "偏多" ? "bg-emerald-100 text-emerald-700"
                  : snap.volume_profile.stance === "偏空" ? "bg-red-100 text-red-700"
                  : "bg-gray-100 text-gray-500"}`}>
                  👉 {snap.volume_profile.stance}
                </span>
                <span className="text-gray-700">{snap.volume_profile.action_hint}</span>
              </div>
            )}
            <div className="space-y-1.5 text-xs">
              {snap.volume_profile.nearest_magnet_up != null && (
                <div className="flex items-center justify-between px-2.5 py-1.5 rounded-md bg-emerald-50/60 border border-emerald-100">
                  <span className="text-emerald-700 font-medium">▲ 上方磁吸</span>
                  <span className="font-mono text-gray-700">${snap.volume_profile.nearest_magnet_up.toFixed(2)}</span>
                </div>
              )}
              {snap.volume_profile.nearest_magnet_down != null && (
                <div className="flex items-center justify-between px-2.5 py-1.5 rounded-md bg-red-50/60 border border-red-100">
                  <span className="text-red-700 font-medium">▼ 下方磁吸</span>
                  <span className="font-mono text-gray-700">${snap.volume_profile.nearest_magnet_down.toFixed(2)}</span>
                </div>
              )}
              {snap.volume_profile.naked_pocs_above.length + snap.volume_profile.naked_pocs_below.length > 0 && (
                <div className="text-[11px] text-[#525461] px-2.5 py-1 leading-snug">
                  🧲 未回补 POC：
                  {[...snap.volume_profile.naked_pocs_above, ...snap.volume_profile.naked_pocs_below]
                    .map(x => `$${x.toFixed(2)}`).join("、")}
                </div>
              )}
              {snap.volume_profile.lvn.length > 0 && (
                <div className="text-[11px] text-gray-400 px-2.5 leading-snug">
                  LVN 真空带(勿设止损)：{snap.volume_profile.lvn.map(x => `$${x.toFixed(2)}`).join("、")}
                </div>
              )}
            </div>
          </div>
        )}

        {/* 挤空燃料 */}
        {snap.squeeze?.fuel_score != null && (
          <div className="bg-white rounded-2xl border border-[#EDEDF0] p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
                🔥 挤空燃料
              </span>
              <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold ${
                snap.squeeze.fuel_label === "高" ? "bg-emerald-100 text-emerald-700"
                : snap.squeeze.fuel_label === "中" ? "bg-amber-100 text-amber-700"
                : "bg-gray-100 text-gray-500"}`}>
                燃料{snap.squeeze.fuel_label}
              </span>
            </div>
            {/* 燃料计量条 */}
            <div className="flex items-center gap-2 mb-3">
              <span className="text-lg font-bold font-mono text-gray-800">{snap.squeeze.fuel_score.toFixed(0)}</span>
              <span className="text-[10px] text-gray-400">/100</span>
              <div className="flex-1 h-2 rounded-full bg-gray-100 overflow-hidden">
                <div className={`h-full rounded-full ${
                  snap.squeeze.fuel_label === "高" ? "bg-emerald-500"
                  : snap.squeeze.fuel_label === "中" ? "bg-amber-400" : "bg-gray-300"}`}
                  style={{ width: `${Math.min(100, snap.squeeze.fuel_score)}%` }} />
              </div>
            </div>
            {/* 三个分量 */}
            <div className="grid grid-cols-3 gap-2 mb-3 text-center">
              {([["空仓", snap.squeeze.components.short, 40],
                 ["期权", snap.squeeze.components.options, 35],
                 ["13F", snap.squeeze.components.holdings, 25]] as const).map(([lbl, v, max]) => (
                <div key={lbl} className="bg-[#F6F6F8] rounded-lg py-1.5">
                  <div className="text-[10px] text-gray-400">{lbl}</div>
                  <div className="text-xs font-mono font-semibold text-gray-700">{v.toFixed(0)}<span className="text-gray-300">/{max}</span></div>
                </div>
              ))}
            </div>
            <div className="text-[11px] text-[#525461] leading-snug">{snap.squeeze.rationale}</div>
          </div>
        )}
      </section>

      {/* ══ 5. 今日要闻 + 60日小图 ═══════════════════════════════════════ */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white rounded-2xl border border-[#EDEDF0] p-5">
          <div className="text-xs font-semibold text-[#525461] uppercase tracking-wider mb-3">
            📰 今日要闻
          </div>
          {newsTop.length === 0 ? (
            <div className="text-xs text-gray-400 py-4">暂无高影响新闻</div>
          ) : (
            <div className="space-y-2.5">
              {newsTop.map((n, i) => (
                <a key={i} href={n.url || "#"} target="_blank" rel="noopener noreferrer"
                   className="block group">
                  <div className="flex items-start gap-2">
                    <span className={`shrink-0 mt-1 w-1.5 h-1.5 rounded-full
                      ${n.ai.sentiment === "bullish" ? "bg-emerald-500"
                        : n.ai.sentiment === "bearish" ? "bg-[#F03A3E]" : "bg-gray-300"}`} />
                    <div className="min-w-0">
                      <div className="text-sm text-gray-900 group-hover:text-[#006FFF] transition-colors leading-snug">
                        {n.title}
                      </div>
                      <div className="text-[11px] text-[#525461] mt-0.5">
                        {n.ai.reasoning} <span className="text-gray-400">· {n.publisher} · {n.published?.slice(5, 10)}</span>
                      </div>
                    </div>
                  </div>
                </a>
              ))}
            </div>
          )}
        </div>

        <MiniChart
          candles={snap.chart.candles}
          sma20={snap.chart.sma20}
          sma200={snap.chart.sma200}
          high_52w={snap.chart.high_52w}
          low_52w={snap.chart.low_52w}
          plan={chartPlan}
          supply={snap.smc?.supply_zones}
          demand={snap.smc?.demand_zones}
          poc={snap.volume_profile?.poc ?? null}
          markers={chartMarkers}
          nwBands={snap.nw_envelope?.bands}
        />
      </section>

      <footer className="text-center text-[10px] text-gray-400 pb-4">
        QBTS Quant Lab · AI 决策由 Claude 基于 8 类数据源综合生成 · 每日 publish.py 更新 · 仅供研究参考，非投资建议
      </footer>

      {/* 右下角版本号 */}
      <div className="hidden md:block fixed bottom-2 right-3 z-10 text-[10px] font-mono text-gray-300 select-none pointer-events-none">
        v{APP_VERSION}
      </div>
    </main>
  );
}
