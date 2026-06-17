"use client";

import { useCallback, useEffect, useState } from "react";
import { MiniChart } from "./_components/mini-chart";
import { ControlPanel } from "./_components/control-panel";
import { getSnapshot, getLiveQuote, type Snapshot, type Decision, type LiveQuote } from "./_lib/data";

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

function fmtPx(n: number | null | undefined): string {
  return typeof n === "number" && isFinite(n) ? `$${n.toFixed(2)}` : "—";
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
  const genAt = snap.decision_generated_at?.slice(0, 16).replace("T", " ");

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
  const decisionAgeH = snap.decision_generated_at
    ? (Date.now() - new Date(snap.decision_generated_at).getTime()) / 3_600_000
    : null;
  const planStale = decisionAgeH !== null && decisionAgeH > 36;

  const newsTop = (snap.news?.items ?? [])
    .filter(n => n.ai?.impact !== "low")
    .slice(0, 5);

  return (
    <main className="max-w-[1200px] mx-auto px-6 py-6 space-y-4">

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
            <div className={`md:w-[300px] border-l-2 ${meta.cls} p-6 flex flex-col items-center justify-center text-center`}>
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

      {d && (
        <>
          {/* ══ 2. 交易计划 + 3. 关键驱动 ══════════════════════════════════ */}
          <section className="grid grid-cols-1 lg:grid-cols-[380px_1fr] gap-4">
            {/* 交易计划 */}
            <div className="bg-white rounded-2xl border border-[#EDEDF0] p-5">
              <div className="text-xs font-semibold text-[#525461] uppercase tracking-wider mb-3">
                📋 交易计划
              </div>
              <div className="text-xs text-gray-700 bg-[#F6F6F8] rounded-lg px-3 py-2 mb-3 leading-relaxed">
                <span className="font-semibold">入场条件：</span>{d.trade_plan.entry_condition}
              </div>
              <table className="w-full text-sm">
                <tbody>
                  <tr className="border-b border-[#F0F0F2]">
                    <td className="py-1.5 text-[#525461] text-xs">QBTS 入场 / 止损 / 目标</td>
                    <td className="py-1.5 text-right font-mono">
                      {fmtPx(d.trade_plan.qbts_entry)} / <span className="text-[#F03A3E]">{fmtPx(d.trade_plan.qbts_stop)}</span> / <span className="text-emerald-600">{fmtPx(d.trade_plan.qbts_target)}</span>
                    </td>
                  </tr>
                  {d.trade_plan.etf_ticker && (
                    <tr className="border-b border-[#F0F0F2]">
                      <td className="py-1.5 text-[#525461] text-xs">{d.trade_plan.etf_ticker} 入场 / 止损 / 目标</td>
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
              {/* 失效条件 */}
              <div className="mt-3 text-xs text-[#B45309] bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 leading-relaxed">
                ⚠️ <span className="font-semibold">失效条件：</span>{d.invalidation}
              </div>
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
                    {e.date.slice(5)} {e.time_et}ET
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
                </div>
                {(e.forecast || e.previous) && (
                  <div className="text-[10px] text-gray-500 mt-0.5 font-mono">
                    预测 {e.forecast || "—"} · 前值 {e.previous || "—"}
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
            </div>
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
            {snap.journal?.accuracy != null && (
              <span className={`text-sm font-bold font-mono ${
                snap.journal.accuracy >= 0.55 ? "text-emerald-600"
                : snap.journal.accuracy >= 0.45 ? "text-amber-500" : "text-[#F03A3E]"}`}>
                命中 {(snap.journal.accuracy * 100).toFixed(0)}%
                <span className="text-[10px] text-gray-400 ml-1">
                  ({snap.journal.n_correct}/{snap.journal.n_graded})
                </span>
              </span>
            )}
          </div>
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
        </div>
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
        />
      </section>

      <footer className="text-center text-[10px] text-gray-400 pb-4">
        QBTS Quant Lab · AI 决策由 Claude 基于 8 类数据源综合生成 · 每日 publish.py 更新 · 仅供研究参考，非投资建议
      </footer>
    </main>
  );
}
