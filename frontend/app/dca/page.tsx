"use client";

import { useEffect, useState } from "react";
import { getDcaState, type DcaState, type DcaResult } from "../_lib/data";
import { DcaCalculator } from "../_components/dca-calculator";

/* ─────────────────────────────────────────────────────────────────────────
   📥 定投专区 — 闲钱定投的「全球估值菜单」。不是择时:决定结果的是 多投>早投>
   低费>不割肉>分散,买点接近噪声。这里只帮你 ① 选对篮子(全球分散+按估值温和倾斜)
   ② 提示「什么时候多投一点」(用真实历史:深跌才动预备金、小回调在200线上方最优、
   中段下跌别抄底、近高点照投别怕)。
   ───────────────────────────────────────────────────────────────────────── */

const VAL: Record<string, { border: string; bg: string; chip: string }> = {
  "便宜": { border: "border-emerald-300", bg: "bg-emerald-50/40", chip: "bg-emerald-100 text-emerald-700" },
  "中性": { border: "border-amber-200",   bg: "bg-amber-50/30",   chip: "bg-amber-100 text-amber-700" },
  "偏贵": { border: "border-red-200",      bg: "bg-red-50/30",     chip: "bg-red-100 text-red-600" },
};
const FALLBACK = { border: "border-[#E5E5EA]", bg: "bg-white", chip: "bg-gray-100 text-gray-500" };

const signed = (n: number | null | undefined, d = 1) =>
  typeof n === "number" && isFinite(n) ? `${n >= 0 ? "+" : ""}${(n * 100).toFixed(d)}%` : "—";
const mo = (m: number | null | undefined) => (typeof m === "number" ? `${m}月` : "—");

