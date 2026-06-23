"use client";

import { useEffect, useState } from "react";
import { getWatchScan, type WatchScan, type ScanResult } from "../_lib/data";

/* ─────────────────────────────────────────────────────────────────────────
   🔭 自选扫描 — 分散高波动篮子的每日买点扫描（独立于 QBTS 决策仪表盘）。
   每只票跑通用信号(SMC 结构 / 成交量画像 / 波动 regime),给出买点立场 + 大白话
   触发条件 + 关键价位。纯机械、零额外成本。按"最接近买点"排序。
   ───────────────────────────────────────────────────────────────────────── */

const STANCE: Record<string, { border: string; bg: string; chip: string; bar: string }> = {
  "买入区":   { border: "border-emerald-300", bg: "bg-emerald-50/50", chip: "bg-emerald-100 text-emerald-700", bar: "bg-emerald-500" },
  "接近买点": { border: "border-amber-300",   bg: "bg-amber-50/40",   chip: "bg-amber-100 text-amber-700",   bar: "bg-amber-400" },
  "观望":     { border: "border-[#E5E5EA]",   bg: "bg-white",         chip: "bg-gray-100 text-gray-500",     bar: "bg-gray-400" },
  "偏空回避": { border: "border-red-200",     bg: "bg-red-50/40",     chip: "bg-red-100 text-red-700",       bar: "bg-red-400" },
};
const FALLBACK = { border: "border-[#E5E5EA]", bg: "bg-white", chip: "bg-gray-100 text-gray-500", bar: "bg-gray-300" };

const TREND_CN: Record<string, string> = { bullish: "结构看多", bearish: "结构看空", neutral: "结构中性" };
const REGIME_CN: Record<string, string> = { expansion: "波动扩张", contraction: "波动收缩", normal: "波动正常" };

function pct(n: number | null | undefined): string {
  return typeof n === "number" && isFinite(n) ? `${(n * 100).toFixed(1)}%` : "—";
}

