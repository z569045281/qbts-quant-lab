"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MiniChart } from "./_components/mini-chart";
import { AuditModal } from "./_components/audit-modal";
import { ControlPanel } from "./_components/control-panel";
import PositionsCard from "./_components/positions-card";
import { RetrospectivePanel } from "./_components/retrospective-panel";
import { SiteCheckOverview } from "./_components/self-check";
import { getSnapshot, getLiveQuote, type Snapshot, type Decision, type LiveQuote, type LiveQuoteEntry } from "./_lib/data";
import { fmtLocalDateTime, parseUtc, etMelbSuffix, epochMelbTime, macroSurprise } from "./_lib/format";
import versionData from "../public/version.json";

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

/* 页面版本号 — 右下角显示。单一来源 public/version.json(版本守卫也读它);发版时 bump 那个文件 */
const APP_VERSION = versionData.version;

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
  // 👀 隐藏点击审计:版本号 1.5s 内连点 3 次打开
  const [auditOpen, setAuditOpen] = useState(false);
  const [modelView, setModelView] = useState<"fable" | "ds">("fable");  // 决策卡 Claude/DeepSeek 切换
  const versionClicks = useRef<number[]>([]);

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

  // DeepSeek 影子决策(同一份数据、同一套规则、零决策权)—— 切换只换展示,
  // 台账/推送/持仓建议的"官方口径"永远是 Fable 主决策
  const dsd = snap.decision?.shadow_ds ?? null;
  const d = modelView === "ds" && dsd ? dsd : (snap.decision ?? null);
  const meta = d ? getActionMeta(d.action, d.conviction) : null;
  const genAt = fmtLocalDateTime(snap.decision_generated_at);   // UTC → 浏览器本地时区

  // ── Plan vitality check: compare LIVE price against the plan's kill level.
  // A displayed plan whose invalidation has been breached is worse than no
  // plan — flag it dead in red instead of letting a stale "buy at $26" stand.
  const liveQbts = live?.quotes?.qbts;
  const decisionGenDate = parseUtc(snap.decision_generated_at);
  // 数据源选择:谁新用谁,全页一个口径(价格 / SMC / 模拟浮盈都走它)。
  // live 盘中每分钟写入、19:59 ET 停更;快照每天 09:00 ET 发布。收盘后 live 虽超过
  // 3 分钟,但"最后报价"仍比快照新几小时 —— 旧闸门整夜回退到快照价,曾比真实收盘
  // 高 1.8%($22.92 vs 收盘 $22.52)。3 分钟新鲜度现在只决定"盘中"徽章和脉冲;
  // 若 quote 推送挂掉、每日重发布的快照反而更新,则自动回退快照 —— 谁新用谁。
  const liveCurrent = !!(liveQbts && live &&
    live.asof_epoch > (decisionGenDate ? decisionGenDate.getTime() / 1000 : 0));
  const liveFresh = !!(live && (Date.now() / 1000 - live.asof_epoch) < 180);
  let planBreached = false;
  if (d && liveCurrent && liveQbts) {
    const kill = d.invalidation_price ?? d.trade_plan?.qbts_stop;
    if (typeof kill === "number") {
      if (d.action === "LONG_QBTX"  && liveQbts.price <= kill) planBreached = true;
      if (d.action === "SHORT_QBTZ" && liveQbts.price >= kill) planBreached = true;
    }
  }
  const decisionAgeH = decisionGenDate
    ? (Date.now() - decisionGenDate.getTime()) / 3_600_000
    : null;
  const planStale = decisionAgeH !== null && decisionAgeH > 36;
  // CHoCH 早期预警:最近一次结构事件是 CHoCH(性格转变)= 反转苗头但尚未被 BOS 确认。
  // 纯提示,不参与决策信号 —— 填补"等确认所以进场晚"的空窗。
  // SMC 读数:盘中每 ~5min 刷新写进 live_quote → 和价格走同一个 liveCurrent 口径,
  // 否则会出现"页面显示 $24.43、但 SMC 卡用的是另一份价算的"、价格在区间内而对应勾
  // 却是灰色的自相矛盾(cross-source 老教训)。
  const smc = (liveCurrent && live?.smc) ? live.smc : (snap.smc ?? null);
  const pbLive = !!(liveFresh && live?.smc);   // 「盘中实时」脉冲只在 <3min 时亮
  const choch = smc?.last_event?.kind === "CHoCH" ? smc.last_event : null;
  const pb = smc?.playbook ?? null;

  // Playbook 的 QBTS 价位 → 实际下单的杠杆 ETF 价格(与 decision.py _conv_etf 同公式:
  // ±2× 线性近似)。空头锁 → QBTZ(−2×),多头锁 → QBTX(+2×);价格与整页同一 liveCurrent
  // 口径。用户曾把空头入场区误读成 QBTX 买点 —— 直接标出该买哪只、什么价,杜绝反向误读。
  const pbEtf = (() => {
    if (!pb || (pb.lock !== "bull" && pb.lock !== "bear")) return null;
    const qbtsNow = liveCurrent && liveQbts ? liveQbts.price : snap.price;
    const sym = pb.lock === "bull" ? ("qbtx" as const) : ("qbtz" as const);
    const etfNow = (liveCurrent ? live?.quotes?.[sym]?.price : null) ?? snap.etf_prices?.[sym];
    if (!qbtsNow || typeof etfNow !== "number") return null;
    const sign = pb.lock === "bull" ? 2 : -2;
    const conv = (level: number | null | undefined) =>
      typeof level === "number" ? etfNow * (1 + sign * (level / qbtsNow - 1)) : null;
    const [eA, eB] = [conv(pb.entry_zone?.low), conv(pb.entry_zone?.high)];
    // 反向 ETF 换算后区间上下颠倒 → 重新排序
    const entryLo = eA != null && eB != null ? Math.min(eA, eB) : (eA ?? eB);
    const entryHi = eA != null && eB != null ? Math.max(eA, eB) : null;
    return { ticker: sym.toUpperCase(), entryLo, entryHi,
             stop: conv(pb.stop), tp1: conv(pb.tp1?.price), tp2: conv(pb.tp2?.price) };
  })();

  // 模拟持仓:当前未平方向单的浮动盈亏(用实时 QBTS 价 vs 入场,按标的、未计 2× 杠杆)
  const jPaper = snap.journal?.paper ?? null;
  const jLiveQ = liveCurrent ? live?.quotes?.qbts?.price : snap.price;  // 与页面价同源
  let jUnreal: number | null = null;
  if (jPaper?.open && typeof jLiveQ === "number" && jPaper.open.entry > 0) {
    const { action, entry } = jPaper.open;
    jUnreal = (action === "SHORT_QBTZ" ? (entry - jLiveQ) : (jLiveQ - entry)) / entry * jPaper.trade_usd;
  }

  const newsTop = (snap.news?.items ?? [])
    .filter(n => n.ai?.impact !== "low")
    .slice(0, 5);

  // 🌍 地缘政治雷达:云端 ~30min 刷新的 live 版优先于每日快照
  const geo = live?.geo ?? snap.geopolitics ?? null;
  const geoLive = !!live?.geo;
  const geoItems = (geo?.items ?? [])
    .filter(g => g.relevance !== "low")
    .slice(0, 7);

  return (
    <main className="max-w-[1200px] mx-auto px-4 sm:px-6 py-5 sm:py-6 space-y-4">

      {/* ══ 控制台：出决策 / 实时报价按钮（仅本地后端可达时显示）═══════════ */}
      <ControlPanel onPublished={refresh} />

      {/* ══ 0-. 周一开盘·周末BTC 信号(周日夜盘 20:00 ET 起显示;第七轮实证)══ */}
      {live?.btc_weekend && (
        <div className={`rounded-xl px-5 py-3.5 flex items-start gap-3 shadow-sm border ${
          live.btc_weekend.green
            ? "bg-emerald-50 border-emerald-200" : "bg-red-50 border-red-200"}`}>
          <span className="text-xl leading-none mt-0.5">🌉</span>
          <div className="text-sm leading-relaxed">
            <span className="font-bold">周一开盘信号 · 周末 BTC {(live.btc_weekend.weekend_ret * 100) >= 0 ? "+" : ""}{(live.btc_weekend.weekend_ret * 100).toFixed(1)}%</span>
            {live.btc_weekend.green ? (
              <span className="text-emerald-800"> 🟢 → 夜盘/盘前可先建仓(QBTS 现货限价单,点差大勿追),或开盘买 QBTX;周一收盘前全部卖出,不过夜。
                回测:开→收 +2.9%、胜率 60%;收→收含跳空 +3.9%</span>
            ) : (
              <span className="text-red-800"> 🔴 → 周一不做多,夜盘也不(历史此情形周一日内均值 −3.0%)</span>
            )}
            <span className="text-gray-400 text-xs"> · n=55 验证期,小仓 · 已推送{live.btc_weekend.pushed ? "✅" : "…"}</span>
          </div>
        </div>
      )}

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

      {/* ══ 💌 给 Vivienne 的（大白话，无术语）══════════════════════════════ */}
      <section className="rounded-3xl border border-rose-200 bg-gradient-to-br from-rose-50 to-pink-50/40 p-5 shadow-sm">
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
      <section className="bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] overflow-hidden shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] items-stretch">
          {/* 价格区 — live quote preferred, snapshot fallback */}
          <div className="p-6">
            {(() => {
              const lq = live?.quotes?.qbts;
              const price  = liveCurrent && lq ? lq.price : snap.price;
              const chgPct = liveCurrent && lq && lq.change_pct != null ? lq.change_pct : snap.today_change;
              const up = chgPct >= 0;
              // <3min → 实时 session 徽章;更旧但仍是最新数据 → 诚实标「已收盘」+最后报价时间
              const badge = liveCurrent && live ? (liveFresh ? SESSION_BADGE[live.session] : SESSION_BADGE.closed) : null;
              const lqx = liveCurrent ? live?.quotes?.qbtx : null;
              const lqz = liveCurrent ? live?.quotes?.qbtz : null;
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
                  {(() => {
                    // 薄流动性 ETF 的最后成交常比 QBTS 旧几十分钟(QBTZ 盘后尤甚)——
                    // 滞后 >15 分钟标 ⏱,免得并排的涨跌幅被当成同一时刻的 2× 关系核对
                    const mins = (bt?: string | null) =>
                      bt && bt.length >= 16 ? parseInt(bt.slice(11, 13)) * 60 + parseInt(bt.slice(14, 16)) : null;
                    const ref = mins(lq?.bar_time);
                    const stale = (e?: LiveQuoteEntry | null) => {
                      const m = mins(e?.bar_time);
                      return ref != null && m != null && ref - m > 15;
                    };
                    return (
                      <span className="text-xs text-gray-400 font-mono">
                        QBTX {fmtPx(lqx?.price ?? snap.etf_prices?.qbtx)}
                        {stale(lqx) && <span title={`最后成交 ${lqx?.bar_time?.slice(11, 16)},比 QBTS 旧 >15 分钟(薄流动性),涨跌口径不同步`}>⏱</span>}
                        {" · "}QBTZ {fmtPx(lqz?.price ?? snap.etf_prices?.qbtz)}
                        {stale(lqz) && <span title={`最后成交 ${lqz?.bar_time?.slice(11, 16)},比 QBTS 旧 >15 分钟(薄流动性),涨跌口径不同步`}>⏱</span>}
                      </span>
                    );
                  })()}
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
            {dsd && (
              <div className="mt-3 flex items-center gap-1.5 flex-wrap">
                {(["fable", "ds"] as const).map(m => (
                  <button key={m} onClick={() => setModelView(m)}
                    className={`text-[11px] px-2.5 py-1 rounded-full border font-medium transition-colors ${
                      modelView === m
                        ? "bg-[#006FFF] text-white border-[#006FFF]"
                        : "bg-white text-[#525461] border-[#EDEDF0] hover:border-gray-300"}`}>
                    {m === "fable" ? "Fable 5 · 主决策" : "DeepSeek · 影子"}
                  </button>
                ))}
                {modelView === "ds" && (
                  <span className="text-[10px] text-amber-600 font-medium">
                    影子对照:不驱动交易/推送/台账;方向表态另记分,8/15 与 Fable 同框宣判
                  </span>
                )}
              </div>
            )}
            <div className="mt-2 text-[10px] text-gray-400">
              数据截至 {snap.as_of?.slice(0, 10)}{genAt ? ` · 决策生成于 ${genAt}` : ""} · 由 {modelView === "ds" && dsd ? "DeepSeek V4 Pro(影子)" : "Claude"} 综合全部信号生成 · 非投资建议
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
                  <span>
                    P(up,5d) {(d.p_up_5d * 100).toFixed(0)}%
                    {d.bold_call_5d && (
                      <span className={`ml-1.5 px-1.5 py-0.5 rounded-full font-bold ${
                        d.bold_call_5d === "up" ? "bg-emerald-500/20" : "bg-red-500/20"}`}>
                        押{d.bold_call_5d === "up" ? "涨 ▲" : "跌 ▼"}
                      </span>
                    )}
                  </span>
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

      {/* ══ 1.5 🚦 今天怎么做 — 四条军规(254套回测的最终提炼,数字全实时)══════ */}
      {snap.champs && (
        <section className="bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] p-5">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
              🚦 今天怎么做(四条军规)
            </span>
            <span className={`text-[11px] px-2.5 py-1 rounded-full font-bold ${
              snap.champs.risk_on ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"}`}>
              大盘{snap.champs.risk_on ? "🟢 顺风" : "🔴 逆风"}
            </span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[13px] leading-relaxed">
            <div className="bg-[#F6F6F8] rounded-xl px-3.5 py-2.5">
              <div className="text-[11px] text-gray-400 mb-0.5">① 先看大盘红绿灯</div>
              {snap.champs.risk_on
                ? <span>🟢 顺风 → <b>可以玩</b>(看下面三条)</span>
                : <span>🔴 逆风 → <b>今天什么都不买</b>,现金等灯变绿</span>}
            </div>
            <div className="bg-[#F6F6F8] rounded-xl px-3.5 py-2.5">
              <div className="text-[11px] text-gray-400 mb-0.5">② 什么价买</div>
              跌到 <b className="font-mono text-emerald-700">${snap.champs.swing.lo5.toFixed(2)}</b>(5日新低)才买,<b>永不追涨</b>
            </div>
            <div className="bg-[#F6F6F8] rounded-xl px-3.5 py-2.5">
              <div className="text-[11px] text-gray-400 mb-0.5">③ 什么价卖</div>
              弹回 <b className="font-mono text-red-600">${(snap.champs.swing.open?.hi5 ?? snap.champs.swing.hi5).toFixed(2)}</b>(5日新高)就卖,最多拿 10 天
            </div>
            <div className="bg-[#F6F6F8] rounded-xl px-3.5 py-2.5">
              <div className="text-[11px] text-gray-400 mb-0.5">④ 买多少</div>
              最多用 <b className="font-mono">{((snap.regime?.vol_target?.position_pct ?? snap.champs.vt_pct) * 100).toFixed(0)}%</b> 的投机资金,其余现金;拿 5 天以内用 QBTX,更久用 QBTS 正股
            </div>
          </div>
          <div className="mt-2 bg-amber-50 rounded-xl px-3.5 py-2.5 text-[13px] leading-relaxed text-amber-900">
            <b>⓪ 总闸(先于一切)</b>:QBTS 投机仓总额 ≤ 你全部资产的 <b>10%</b>——这只票可能单日 −40%、可能增发腰斩,
            止损保护不了隔夜跳空,<b>仓位小是唯一真防御</b>。DCA 核心仓(📥定投专区)永远另册,两边不许挪钱。
          </div>
        </section>
      )}

      {/* ══ 1.6 💼 当前持仓 — 你的真金仓位 + AI 每日逐笔操作建议 ═══════════ */}
      <PositionsCard
        initial={snap.user_positions ?? []}
        prices={{
          QBTS: liveCurrent ? liveQbts?.price : snap.price,
          QBTX: (liveCurrent ? live?.quotes?.qbtx?.price : null) ?? snap.etf_prices?.qbtx,
          QBTZ: (liveCurrent ? live?.quotes?.qbtz?.price : null) ?? snap.etf_prices?.qbtz,
        }}
        advice={d?.position_advice}
        adviceAsOf={genAt ?? undefined}
      />

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
            <div className="bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] p-5">
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
                  {/* HOLD 天也要看得到 sizing 规则 — 它管的是"整个投机仓该多大",与今日方向无关 */}
                  {snap.regime?.vol_target?.position_pct != null && (
                    <div className="mt-2 text-xs text-indigo-700 bg-indigo-50 border border-indigo-100 rounded-md px-2.5 py-1.5 leading-snug"
                         title={snap.regime.vol_target.note}>
                      📐 <b>波动率目标敞口 ≤{(snap.regime.vol_target.position_pct * 100).toFixed(0)}%</b>
                      ：以当前波动,投机仓整体别超过这个比例(一年回测:+60.6%/−56%回撤 vs 满仓买持 +41%/−71%;不预测方向,只管大小)。
                    </div>
                  )}
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
                      {/* 波动率目标仓位 — 一年回测唯一同时改善收益与回撤的 sizing 规则(不预测方向) */}
                      {snap.regime?.vol_target?.position_pct != null && (
                        <tr>
                          <td className="py-1.5 text-[#525461] text-xs" title={snap.regime.vol_target.note}>
                            📐 波动率目标敞口
                          </td>
                          <td className="py-1.5 text-right font-mono font-semibold text-indigo-600"
                              title={snap.regime.vol_target.note}>
                            ≤{(snap.regime.vol_target.position_pct * 100).toFixed(0)}% 投机仓
                          </td>
                        </tr>
                      )}
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

              {/* 🥊 另一位考生的独立判断 — 同卷对照,常驻显示(不用切换) */}
              {dsd && snap.decision && (() => {
                const other = modelView === "ds" ? snap.decision : dsd;
                const isDs = modelView !== "ds";   // 对照区显示的是不是 DeepSeek
                const tp = other.trade_plan;
                const agree = other.action === d.action;
                return (
                  <div className={`mt-3 rounded-lg border px-3 py-2.5 ${
                    isDs ? "bg-violet-50/60 border-violet-200" : "bg-blue-50/60 border-blue-200"}`}>
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <span className="text-[11px] font-bold text-gray-700">
                        {isDs ? "🤖 DeepSeek 影子判断" : "🧠 Fable 5 主决策"}(同卷对照)
                      </span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-semibold ${
                        agree ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
                        {agree ? "两模型同向 ✓" : "两模型分歧 ⚠️"}
                      </span>
                    </div>
                    <div className="mt-1.5 text-xs text-gray-700">
                      {other.action === "LONG_QBTX" ? "📈 做多 — 买 QBTX"
                       : other.action === "SHORT_QBTZ" ? "📉 做空 — 买 QBTZ" : "⏸️ 观望"}
                      <span className="text-gray-400"> · </span>信心 {other.conviction}/10
                      <span className="text-gray-400"> · </span>
                      押{other.bold_call_5d === "up" ? "涨 ▲" : "跌 ▼"}(P(up) {(other.p_up_5d * 100).toFixed(0)}%)
                    </div>
                    {other.action !== "HOLD" && other.plan_valid !== false && tp?.etf_ticker && (
                      <div className="mt-1 text-[11px] font-mono text-gray-600">
                        {tp.etf_ticker} {fmtPx(tp.etf_entry)} / <span className="text-[#F03A3E]">{fmtPx(tp.etf_stop)}</span> / <span className="text-emerald-600">{fmtPx(tp.etf_target)}</span>
                        <span className="text-gray-400"> · </span>1:{tp.rr_ratio?.toFixed(1) ?? "—"}
                        <span className="text-gray-400"> · </span>{tp.suggested_position_pct}% 仓
                      </div>
                    )}
                    {tp?.entry_condition && (
                      <div className="mt-1 text-[10px] text-gray-500 leading-snug">
                        入场条件:{tp.entry_condition.slice(0, 90)}
                      </div>
                    )}
                    {isDs && (
                      <div className="mt-1 text-[9px] text-amber-600">
                        影子判断 · 不驱动交易/推送/台账;方向表态每日记分,8/15 与主决策同框宣判
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>

            {/* 关键驱动 + 风险 */}
            <div className="bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] p-5">
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
            <section className="bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] p-5">
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

      {/* ══ 🔬 进阶分析抽屉 — 结构/宏观等技术细节,小白可整块跳过(AI 决策已替你读过) ═══ */}
      <details className="group">
        <summary className="cursor-pointer list-none bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] px-5 py-4 flex items-center justify-between gap-3 select-none">
          <span className="min-w-0">
            <span className="block text-sm font-semibold text-[#525461]">🔬 进阶分析(SMC 结构 · 宏观日历 · 技术细节)</span>
            <span className="block text-[11px] text-gray-400 mt-0.5">上面的决策已替你读过这些 · 想深挖再展开</span>
          </span>
          <span className="shrink-0 inline-flex items-center gap-1.5 rounded-full bg-[#007AFF] px-4 py-2 text-[13px] font-semibold text-white shadow-[0_1px_3px_rgba(0,122,255,0.4)] transition-opacity active:opacity-70 group-open:bg-[#E5E5EA] group-open:text-[#525461] group-open:shadow-none">
            <span className="group-open:hidden">展开深挖</span>
            <span className="hidden group-open:inline">收起</span>
            <span className="inline-block transition-transform group-open:rotate-90">›</span>
          </span>
        </summary>
        <div className="mt-4 space-y-4">

      {/* CHoCH 早期反转预警 — 结构性格转变但未被 BOS 确认,不发交易信号 */}
      {choch && (
        <div className="bg-indigo-50 border border-indigo-200 text-indigo-800 rounded-xl px-5 py-3 text-sm leading-relaxed flex items-start gap-2">
          <span className="text-base leading-none mt-0.5">🔭</span>
          <div>
            <span className="font-semibold">早期{choch.dir === "bullish" ? "见底" : "见顶"}预警</span>
            ：{choch.date} 在 ${choch.level.toFixed(2)} 出现
            <span className="font-semibold">{choch.dir === "bullish" ? "看涨" : "看跌"} CHoCH</span>
            （结构性格转变，可能{choch.dir === "bullish" ? "见底转涨" : "见顶转跌"}的苗头）。
            <span className="text-indigo-500"> 这是早期提示、<b>尚未被 BOS 确认</b>，系统不会据此发交易信号。</span>
          </div>
        </div>
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
                  {e.coef && e.coef.spy >= 1.3 && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded font-semibold bg-orange-100 text-orange-700"
                          title={`实测事件日波动放大倍数(2022-08~2026-07): 大盘×${e.coef.spy} · 量子ETF×${e.coef.qtum} · QBTS单票×${e.coef.qbts}(宏观日对QBTS单票无额外波动,系数看大盘方向背景)`}>
                      大盘×{e.coef.spy}
                    </span>
                  )}
                  {(() => {
                    // Badge 按类型诚实:演讲天生没数值结果,别挂"已公布"让人以为缺数据;
                    // 有预测的数据过期但没实际值(如免费源没有的 ISM/ADP,或覆盖内待下次补)
                    // → 标"待结果",一眼看出是数据源局限而非 bug。
                    const hu = e.hours_until;
                    const isSpeech = /speaks|speech|testif/i.test(e.title)
                      || (!e.forecast && !e.previous && !e.actual);
                    const future = typeof hu === "number" && hu >= 0 && hu <= 48;
                    const past = typeof hu === "number" && hu < 0 && hu > -24;
                    if (isSpeech) {
                      if (future) return (
                        <span className="text-[10px] px-1.5 py-0.5 rounded font-bold bg-red-500 text-white">
                          {hu! < 1 ? "即将开始" : `${Math.round(hu!)}小时后`}
                        </span>);
                      return (
                        <span className="text-[10px] px-1.5 py-0.5 rounded font-semibold bg-violet-100 text-violet-600">
                          🎤 演讲{past ? "已结束" : ""}
                        </span>);
                    }
                    if (future) return (
                      <span className="text-[10px] px-1.5 py-0.5 rounded font-bold bg-red-500 text-white">
                        {hu! < 1 ? "即将发布" : `${Math.round(hu!)}小时后`}
                      </span>);
                    if (past) return e.actual ? (
                      <span className="text-[10px] px-1.5 py-0.5 rounded font-semibold bg-gray-200 text-gray-600">已公布</span>
                    ) : (
                      <span className="text-[10px] px-1.5 py-0.5 rounded font-semibold bg-amber-100 text-amber-700"
                            title="发布时间已过,但实际值不在免费数据源里(如 ISM/ADP),或覆盖内数据将在下次更新时补上">
                        已公布·待结果
                      </span>);
                    return null;
                  })()}
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
        {smc && (
          <div className="bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider flex items-center gap-2">
                🧠 SMC 聪明钱结构
                {/* 现价(与 SMC 数据同源:实时新鲜则用 live,否则回退快照)—— 省得上下拉页面 */}
                <span className="normal-case font-mono font-bold text-gray-900 text-sm">
                  ${(liveCurrent && liveQbts ? liveQbts.price : snap.price).toFixed(2)}
                  {pbLive && <span className="ml-1 inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse align-middle" />}
                </span>
              </span>
              <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold ${
                smc.signal > 0 ? "bg-emerald-100 text-emerald-700"
                : smc.signal < 0 ? "bg-red-100 text-red-700"
                : "bg-gray-100 text-gray-500"}`}>
                {smc.signal > 0 ? "偏多" : smc.signal < 0 ? "偏空" : "中性"}
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
                {pb.risk_note && (
                  <div className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-2.5 py-1.5 mb-2 leading-snug">
                    {pb.risk_note}
                  </div>
                )}
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
                        <span className="font-medium">
                          🎯 共振入场
                          <span className={`mx-1 px-1 py-0.5 rounded text-[10px] font-bold ${
                            pb.lock === "bear" ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-700"}`}>
                            {pb.lock === "bear" ? "做空↓" : "做多↑"}
                          </span>
                          [{pb.entry_zone.basis}]
                        </span>
                        <span className="font-mono">${pb.entry_zone.low.toFixed(2)} – ${pb.entry_zone.high.toFixed(2)}</span>
                      </div>
                    )}
                    {/* 💱 实际下单标的换算:QBTS 反弹到入场区时,对应 ETF 大约在这些价位 */}
                    {pbEtf && (pbEtf.entryLo != null || pbEtf.tp1 != null) && (
                      <div className="col-span-2 px-2 py-1.5 rounded-md bg-indigo-50 text-indigo-800 leading-snug">
                        <span className="font-semibold">💱 实际下单 · {pbEtf.ticker}</span>
                        <span className="font-mono">
                          {pbEtf.entryLo != null && <>：买入 ≈${pbEtf.entryLo.toFixed(2)}{pbEtf.entryHi != null ? `–$${pbEtf.entryHi.toFixed(2)}` : ""}</>}
                          {pbEtf.stop != null && <> · 止损 ≈${pbEtf.stop.toFixed(2)}</>}
                          {pbEtf.tp1 != null && <> · 止盈 ≈${pbEtf.tp1.toFixed(2)}</>}
                          {pbEtf.tp2 != null && <>/${pbEtf.tp2.toFixed(2)}</>}
                        </span>
                        <div className="text-[10px] opacity-70 mt-0.5">
                          由左侧 QBTS 价位按 2× 实时换算(近似);ETF 每日再平衡,隔夜/多日会漂移,以当日盘中为准
                        </div>
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
                smc.trend === "bullish" ? "bg-emerald-50 text-emerald-700"
                : smc.trend === "bearish" ? "bg-red-50 text-red-700"
                : "bg-gray-50 text-gray-600"}`}>
                结构 {smc.trend === "bullish" ? "看多" : smc.trend === "bearish" ? "看空" : "中性"}
              </span>
              {smc.last_event && (
                <span className="px-2 py-1 rounded-md bg-violet-50 text-violet-700 font-medium">
                  {smc.last_event.date} {smc.last_event.dir === "bullish" ? "↗" : "↘"} {smc.last_event.kind} @ ${smc.last_event.level.toFixed(2)}
                </span>
              )}
              <span className="px-2 py-1 rounded-md bg-blue-50 text-blue-700 font-medium">
                {smc.zone} {typeof smc.range_position === "number" ? `${(smc.range_position * 100).toFixed(0)}%` : "—"}
              </span>
              {/* 多周期共振 (1h vs 日线) */}
              {smc.ltf && smc.confluence && (
                <span className={`px-2 py-1 rounded-md font-medium ${
                  smc.confluence === "aligned" ? "bg-emerald-50 text-emerald-700"
                  : smc.confluence === "conflict" ? "bg-amber-50 text-amber-700"
                  : "bg-gray-50 text-gray-500"}`}>
                  1h {smc.ltf.trend === "bullish" ? "↗" : smc.ltf.trend === "bearish" ? "↘" : "→"}
                  {smc.confluence === "aligned" ? " 同向" : smc.confluence === "conflict" ? " 背离" : " 中性"}
                </span>
              )}
            </div>
            {/* 相对强度 — 一行(prompt 已用，此处只给用户一个语境标注) */}
            {snap.relative_strength?.rationale && (
              <div className="text-[11px] text-[#525461] bg-[#F6F6F8] rounded-md px-2.5 py-1.5 mb-2 leading-snug">
                📊 {snap.relative_strength.rationale}
              </div>
            )}
            {/* 散户情绪 — 弱信号小条(Adanos Reddit)。同步性>预测性,仅背景参考 */}
            {snap.sentiment?.sentiment_score != null && (
              <div className={`text-[11px] rounded-md px-2.5 py-1.5 mb-2 leading-snug ${
                snap.sentiment.signal > 0 ? "bg-emerald-50 text-emerald-700"
                : snap.sentiment.signal < 0 ? "bg-red-50 text-red-700"
                : "bg-[#F6F6F8] text-[#525461]"}`}>
                💬 {snap.sentiment.note}
                <span className="text-gray-400"> · 弱信号,散户情绪多为同步反映、非方向依据</span>
              </div>
            )}
            {/* 关键区域 */}
            <div className="space-y-1.5 text-xs">
              {smc.supply_zones.map((z, i) => (
                <div key={`s${i}`} className="flex items-center justify-between px-2.5 py-1.5 rounded-md bg-red-50/60 border border-red-100">
                  <span className="text-red-700 font-medium">▼ 供给区 [{z.kind}]</span>
                  <span className="font-mono text-gray-700">${z.low.toFixed(2)} – ${z.high.toFixed(2)}</span>
                </div>
              ))}
              {smc.demand_zones.map((z, i) => (
                <div key={`d${i}`} className="flex items-center justify-between px-2.5 py-1.5 rounded-md bg-emerald-50/60 border border-emerald-100">
                  <span className="text-emerald-700 font-medium">▲ 需求区 [{z.kind}]</span>
                  <span className="font-mono text-gray-700">${z.low.toFixed(2)} – ${z.high.toFixed(2)}</span>
                </div>
              ))}
              {smc.sweeps.slice(-2).map((s, i) => (
                <div key={`w${i}`} className="text-[11px] text-[#525461] px-2.5 py-1">
                  💧 {s.note}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 历史战绩 */}
        <div className="bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] p-5">
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
          <div className="bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] p-5">
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
              <span className="text-red-600 font-mono">VAL {fmtPx(snap.volume_profile.val)}</span>
              <span className="font-mono font-bold text-violet-700">POC {fmtPx(snap.volume_profile.poc)}</span>
              <span className="text-emerald-600 font-mono">VAH {fmtPx(snap.volume_profile.vah)}</span>
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

        {/* Intrabar Profile — 单根日线 bar 内部:吸收/投降/派发(辅助地图) */}
        {snap.intrabar_profile?.available && (
          <div className="bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] p-5">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
                🔬 K线内画像 · Intrabar
              </span>
              <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold ${
                snap.intrabar_profile.stance === "偏多" ? "bg-emerald-100 text-emerald-700"
                : snap.intrabar_profile.stance === "偏空" ? "bg-red-100 text-red-700"
                : "bg-gray-100 text-gray-500"}`}>
                {snap.intrabar_profile.read}
              </span>
            </div>
            <div className="text-[11px] text-gray-400 mb-3">
              {snap.intrabar_profile.bar_date} 单日 · {snap.intrabar_profile.n_subbars}根1h 重构 · 辅助非信号
            </div>
            {/* 买卖 delta 条 */}
            <div className="mb-2">
              <div className="flex h-5 rounded-md overflow-hidden text-[10px] font-bold text-white">
                <div className="bg-emerald-500 flex items-center justify-center"
                     style={{ width: `${Math.max((snap.intrabar_profile.up_vol_pct ?? 0) * 100, 6)}%` }}>
                  买{Math.round((snap.intrabar_profile.up_vol_pct ?? 0) * 100)}%
                </div>
                <div className="bg-red-500 flex items-center justify-center"
                     style={{ width: `${Math.max((snap.intrabar_profile.down_vol_pct ?? 0) * 100, 6)}%` }}>
                  卖{Math.round((snap.intrabar_profile.down_vol_pct ?? 0) * 100)}%
                </div>
              </div>
              <div className="flex justify-between text-[11px] text-[#525461] mt-1 px-0.5">
                <span>净delta <span className={`font-mono font-semibold ${
                  (snap.intrabar_profile.net_delta_pct ?? 0) > 0 ? "text-emerald-600" : "text-red-600"}`}>
                  {(snap.intrabar_profile.net_delta_pct ?? 0) > 0 ? "+" : ""}{Math.round((snap.intrabar_profile.net_delta_pct ?? 0) * 100)}%</span></span>
                <span>VPOC <span className="font-mono">${snap.intrabar_profile.intrabar_poc?.toFixed(2)}</span>
                  <span className="text-gray-400">（{Math.round((snap.intrabar_profile.poc_position ?? 0) * 100)}%位）</span></span>
              </div>
            </div>
            {/* 读数 */}
            <div className="flex items-start gap-2 text-xs bg-indigo-50/70 border border-indigo-100 rounded-lg px-3 py-2 mb-2 leading-snug">
              <span className={`shrink-0 px-1.5 py-0.5 rounded font-bold ${
                snap.intrabar_profile.stance === "偏多" ? "bg-emerald-100 text-emerald-700"
                : snap.intrabar_profile.stance === "偏空" ? "bg-red-100 text-red-700"
                : "bg-gray-100 text-gray-500"}`}>
                {snap.intrabar_profile.read}
              </span>
              <span className="text-gray-700">{snap.intrabar_profile.read_note}</span>
            </div>
            {snap.intrabar_profile.delta_disagree && (
              <div className="text-[11px] text-amber-700 bg-amber-50 border border-amber-100 rounded-md px-2.5 py-1 mb-2 leading-snug">
                ⚠️ 净 delta 方向与读数背离,降级参考
              </div>
            )}
            {/* 近N日 delta 趋势条 */}
            {(snap.intrabar_profile.delta_strip?.length ?? 0) > 0 && (
              <div className="flex items-center gap-2 text-[11px] text-[#525461]">
                <span className="shrink-0">近{snap.intrabar_profile.delta_strip!.length}日抛压/承接</span>
                <div className="flex gap-1">
                  {snap.intrabar_profile.delta_strip!.map((s) => (
                    <div key={s.date}
                         title={`${s.date}: 净delta ${s.delta_pct > 0 ? "+" : ""}${Math.round(s.delta_pct * 100)}%`}
                         className={`w-4 h-4 rounded-sm ${s.sign > 0 ? "bg-emerald-400" : "bg-red-400"}`} />
                  ))}
                </div>
                <span className="text-gray-400">🟢买 / 🔴卖</span>
              </div>
            )}
          </div>
        )}

        {/* 空头动向(原挤空燃料,2026-07-04 依第五轮实证翻转:空头=聪明钱) */}
        {snap.squeeze?.short_z != null && (
          <div className="bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
                🩳 空头动向
              </span>
              <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold ${
                snap.squeeze.stance === "crowded" ? "bg-red-100 text-red-700"
                : snap.squeeze.stance === "retreat" ? "bg-emerald-100 text-emerald-700"
                : "bg-gray-100 text-gray-500"}`}>
                {snap.squeeze.stance_cn}
              </span>
            </div>
            <div className="flex items-baseline gap-3 mb-2">
              <span className="text-lg font-bold font-mono text-gray-800">
                {snap.squeeze.short_ratio != null ? `${(snap.squeeze.short_ratio * 100).toFixed(0)}%` : "—"}
              </span>
              <span className="text-[10px] text-gray-400">空量比</span>
              <span className={`text-sm font-mono font-semibold ${
                snap.squeeze.short_z > 1 ? "text-red-600"
                : snap.squeeze.short_z < -1 ? "text-emerald-600" : "text-gray-500"}`}>
                60日 z {snap.squeeze.short_z >= 0 ? "+" : ""}{snap.squeeze.short_z.toFixed(1)}
              </span>
            </div>
            <div className="text-[11px] text-[#525461] leading-snug">{snap.squeeze.rationale}</div>
            {snap.squeeze.context && (
              <div className="mt-1.5 text-[10px] text-gray-400">{snap.squeeze.context}</div>
            )}
            <div className="mt-1.5 text-[10px] text-gray-400">
              实证:空量比飙升后 5 日均值 +2.7% vs 平时 +5.2%(空头=聪明钱,第五轮 mining.md)· 证据弱,只当风向
            </div>
          </div>
        )}
      </section>

        </div>
      </details>

      {/* ══ 4.8 恐慌深坑报警器 — 跌20%于20日高抄底(纸面测量,策略动物园胜率冠军但未验证) ═══ */}
      {snap.dip_buy && (
        <section className={`rounded-2xl border p-4 text-sm leading-relaxed ${
          snap.dip_buy.open ? "bg-emerald-50 border-emerald-200"
          : snap.dip_buy.triggered ? "bg-amber-50 border-amber-300"
          : "bg-white border-[#EDEDF0]"}`}>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">🕳️ 恐慌深坑报警器</span>
            {snap.dip_buy.open ? (
              <span className="text-emerald-700">
                虚拟持仓中:{snap.dip_buy.open.entry_date} 入 ${snap.dip_buy.open.entry.toFixed(2)} →
                现 {snap.dip_buy.open.unreal_pct >= 0 ? "+" : ""}{(snap.dip_buy.open.unreal_pct * 100).toFixed(1)}%
                · 目标 ${snap.dip_buy.open.target.toFixed(2)} · 第 {snap.dip_buy.open.days}/15 天
              </span>
            ) : snap.dip_buy.triggered ? (
              <span className="text-amber-700 font-semibold">⚡ 已触发!现价 ${snap.dip_buy.close.toFixed(2)} ≤ 触发线 ${snap.dip_buy.trigger_px.toFixed(2)}(恐慌深坑,明日开仓虚拟单)</span>
            ) : (
              <span className="text-gray-600">
                未触发 · 现价 ${snap.dip_buy.close.toFixed(2)},触发线 <b className="font-mono">${snap.dip_buy.trigger_px.toFixed(2)}</b>
                (还差 {(Math.abs(snap.dip_buy.distance_pct) * 100).toFixed(0)}%)
              </span>
            )}
            <span className="ml-auto text-[11px] text-gray-400">
              战绩 {snap.dip_buy.n_win}/{snap.dip_buy.n_closed}
              {snap.dip_buy.win_rate != null && ` (${(snap.dip_buy.win_rate * 100).toFixed(0)}%)`}
              {" · 落袋 "}{snap.dip_buy.realized >= 0 ? "+" : ""}${snap.dip_buy.realized.toFixed(0)}
            </span>
          </div>
          <div className="mt-1 text-[10px] text-gray-400">
            规则:收盘跌破 20日高×0.80 虚拟买 $1000,回 95% 止盈 / 15 天到期 · 回测 64%@25 但近一年平庸+多重比较嫌疑 —— 纯纸面测量,不进决策,30 笔后见真章
          </div>
        </section>
      )}

      {/* ══ 4.85 冠军策略陪跑 — 35套动物园前两名的实时纸面成绩(测量,不进决策) ═══ */}
      {snap.champs && (
        <section className="bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] p-4">
          <div className="flex items-center justify-between mb-2.5">
            <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
              🐎 策略马厩 — 7 套策略的实盘模拟(每套虚拟 $1000)
            </span>
            <span className="text-[10px] text-gray-400">谁真赚钱,数字说话</span>
          </div>
          <div className="space-y-2 text-sm leading-relaxed">
            {/* ① QQQ50 × 波动率目标:虚拟净值 vs 死拿 */}
            {snap.champs.volreg && (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 bg-[#FAFAFB] rounded-lg px-3 py-2">
                <span className="text-xs font-semibold text-gray-700">🥇 QQQ50×波动率目标</span>
                <span className={snap.champs.volreg.ret_pct >= 0 ? "text-emerald-700" : "text-[#F03A3E]"}>
                  ${snap.champs.volreg.nav.toFixed(0)}({snap.champs.volreg.ret_pct >= 0 ? "+" : ""}{(snap.champs.volreg.ret_pct * 100).toFixed(1)}%)
                </span>
                <span className="text-gray-400 text-xs">
                  vs 死拿 ${snap.champs.volreg.bh_nav.toFixed(0)}({snap.champs.volreg.bh_ret_pct >= 0 ? "+" : ""}{(snap.champs.volreg.bh_ret_pct * 100).toFixed(1)}%)
                  · 当前敞口 {(snap.champs.volreg.exposure * 100).toFixed(0)}% · {snap.champs.volreg.start_date} 起 $1000
                </span>
              </div>
            )}
            {/* ② 5日swing × QQQ50 */}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 bg-[#FAFAFB] rounded-lg px-3 py-2">
              <span className="text-xs font-semibold text-gray-700">🥈 5日swing×QQQ50</span>
              {snap.champs.swing.open ? (
                <span className="text-emerald-700">
                  持仓中:{snap.champs.swing.open.entry_date} 入 ${snap.champs.swing.open.entry.toFixed(2)} →
                  现 {snap.champs.swing.open.unreal_pct >= 0 ? "+" : ""}{(snap.champs.swing.open.unreal_pct * 100).toFixed(1)}%
                  · 目标破 ${snap.champs.swing.open.hi5.toFixed(2)} · 第 {snap.champs.swing.open.days}/10 天
                </span>
              ) : snap.champs.swing.would_trigger && snap.champs.risk_on ? (
                <span className="text-amber-700 font-semibold">⚡ 触发中!收盘 ${snap.champs.swing.close.toFixed(2)} = 5日新低(明日开虚拟仓)</span>
              ) : (
                <span className="text-gray-600">
                  等待 · 现 ${snap.champs.swing.close.toFixed(2)},触发线 <b className="font-mono">${snap.champs.swing.lo5.toFixed(2)}</b>(5日新低)
                </span>
              )}
              <span className="ml-auto text-[11px] text-gray-400">
                战绩 {snap.champs.swing.n_win}/{snap.champs.swing.n_closed}
                {snap.champs.swing.win_rate != null && ` (${(snap.champs.swing.win_rate * 100).toFixed(0)}%)`}
                · 落袋 {snap.champs.swing.realized >= 0 ? "+" : ""}${snap.champs.swing.realized.toFixed(0)}
              </span>
            </div>
            {/* ③ BTC昨日绿 × QQQ50 × 波目(第四轮新增) */}
            {snap.champs.btc && (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 bg-[#FAFAFB] rounded-lg px-3 py-2">
                <span className="text-xs font-semibold text-gray-700">🆕 BTC昨日绿×QQQ50</span>
                <span className={snap.champs.btc.ret_pct >= 0 ? "text-emerald-700" : "text-[#F03A3E]"}>
                  ${snap.champs.btc.nav.toFixed(0)}({snap.champs.btc.ret_pct >= 0 ? "+" : ""}{(snap.champs.btc.ret_pct * 100).toFixed(1)}%)
                </span>
                <span className="text-gray-400 text-xs">
                  BTC 昨日{snap.champs.btc.btc_green == null ? "?" : snap.champs.btc.btc_green ? "🟢 涨 → 持仓" : "🔴 跌 → 空仓"}
                  · 当前敞口 {(snap.champs.btc.exposure * 100).toFixed(0)}% · {snap.champs.btc.start_date} 起 $1000
                </span>
              </div>
            )}
            {/* ④ CLV强收盘 × QQQ50 × 波目(第六轮新增) */}
            {snap.champs.clv && (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 bg-[#FAFAFB] rounded-lg px-3 py-2">
                <span className="text-xs font-semibold text-gray-700">🆕 CLV强收盘×QQQ50</span>
                <span className={snap.champs.clv.ret_pct >= 0 ? "text-emerald-700" : "text-[#F03A3E]"}>
                  ${snap.champs.clv.nav.toFixed(0)}({snap.champs.clv.ret_pct >= 0 ? "+" : ""}{(snap.champs.clv.ret_pct * 100).toFixed(1)}%)
                </span>
                <span className="text-gray-400 text-xs">
                  今日收盘位置 {snap.champs.clv.clv != null
                    ? `${snap.champs.clv.clv >= 0 ? "+" : ""}${snap.champs.clv.clv.toFixed(2)}${snap.champs.clv.clv > 0.3 ? " 💪 强 → 明日持仓" : " 弱 → 空仓"}`
                    : "?"}
                  · 敞口 {(snap.champs.clv.exposure * 100).toFixed(0)}% · {snap.champs.clv.start_date} 起 $1000
                </span>
              </div>
            )}
            {/* ⑤ 配对超涨 veto(第八轮新增) */}
            {snap.champs.veto && (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 bg-[#FAFAFB] rounded-lg px-3 py-2">
                <span className="text-xs font-semibold text-gray-700">🆕 配对超涨veto</span>
                <span className={snap.champs.veto.ret_pct >= 0 ? "text-emerald-700" : "text-[#F03A3E]"}>
                  ${snap.champs.veto.nav.toFixed(0)}({snap.champs.veto.ret_pct >= 0 ? "+" : ""}{(snap.champs.veto.ret_pct * 100).toFixed(1)}%)
                </span>
                <span className="text-gray-400 text-xs">
                  vs IONQ 价差 z {snap.champs.veto.z40 != null ? `${snap.champs.veto.z40 >= 0 ? "+" : ""}${snap.champs.veto.z40.toFixed(1)}` : "?"}
                  {snap.champs.veto.vetoed ? " 🚫 贵1σ+ → 清仓等" : " ✓ 不贵 → 照常持有"}
                  · 敞口 {(snap.champs.veto.exposure * 100).toFixed(0)}% · {snap.champs.veto.start_date} 起 $1000
                </span>
              </div>
            )}
            {/* ⑥ QTUM昨日绿(第八轮新增) */}
            {snap.champs.qtum && (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 bg-[#FAFAFB] rounded-lg px-3 py-2">
                <span className="text-xs font-semibold text-gray-700">🆕 QTUM板块绿×QQQ50</span>
                <span className={snap.champs.qtum.ret_pct >= 0 ? "text-emerald-700" : "text-[#F03A3E]"}>
                  ${snap.champs.qtum.nav.toFixed(0)}({snap.champs.qtum.ret_pct >= 0 ? "+" : ""}{(snap.champs.qtum.ret_pct * 100).toFixed(1)}%)
                </span>
                <span className="text-gray-400 text-xs">
                  量子ETF昨日{snap.champs.qtum.qtum_green == null ? "?" : snap.champs.qtum.qtum_green ? "🟢 涨 → 持仓" : "🔴 跌 → 空仓"}
                  · 敞口 {(snap.champs.qtum.exposure * 100).toFixed(0)}% · {snap.champs.qtum.start_date} 起 $1000
                </span>
              </div>
            )}
            {/* ⑦ 特调双腿(用户自创,第十轮新增) */}
            {snap.champs.tj && (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 bg-[#FAFAFB] rounded-lg px-3 py-2">
                <span className="text-xs font-semibold text-gray-700">🎯 特调双腿(你的作品)</span>
                {snap.champs.tj.open ? (
                  <span className="text-emerald-700">
                    持仓中:{snap.champs.tj.open.entry_date} 抄底 ${snap.champs.tj.open.entry.toFixed(2)} →
                    现 {(snap.champs.tj.unreal ?? 0) >= 0 ? "+" : ""}{(((snap.champs.tj.unreal ?? 0) / 1000) * 100).toFixed(1)}%
                    · 等止盈/破位信号离场
                  </span>
                ) : snap.champs.tj.sig?.buy_base ? (
                  <span className="text-amber-700 font-semibold">⚡ 抄底建仓触发!(明日开虚拟仓)</span>
                ) : (
                  <span className="text-gray-600">
                    等待 · 快%R {snap.champs.tj.sig?.fast ?? "?"} / 慢%R {snap.champs.tj.sig?.slow ?? "?"}(快线上穿-80 且慢线弱才买)
                  </span>
                )}
                <span className="ml-auto text-[11px] text-gray-400">
                  战绩 {snap.champs.tj.n_win}/{snap.champs.tj.n_closed}
                  · 落袋 {snap.champs.tj.realized >= 0 ? "+" : ""}${snap.champs.tj.realized.toFixed(0)}
                </span>
              </div>
            )}
          </div>
          <div className="mt-2 text-[10px] text-gray-400">
            回测出身(近1年/最大回撤):🥇+113%/-40% · 🥈胜率72% · BTC +120%/-20% · CLV +189%/-18% · veto +176%/-22% · QTUM +228%/-19% · 🎯抄底腿5天+17.4%(254套十轮)—— 纯纸面陪跑,不进决策;跑赢真实记录才算数
          </div>
        </section>
      )}

      {/* ══ 4.9 AI 系统自检 — 决策模型以审计者身份报告的数据问题/改进建议(给维护者) ═══ */}
      {(d?.system_notes?.length ?? 0) > 0 && (
        <section className="bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] p-5">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
              🔬 AI 系统自检 · 今日发现
            </span>
            {d?.model && <span className="text-[10px] text-gray-400 font-mono">{d.model}</span>}
          </div>
          <div className="space-y-2">
            {d!.system_notes!.map((n, i) => (
              <div key={i} className="flex items-start gap-2 text-sm leading-relaxed">
                <span className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded font-semibold mt-0.5 ${
                  n.kind === "数据问题" ? "bg-amber-100 text-amber-700" : "bg-sky-100 text-sky-700"}`}>
                  {n.kind}
                </span>
                <span className="text-gray-700">{n.note}</span>
              </div>
            ))}
          </div>
          <div className="mt-2.5 text-[10px] text-gray-400">
            决策模型顺带审计当日数据后主动提出,不影响交易决定 · 修不修由你定
          </div>
        </section>
      )}

      {/* ══ 🔬 全站系统体检(publish §4.8 · 六页规则层+Haiku)═══════════════ */}
      <SiteCheckOverview check={snap?.site_check ?? null} />

      {/* ══ 4.95 🌍 地缘政治雷达 — 伊朗战局/川普政策/量子政策(07-07 暴跌的驱动)═══ */}
      {geo && (
        <section className={`rounded-3xl p-5 shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] border ${
          geo.risk_level === "alert" ? "bg-red-50/70 border-red-200"
            : geo.risk_level === "watch" ? "bg-amber-50/50 border-amber-200"
            : "bg-white border-transparent"}`}>
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
              🌍 地缘政治雷达 · 伊朗战局 / 川普政策 / 量子政策
            </span>
            <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold ${
              geo.risk_level === "alert" ? "bg-red-600 text-white"
                : geo.risk_level === "watch" ? "bg-amber-400 text-amber-950"
                : "bg-emerald-100 text-emerald-700"}`}>
              {geo.risk_cn}
            </span>
            {geoLive && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-100 text-sky-700 font-semibold animate-pulse">
                盘中实时
              </span>
            )}
            <span className="ml-auto text-[10px] text-gray-400 font-mono">
              {fmtLocalDateTime(geo.as_of) ?? ""}
            </span>
          </div>

          <div className="text-[15px] font-bold text-gray-900 mb-1.5">{geo.headline_cn}</div>
          {geo.summary_cn && (
            <p className="text-sm leading-relaxed text-gray-700 mb-3">{geo.summary_cn}</p>
          )}

          {geoItems.length > 0 && (
            <div className="space-y-2 border-t border-black/5 pt-3">
              {geoItems.map(g => (
                <a key={g.key} href={g.url || "#"} target="_blank" rel="noopener noreferrer"
                   className="block group">
                  <div className="flex items-start gap-2">
                    <span className={`shrink-0 mt-1 w-1.5 h-1.5 rounded-full ${
                      g.stance === "risk_off" ? "bg-[#F03A3E]"
                        : g.stance === "risk_on" ? "bg-emerald-500" : "bg-gray-300"}`} />
                    <div className="min-w-0">
                      <div className="text-sm text-gray-900 group-hover:text-[#006FFF] transition-colors leading-snug">
                        <span className={`mr-1.5 text-[10px] px-1.5 py-0.5 rounded font-semibold align-[1px] ${
                          g.track === "iran" ? "bg-red-100 text-red-700"
                            : g.track === "trump" ? "bg-indigo-100 text-indigo-700"
                            : "bg-violet-100 text-violet-700"}`}>
                          {g.track_cn}
                        </span>
                        {g.title}
                        {g.relevance === "high" && (
                          <span className="ml-1.5 text-[10px] px-1 py-0.5 rounded bg-red-600 text-white font-bold">高影响</span>
                        )}
                      </div>
                      <div className="text-[11px] text-[#525461] mt-0.5">
                        {g.note_cn} <span className="text-gray-400">· {g.source} · {g.published?.slice(5, 16)} UTC</span>
                      </div>
                    </div>
                  </div>
                </a>
              ))}
            </div>
          )}

          <div className="mt-3 text-[10px] text-gray-400">
            Google News 每~30分钟盘中自动扫描(伊朗谈判/停火/空袭 · 川普关税/行政令 · 量子国防/出口管制)
            · 出现新高影响条目或风险级别翻转 → ntfy 手机推送 · AI 分级仅供参考
          </div>
        </section>
      )}

      {/* ══ 5. 今日要闻 + 60日小图 ═══════════════════════════════════════ */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] p-5">
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
          supply={smc?.supply_zones}
          demand={smc?.demand_zones}
          poc={snap.volume_profile?.poc ?? null}
          markers={chartMarkers}
          nwBands={snap.nw_envelope?.bands}
        />
      </section>

      <footer className="text-center text-[10px] text-gray-400 pb-4">
        QBTS Quant Lab · AI 决策由 Claude 基于 8 类数据源综合生成 · 每日 publish.py 更新 · 仅供研究参考，非投资建议
      </footer>

      {/* 右下角版本号 — 连点 3 次(1.5s 内)打开隐藏的点击审计查看窗 */}
      <div
        className="fixed bottom-2 right-3 z-10 text-[10px] font-mono text-gray-300 select-none cursor-default"
        onClick={() => {
          const now = Date.now();
          versionClicks.current = [...versionClicks.current.filter(t => now - t < 1500), now];
          if (versionClicks.current.length >= 3) {
            versionClicks.current = [];
            setAuditOpen(true);
          }
        }}
      >
        v{APP_VERSION}
      </div>
      {auditOpen && <AuditModal onClose={() => setAuditOpen(false)} />}
    </main>
  );
}
