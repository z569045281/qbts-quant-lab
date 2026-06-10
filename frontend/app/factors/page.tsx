"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import type { IChartApi, CandlestickData, SeriesMarker, Time } from "lightweight-charts";
import { getFactors, type FactorRow, type ChartData } from "../_lib/data";

/* ── helpers ── */
function fmt(n: number | undefined, pct = false) {
  if (typeof n !== "number" || isNaN(n)) return "—";
  return pct ? `${(n * 100).toFixed(1)}%` : n.toFixed(3);
}
const winColor = (v: number | undefined) =>
  typeof v !== "number" ? "text-gray-400"
  : v > 0.55 ? "text-emerald-600" : v > 0.45 ? "text-amber-500" : "text-red-500";
const ddColor = (v: number | undefined) =>
  typeof v !== "number" ? "text-gray-400"
  : v > -0.2 ? "text-emerald-600" : v > -0.4 ? "text-amber-500" : "text-red-500";

/* ── Factor chart rendered from stored data (no backend) ── */
function FactorChartStatic({ data }: { data: ChartData }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<IChartApi | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let chart: IChartApi | null = null;
    let ro: ResizeObserver | null = null;

    async function init() {
      try {
        const { createChart } = await import("lightweight-charts");
        if (cancelled || !containerRef.current) return;

        chart = createChart(containerRef.current, {
          width:  containerRef.current.clientWidth,
          height: 420,
          layout: { background: { color: "#ffffff" }, textColor: "#525461" },
          grid:   { vertLines: { color: "#EDEDF0" }, horzLines: { color: "#EDEDF0" } },
          crosshair: { mode: 1 },
          rightPriceScale: { borderColor: "#EDEDF0" },
          timeScale: { borderColor: "#EDEDF0", timeVisible: true, secondsVisible: false },
        });
        chartRef.current = chart;

        const candles = chart.addCandlestickSeries({
          upColor: "#22c55e", downColor: "#F03A3E",
          borderUpColor: "#22c55e", borderDownColor: "#F03A3E",
          wickUpColor: "#22c55e", wickDownColor: "#F03A3E",
        });
        candles.setData(
          data.ohlcv.map(b => ({ ...b, time: b.time as Time })) as CandlestickData[]
        );

        const markers: SeriesMarker<Time>[] = data.markers.map(m => ({
          time:     m.time as Time,
          position: m.signal === 1 ? "belowBar" : "aboveBar",
          color:    m.signal === 1 ? "#006FFF"  : "#F03A3E",
          shape:    m.signal === 1 ? "arrowUp"  : "arrowDown",
          text:     m.signal === 1 ? "B"        : "S",
          size:     1,
        }));
        const splitBar = data.ohlcv.reduce((nearest, bar) =>
          Math.abs(bar.time - data.split_time) < Math.abs(nearest.time - data.split_time)
            ? bar : nearest,
          data.ohlcv[0]
        );
        const allMarkers: SeriesMarker<Time>[] = [
          ...markers,
          { time: splitBar?.time as Time, position: "aboveBar" as const,
            color: "#f59e0b", shape: "circle" as const, text: "OOS", size: 0 },
        ].filter(m => m.time != null).sort((a, b) => (a.time as number) - (b.time as number));
        candles.setMarkers(allMarkers);

        chart.timeScale().fitContent();

        ro = new ResizeObserver(() => {
          if (containerRef.current && chartRef.current) {
            chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
          }
        });
        ro.observe(containerRef.current);
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : "图表渲染失败");
      }
    }

    init();
    return () => {
      cancelled = true;
      ro?.disconnect();
      ro = null;
      chartRef.current = null;
      chart?.remove();
    };
  }, [data]);

  return (
    <div className="border-t-2 border-[#006FFF] bg-white">
      <div className="px-5 py-2.5 border-b border-[#EDEDF0] text-xs text-[#525461]">
        橙色圈 = IS/OOS 分割点 &nbsp;·&nbsp;
        <span className="text-[#006FFF] font-medium">▲ 蓝色 = 买入</span> &nbsp;·&nbsp;
        <span className="text-[#F03A3E] font-medium">▼ 红色 = 卖出</span>
      </div>
      {error
        ? <div className="py-16 text-center text-[#F03A3E] text-sm">{error}</div>
        : <div ref={containerRef} className="w-full" />}
    </div>
  );
}