function ScanCard({ r }: { r: ScanResult }) {
  const s = STANCE[r.stance] ?? FALLBACK;
  const up = (r.today_change ?? 0) >= 0;

  if (r.error) {
    return (
      <div className="rounded-2xl border border-[#E5E5EA] bg-white p-4 flex items-center gap-3">
        <span className="text-lg">⚠️</span>
        <span className="font-bold text-gray-800">{r.ticker}</span>
        <span className="text-xs text-gray-400">{r.theme} · 数据拉取失败</span>
      </div>
    );
  }

  return (
    <div className={`rounded-2xl border ${s.border} ${s.bg} p-4 shadow-sm`}>
      {/* 头行 */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-lg leading-none">{r.stance_emoji}</span>
        <span className="text-lg font-bold text-gray-900">{r.ticker}</span>
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 font-medium">{r.theme}</span>
        <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold ${s.chip}`}>{r.stance}</span>
        <span className="ml-auto text-sm font-mono text-gray-900">${r.price?.toFixed(2)}</span>
        <span className={`text-sm font-semibold ${up ? "text-emerald-600" : "text-[#F03A3E]"}`}>
          {up ? "▲" : "▼"} {pct(Math.abs(r.today_change ?? 0))}
        </span>
      </div>

      {/* 评分条 */}
      <div className="flex items-center gap-2 mt-2.5">
        <span className="text-[10px] text-gray-400 w-12">买点分</span>
        <div className="flex-1 h-1.5 rounded-full bg-gray-100 overflow-hidden">
          <div className={`h-full ${s.bar}`} style={{ width: `${r.score}%` }} />
        </div>
        <span className="text-xs font-mono font-semibold text-gray-600 w-8 text-right">{r.score}</span>
      </div>

      {/* 触发条件(大白话) */}
      {r.trigger && (
        <p className="mt-2.5 text-[13px] leading-relaxed text-gray-800">{r.trigger}</p>
      )}

      {/* 关键价位 */}
      {r.levels && (r.levels.buy_zone || r.levels.target) && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] font-mono">
          {r.levels.buy_zone && (
            <span className="text-emerald-700">买入参考 {r.levels.buy_zone}</span>
          )}
          {r.levels.target && (
            <span className="text-blue-600">上方目标 {r.levels.target}</span>
          )}
        </div>
      )}

      {/* meta 标签 */}
      <div className="mt-2.5 flex flex-wrap gap-1.5 text-[10px]">
        {r.trend && (
          <span className={`px-1.5 py-0.5 rounded ${
            r.trend === "bullish" ? "bg-emerald-50 text-emerald-600"
            : r.trend === "bearish" ? "bg-red-50 text-red-600" : "bg-gray-50 text-gray-500"}`}>
            {TREND_CN[r.trend]}
          </span>
        )}
        {r.regime && (
          <span className="px-1.5 py-0.5 rounded bg-gray-50 text-gray-500">{REGIME_CN[r.regime] ?? r.regime}</span>
        )}
        {typeof r.vol_annual === "number" && (
          <span className="px-1.5 py-0.5 rounded bg-gray-50 text-gray-500">年化波动 {Math.round(r.vol_annual * 100)}%</span>
        )}
        {typeof r.rsi === "number" && (
          <span className="px-1.5 py-0.5 rounded bg-gray-50 text-gray-500">RSI {r.rsi.toFixed(0)}</span>
        )}
      </div>
    </div>
  );
}

export default function WatchScanPage() {
  const [scan, setScan] = useState<WatchScan | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let stop = false;
    (async () => {
      const s = await getWatchScan();
      if (!stop) { setScan(s); setLoading(false); }
    })();
    return () => { stop = true; };
  }, []);

  const genAt = scan?.generated_at?.slice(0, 16).replace("T", " ");

  return (
    <main className="max-w-[1100px] mx-auto px-6 py-6 space-y-4">
      {/* 标题 */}
      <section className="bg-white rounded-2xl border border-[#EDEDF0] p-5 shadow-sm">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-base">🔭</span>
          <span className="text-sm font-semibold text-gray-800">自选扫描 · 分散高波动篮子</span>
          {genAt && <span className="ml-auto text-[10px] text-gray-400 font-mono">扫描于 {genAt}</span>}
        </div>
        <p className="mt-2 text-xs text-[#525461] leading-relaxed">
          7 个不同驱动的高波动板块(平均相关仅 0.30),每天扫一遍——按"最接近买点"排序。
          每只票给出立场、大白话触发条件和关键价位。<span className="text-gray-400">纯机械信号,免费。</span>
        </p>
        <div className="mt-2 flex flex-wrap gap-2 text-[10px]">
          {[["🟢", "买入区"], ["🟡", "接近买点"], ["⚪", "观望"], ["🔴", "偏空回避"]].map(([e, l]) => (
            <span key={l} className="px-1.5 py-0.5 rounded bg-[#F6F6F8] text-gray-500">{e} {l}</span>
          ))}
        </div>
      </section>

      {/* 状态 */}
      {loading ? (
        <div className="text-sm text-[#525461] flex items-center gap-2 px-1">
          <span className="inline-block w-2.5 h-2.5 rounded-full bg-[#006FFF] animate-pulse" /> 读取扫描结果…
        </div>
      ) : !scan || scan.results.length === 0 ? (
        <div className="bg-white rounded-2xl border border-[#EDEDF0] p-8 text-center text-sm text-gray-400">
          尚未生成扫描 — 运行一次 <code className="font-mono bg-gray-100 px-1 rounded">publish.py</code>(或等每日自动任务)后这里就会有数据。
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {scan.results.map(r => <ScanCard key={r.ticker} r={r} />)}
        </div>
      )}

      <footer className="text-center text-[10px] text-gray-400 pb-4 leading-relaxed">
        🔭 自选扫描 · 这些是高波动投机性标的的<b>扫描候选,非买入建议</b> · 系统只提示"哪只 / 什么价 / 什么时候"接近 setup,买卖与仓位由你决定 · 非投资建议
      </footer>
    </main>
  );
}