function DcaCard({ r }: { r: DcaResult }) {
  const v = VAL[r.valuation] ?? FALLBACK;
  if (r.error) {
    return (
      <div className="rounded-2xl border border-[#E5E5EA] bg-white p-4 flex items-center gap-3">
        <span className="text-lg">⚠️</span>
        <span className="font-bold text-gray-800">{r.ticker}</span>
        <span className="text-xs text-gray-400">{r.name} · 数据拉取失败</span>
      </div>
    );
  }
  const up = (r.today_change ?? 0) >= 0;
  return (
    <div className={`rounded-2xl border ${v.border} ${v.bg} p-4 shadow-sm`}>
      {/* 头行 */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-lg font-bold text-gray-900">{r.ticker}</span>
        <span className="text-[11px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 font-medium">{r.name}</span>
        {r.role && <span className="text-[10px] text-gray-400">{r.role}</span>}
        <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold ${v.chip}`}>{r.valuation_emoji} {r.valuation}</span>
        <span className="ml-auto text-sm font-mono text-gray-900">${r.price?.toFixed(2)}</span>
        <span className={`text-sm font-semibold ${up ? "text-emerald-600" : "text-[#F03A3E]"}`}>{signed(r.today_change)}</span>
      </div>

      {/* 历史平均年回报(复合年化 CAGR,含分红)——用户最关心的数字,做醒目条 */}
      {r.cagr != null && (
        <div className="mt-2.5 flex items-baseline gap-2 rounded-lg bg-emerald-50/70 border border-emerald-100 px-3 py-2">
          <span className="text-[11px] text-emerald-700/80">历史年化回报</span>
          <span className="text-lg font-bold font-mono text-emerald-600">{signed(r.cagr)}</span>
          {r.cagr_years != null && <span className="text-[10px] text-emerald-700/50">近 {r.cagr_years} 年 · 含分红 · 复合非算术</span>}
        </div>
      )}

      {/* 估值 + 目标权重 */}
      <div className="mt-2.5 grid grid-cols-3 gap-2 text-xs">
        <div className="bg-white/70 rounded-lg px-2.5 py-1.5">
          <div className="text-[10px] text-gray-400">P/E</div>
          <div className="font-mono font-semibold text-gray-700">{r.pe ?? "—"}</div>
        </div>
        <div className="bg-white/70 rounded-lg px-2.5 py-1.5" title="盈利收益率 1/PE ≈ 粗略的长期预期年化(实际)">
          <div className="text-[10px] text-gray-400">粗估长期年化</div>
          <div className="font-mono font-semibold text-gray-700">{r.earnings_yield != null ? `~${(r.earnings_yield * 100).toFixed(1)}%` : "—"}</div>
        </div>
        <div className="bg-white/70 rounded-lg px-2.5 py-1.5">
          <div className="text-[10px] text-gray-400">建议权重</div>
          <div className="font-mono font-semibold text-[#006FFF]">{r.target_weight != null ? `${r.target_weight}%` : "—"}</div>
        </div>
      </div>

      {/* 证据版「何时多投」 */}
      {r.deploy && (
        <div className="mt-2.5 rounded-lg px-2.5 py-2 bg-white/70 border border-black/5">
          <div className="text-[12px] font-semibold text-gray-800">{r.deploy.emoji} {r.deploy.tag}</div>
          <p className="mt-0.5 text-[12px] leading-relaxed text-gray-600">{r.deploy.text}</p>
          <div className="mt-1 text-[10px] text-gray-400 font-mono">
            距52周高点 {signed(r.drawdown_pct)} · vs 200日线 {signed(r.vs_200dma_pct)}{r.below_200 ? "(下方)" : ""}
          </div>
        </div>
      )}

      {/* 季节性(次要参考)*/}
      <div className="mt-2 text-[10px] text-gray-400 leading-relaxed">
        历史最强 {mo(r.best_month)}({signed(r.best_month_avg)}) · 最弱 {mo(r.worst_month)}({signed(r.worst_month_avg)})
        · ❄️冬 {signed(r.winter_avg)} vs ☀️夏 {signed(r.summer_avg)}/月
      </div>
    </div>
  );
}

export default function DcaPage() {
  const [state, setState] = useState<DcaState | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let stop = false;
    (async () => { const s = await getDcaState(); if (!stop) { setState(s); setLoading(false); } })();
    return () => { stop = true; };
  }, []);

  const genAt = state?.generated_at?.slice(0, 10);
  const weights = state?.allocation?.weights ?? {};

  return (
    <main className="max-w-[1100px] mx-auto px-4 sm:px-6 py-5 sm:py-6 space-y-4">
      {/* 标题 + 大盘估值背景 */}
      <section className="bg-white rounded-2xl border border-[#EDEDF0] p-5 shadow-sm">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-base">📥</span>
          <span className="text-sm font-semibold text-gray-800">定投专区 · 全球估值菜单</span>
          {genAt && <span className="ml-auto text-[10px] text-gray-400 font-mono">更新于 {genAt}</span>}
        </div>
        {state?.macro && (
          <div className="mt-3 rounded-xl px-4 py-2.5 text-[13px] leading-relaxed bg-blue-50 text-blue-800 border border-blue-200">
            🌍 美股 CAPE ≈ <b>{state.macro.us_cape}</b> · 全球 ≈ <b>{state.macro.global_cape}</b>
            <span className="text-[11px] text-blue-700/70"> （{state.macro.as_of}）</span>
            <p className="mt-1 text-[12px] text-blue-700/90">{state.macro.note}</p>
          </div>
        )}
        {state?.principle && <p className="mt-2 text-[11px] text-gray-500 leading-relaxed">{state.principle}</p>}
      </section>

      {/* 建议配置 */}
      {state?.allocation && Object.keys(weights).length > 0 && (
        <section className="bg-white rounded-2xl border border-[#EDEDF0] p-4 shadow-sm">
          <div className="text-xs font-semibold text-gray-700 mb-2">🎯 建议配置(温和的估值倾斜,每年再平衡)</div>
          <div className="flex h-6 rounded-lg overflow-hidden text-[10px] font-semibold text-white">
            {Object.entries(weights).map(([t, w], i) => (
              <div key={t}
                className={["bg-[#006FFF]", "bg-emerald-500", "bg-amber-500", "bg-purple-500"][i % 4]}
                style={{ width: `${w}%` }} title={`${t} ${w}%`}>
                <span className="px-1.5 leading-6">{t} {w}%</span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-gray-500 leading-relaxed">{state.allocation.note}</p>
        </section>
      )}

      {/* 定投计算器 + 复利希望机(本机累计) */}
      {state && Object.keys(weights).length > 0 && (
        <DcaCalculator weights={weights} results={state.results} />
      )}

      {/* 卡片 */}
      {loading ? (
        <div className="text-sm text-[#525461] flex items-center gap-2 px-1">
          <span className="inline-block w-2.5 h-2.5 rounded-full bg-[#006FFF] animate-pulse" /> 读取定投建议…
        </div>
      ) : !state || state.results.length === 0 ? (
        <div className="bg-white rounded-2xl border border-[#EDEDF0] p-8 text-center text-sm text-gray-400">
          尚未生成 — 运行一次 <code className="font-mono bg-gray-100 px-1 rounded">publish.py</code>(或等每日自动任务)后这里就会有数据。
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {state.results.map(r => <DcaCard key={r.ticker} r={r} />)}
        </div>
      )}

      {/* 压舱格(债券/现金)*/}
      {state?.ballast && (
        <section className="rounded-2xl border border-slate-200 bg-slate-50 p-4 shadow-sm">
          <div className="text-xs font-semibold text-slate-700 mb-1">⚓ 压舱 & 预备金(独立于上面的股票)</div>
          <p className="text-[12px] leading-relaxed text-slate-600">{state.ballast}</p>
        </section>
      )}

      {/* 与投机仓分开 */}
      {state?.separation && (
        <section className="rounded-2xl border border-rose-200 bg-rose-50 p-3.5 shadow-sm">
          <p className="text-[12px] leading-relaxed text-rose-700">{state.separation}</p>
        </section>
      )}

      <footer className="text-center text-[10px] text-gray-400 pb-4 leading-relaxed">
        📥 定投专区 · 估值/季节性是<b>长周期的弱倾斜、不是择时</b>,单一年份可能完全相反 · 长期持续投入 &gt; 精准择时 · 非投资建议
      </footer>
    </main>
  );
}