export default function FactorsPage() {
  const [factors, setFactors] = useState<FactorRow[] | null>(null);
  const [error, setError]     = useState<string | null>(null);
  const [openId, setOpenId]   = useState<string | null>(null);
  const [tab, setTab]         = useState<"chart" | "code">("chart");

  useEffect(() => {
    getFactors()
      .then(setFactors)
      .catch(e => setError(e instanceof Error ? e.message : "加载失败"));
  }, []);

  if (error) {
    return (
      <main className="max-w-[1600px] mx-auto px-6 py-10">
        <div className="bg-white rounded-xl border border-red-200 p-6 max-w-xl">
          <div className="text-sm font-semibold text-[#F03A3E] mb-2">⚠️ 因子加载失败</div>
          <pre className="text-xs font-mono text-[#525461] bg-red-50 rounded-md px-3 py-2 whitespace-pre-wrap">{error}</pre>
        </div>
      </main>
    );
  }
  if (!factors) {
    return (
      <main className="max-w-[1600px] mx-auto px-6 py-10 text-sm text-[#525461]">加载因子中…</main>
    );
  }

  const bestSharpe = factors.length ? Math.max(...factors.map(f => f.data.oos_sharpe_ratio)) : null;

  return (
    <main className="max-w-[1600px] mx-auto px-6 py-6 space-y-5">
      {/* ── Header ── */}
      <section className="bg-white rounded-xl border border-[#EDEDF0] px-6 py-4 flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-lg font-bold text-gray-900">⛏️ 因子排行榜</h1>
          <p className="text-xs text-[#525461] mt-0.5">本地挖矿、已发布的因子（只读）。点任意一行看图表与代码。</p>
        </div>
        <div className="flex gap-6 text-right">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500">因子数</div>
            <div className="text-2xl font-bold font-mono text-gray-900">{factors.length}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500">最佳 OOS Sharpe</div>
            <div className="text-2xl font-bold font-mono text-emerald-600">
              {bestSharpe != null ? bestSharpe.toFixed(2) : "—"}
            </div>
          </div>
        </div>
      </section>

      {/* ── Table ── */}
      <section className="bg-white rounded-xl border border-[#EDEDF0] overflow-hidden">
        {factors.length === 0 ? (
          <div className="px-5 py-16 text-center text-sm text-gray-400">
            还没有发布的因子 — 在本地挖矿后运行 <code className="font-mono">publish.py</code>。
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[10px] uppercase tracking-wider text-gray-500 border-b border-[#EDEDF0]">
                  <th className="text-left  px-4 py-2.5 font-medium">因子</th>
                  <th className="text-center px-3 py-2.5 font-medium">类型</th>
                  <th className="text-right px-3 py-2.5 font-medium">Score</th>
                  <th className="text-right px-3 py-2.5 font-medium">OOS Sharpe</th>
                  <th className="text-right px-3 py-2.5 font-medium">胜率</th>
                  <th className="text-right px-3 py-2.5 font-medium">最大回撤</th>
                  <th className="text-right px-3 py-2.5 font-medium">命中率</th>
                  <th className="text-right px-4 py-2.5 font-medium">交易数</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#EDEDF0]">
                {factors.map((f, idx) => {
                  const d = f.data;
                  const open = openId === f.id;
                  return (
                    <Fragment key={f.id}>
                      <tr onClick={() => { setOpenId(open ? null : f.id); setTab("chart"); }}
                          className={`cursor-pointer transition-colors ${open ? "bg-blue-50/60" : "hover:bg-[#F6F6F8]"}`}>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className="text-[10px] font-mono text-gray-400 w-5">{idx + 1}</span>
                            <span className="font-medium text-gray-900">{d.name}</span>
                            {d.overfit && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-50 text-red-600 border border-red-200">过拟合</span>
                            )}
                          </div>
                        </td>
                        <td className="px-3 py-3 text-center">
                          <span className={`text-[10px] px-1.5 py-0.5 rounded border ${
                            d.type === "ml"
                              ? "bg-violet-50 text-violet-700 border-violet-200"
                              : "bg-[#F6F6F8] text-[#525461] border-[#EDEDF0]"}`}>
                            {d.type === "ml" ? "ML" : "规则"} · {d.freq}
                          </span>
                        </td>
                        <td className="px-3 py-3 text-right font-mono font-semibold text-gray-900">{fmt(d.score)}</td>
                        <td className="px-3 py-3 text-right font-mono font-semibold text-[#006FFF]">{fmt(d.oos_sharpe_ratio)}</td>
                        <td className={`px-3 py-3 text-right font-mono font-semibold ${winColor(d.oos_win_rate)}`}>{fmt(d.oos_win_rate, true)}</td>
                        <td className={`px-3 py-3 text-right font-mono font-semibold ${ddColor(d.oos_max_drawdown)}`}>{fmt(d.oos_max_drawdown, true)}</td>
                        <td className={`px-3 py-3 text-right font-mono ${winColor(d.q_hit_rate)}`}>{fmt(d.q_hit_rate, true)}</td>
                        <td className="px-4 py-3 text-right font-mono text-[#525461]">{d.oos_n_trades ?? "—"}</td>
                      </tr>
                      {open && (
                        <tr>
                          <td colSpan={8} className="p-0">
                            <div className="flex gap-1 px-4 pt-3 bg-white">
                              {(["chart", "code"] as const).map(t => (
                                <button key={t} onClick={() => setTab(t)}
                                        className={`px-3 py-1 text-xs rounded-t-md font-medium transition-colors ${
                                          tab === t ? "bg-[#006FFF] text-white" : "text-[#525461] hover:bg-[#F6F6F8]"}`}>
                                  {t === "chart" ? "图表" : "代码"}
                                </button>
                              ))}
                            </div>
                            {tab === "chart"
                              ? (f.chart
                                  ? <FactorChartStatic data={f.chart} />
                                  : <div className="py-12 text-center text-sm text-gray-400 border-t-2 border-[#006FFF]">无图表数据（发布时未生成）</div>)
                              : (f.code
                                  ? <pre className="text-[11px] leading-relaxed font-mono text-gray-800 bg-[#F6F6F8] border-t-2 border-[#006FFF] px-5 py-4 overflow-x-auto whitespace-pre">{f.code}</pre>
                                  : <div className="py-12 text-center text-sm text-gray-400 border-t-2 border-[#006FFF]">无代码</div>)}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="text-center text-[10px] text-gray-400">
        因子由本地挖矿生成、经 publish.py 发布到 Supabase · 仅供研究参考，非投资建议
      </div>
    </main>
  );
}
