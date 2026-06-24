"use client";

import { useEffect, useState } from "react";
import { getDcaState, type DcaState, type DcaResult } from "../_lib/data";

/* ─────────────────────────────────────────────────────────────────────────
   📥 定投专区 — 闲钱定投宽基 ETF。不是择时信号:定投的核心是"待在市场里"。
   这里只用 季节性(万圣节/9月效应)+ 回调/200日均线 给一个温和的"现在多投/正常/
   偏高"提示,其他时间照常投、放着就好。
   ───────────────────────────────────────────────────────────────────────── */

const STANCE: Record<string, { border: string; bg: string; chip: string }> = {
  "逢低加码":        { border: "border-emerald-300", bg: "bg-emerald-50/50", chip: "bg-emerald-100 text-emerald-700" },
  "正常定投":        { border: "border-amber-200",   bg: "bg-amber-50/30",   chip: "bg-amber-100 text-amber-700" },
  "偏高·照投或少投": { border: "border-blue-200",     bg: "bg-blue-50/30",    chip: "bg-blue-100 text-blue-600" },
};
const FALLBACK = { border: "border-[#E5E5EA]", bg: "bg-white", chip: "bg-gray-100 text-gray-500" };

const pct = (n: number | null | undefined, d = 1) =>
  typeof n === "number" && isFinite(n) ? `${(n * 100).toFixed(d)}%` : "—";
const signed = (n: number | null | undefined, d = 1) =>
  typeof n === "number" && isFinite(n) ? `${n >= 0 ? "+" : ""}${(n * 100).toFixed(d)}%` : "—";
const mo = (m: number | null | undefined) => (typeof m === "number" ? `${m}月` : "—");

function DcaCard({ r }: { r: DcaResult }) {
  const s = STANCE[r.stance] ?? FALLBACK;
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
    <div className={`rounded-2xl border ${s.border} ${s.bg} p-4 shadow-sm`}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-lg font-bold text-gray-900">{r.ticker}</span>
        <span className="text-[11px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 font-medium">{r.name}</span>
        <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold ${s.chip}`}>{r.stance_emoji} {r.stance}</span>
        <span className="ml-auto text-sm font-mono text-gray-900">${r.price?.toFixed(2)}</span>
        <span className={`text-sm font-semibold ${up ? "text-emerald-600" : "text-[#F03A3E]"}`}>{signed(r.today_change)}</span>
      </div>

      {r.hint && <p className="mt-2.5 text-[13px] leading-relaxed text-gray-800">{r.hint}</p>}

      {/* 估值/位置 */}
      <div className="mt-2.5 grid grid-cols-2 gap-2 text-xs">
        <div className="bg-white/70 rounded-lg px-2.5 py-1.5">
          <div className="text-[10px] text-gray-400">距52周高点</div>
          <div className={`font-mono font-semibold ${(r.drawdown_pct ?? 0) <= -0.1 ? "text-emerald-600" : "text-gray-700"}`}>{signed(r.drawdown_pct)}</div>
        </div>
        <div className="bg-white/70 rounded-lg px-2.5 py-1.5">
          <div className="text-[10px] text-gray-400">vs 200日均线</div>
          <div className={`font-mono font-semibold ${r.below_200 ? "text-emerald-600" : "text-gray-700"}`}>
            {signed(r.vs_200dma_pct)} {r.below_200 ? "(下方·便宜)" : ""}
          </div>
        </div>
      </div>

      {/* 季节性 */}
      <div className="mt-2 text-[11px] text-[#525461] leading-relaxed bg-white/60 rounded-lg px-2.5 py-1.5">
        📅 历史最强 <b>{mo(r.best_month)}</b>({signed(r.best_month_avg)}/月) · 最弱 <b>{mo(r.worst_month)}</b>({signed(r.worst_month_avg)}/月)
        {r.cur_month_avg != null && <> · 本月({mo(r.cur_month)})历史均值 {signed(r.cur_month_avg)}</>}
        <br />
        ❄️ 冬季(11–4月) {signed(r.winter_avg)}/月 vs ☀️ 夏季(5–10月) {signed(r.summer_avg)}/月
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

  return (
    <main className="max-w-[1100px] mx-auto px-6 py-6 space-y-4">
      {/* 标题 + 季节横幅 */}
      <section className="bg-white rounded-2xl border border-[#EDEDF0] p-5 shadow-sm">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-base">📥</span>
          <span className="text-sm font-semibold text-gray-800">定投专区 · 闲钱定投宽基 ETF</span>
          {genAt && <span className="ml-auto text-[10px] text-gray-400 font-mono">更新于 {genAt}</span>}
        </div>
        {state?.season?.note && (
          <div className={`mt-3 rounded-xl px-4 py-2.5 text-sm leading-relaxed ${
            state.season.in_strong_window ? "bg-emerald-50 text-emerald-800 border border-emerald-200"
            : "bg-amber-50 text-amber-800 border border-amber-200"}`}>
            🗓️ {state.season.note}
          </div>
        )}
        {state?.principle && (
          <p className="mt-2 text-[11px] text-gray-400 leading-relaxed">{state.principle}</p>
        )}
      </section>

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

      <footer className="text-center text-[10px] text-gray-400 pb-4 leading-relaxed">
        📥 定投专区 · 季节性是历史平均的<b>微弱倾向、不是保证</b>(尤其单一年份波动极大) · 长期定投&gt;精准择时 · 非投资建议
      </footer>
    </main>
  );
}
