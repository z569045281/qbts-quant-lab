"use client";

import { useEffect, useRef } from "react";
import type {
  IChartApi,
  CandlestickData,
  LineData,
  SeriesMarker,
  Time,
} from "lightweight-charts";

interface ChartCandle { time: number; open: number; high: number; low: number; close: number; }
interface ChartLine   { time: number; value: number; }
interface ZoneBand    { low: number; high: number; }
/** A past graded decision, plotted as a marker on its bar. */
export interface DecisionMarker { time: number; action: string; correct: boolean | null; }
/** Today's plan levels (QBTS prices) to draw as horizontal lines. */
export interface PlanLevels { entry: number | null; stop: number | null; target: number | null; action: string; }

interface MiniChartProps {
  candles:   ChartCandle[];
  sma20:     ChartLine[];
  sma200:    ChartLine[];
  high_52w:  number;
  low_52w:   number;
  plan?:     PlanLevels | null;     // 入场/止损/目标三线(仅方向单)
  supply?:   ZoneBand[];            // SMC 供给区(上方阻力)
  demand?:   ZoneBand[];            // SMC 需求区(下方支撑)
  poc?:      number | null;         // 成交量控制点
  markers?:  DecisionMarker[];      // 历史已评判决策 ✓/✗
}

export function MiniChart({
  candles, sma20, sma200, high_52w, low_52w,
  plan = null, supply, demand, poc = null, markers,
}: MiniChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<IChartApi | null>(null);

  useEffect(() => {
    let chart: IChartApi | null = null;
    let ro: ResizeObserver | null = null;
    let cancelled = false;

    async function init() {
      const { createChart } = await import("lightweight-charts");
      if (cancelled || !containerRef.current) return;

      chart = createChart(containerRef.current, {
        width:  containerRef.current.clientWidth,
        height: 300,
        layout: { background: { color: "#ffffff" }, textColor: "#525461", fontSize: 11 },
        grid:   { vertLines: { color: "#F0F0F2" }, horzLines: { color: "#F0F0F2" } },
        rightPriceScale: { borderColor: "#EDEDF0" },
        timeScale: { borderColor: "#EDEDF0", timeVisible: false, secondsVisible: false },
        crosshair: { mode: 1 },
      });
      chartRef.current = chart;

      const candleSeries = chart.addCandlestickSeries({
        upColor: "#22c55e", downColor: "#F03A3E",
        borderUpColor: "#22c55e", borderDownColor: "#F03A3E",
        wickUpColor: "#22c55e", wickDownColor: "#F03A3E",
      });
      candleSeries.setData(candles.map(c => ({ ...c, time: c.time as Time })) as CandlestickData[]);

      if (sma20.length > 0) {
        const s20 = chart.addLineSeries({ color: "#F59E0B", lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
        s20.setData(sma20.map(p => ({ ...p, time: p.time as Time })) as LineData[]);
      }
      if (sma200.length > 0) {
        const s200 = chart.addLineSeries({ color: "#8B5CF6", lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
        s200.setData(sma200.map(p => ({ ...p, time: p.time as Time })) as LineData[]);
      }

      // 52-week high/low (faint dashed)
      candleSeries.createPriceLine({ price: high_52w, color: "#D1D5DB", lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "52w高" });
      candleSeries.createPriceLine({ price: low_52w,  color: "#D1D5DB", lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "52w低" });

      // SMC 供给/需求带(最近一档,虚线;只展示直接语境,卡片里有全部)
      const band = (z: ZoneBand, color: string, label: string) => {
        candleSeries.createPriceLine({ price: z.high, color, lineWidth: 1, lineStyle: 1, axisLabelVisible: false, title: label });
        candleSeries.createPriceLine({ price: z.low,  color, lineWidth: 1, lineStyle: 1, axisLabelVisible: false, title: "" });
      };
      (supply ?? []).slice(0, 1).forEach(z => band(z, "rgba(240,58,62,0.45)", "供给"));
      (demand ?? []).slice(0, 1).forEach(z => band(z, "rgba(22,163,74,0.45)", "需求"));

      // POC(成交量控制点,灰色虚线)
      if (poc != null && isFinite(poc)) {
        candleSeries.createPriceLine({ price: poc, color: "#6B7280", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "POC" });
      }

      // 今日计划三线(实线,醒目)——仅方向单
      if (plan && (plan.action === "LONG_QBTX" || plan.action === "SHORT_QBTZ")) {
        const mk = (price: number | null, color: string, title: string) => {
          if (price == null || !isFinite(price)) return;
          candleSeries.createPriceLine({ price, color, lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title });
        };
        mk(plan.entry,  "#2563EB", "入场");
        mk(plan.stop,   "#F03A3E", "止损");
        mk(plan.target, "#16A34A", "目标");
      }

      // 历史已评判决策标记(✓做对 / ✗做错)
      if (markers && markers.length) {
        const ms: SeriesMarker<Time>[] = [...markers]
          .sort((a, b) => a.time - b.time)
          .map(m => ({
            time: m.time as Time,
            position: m.action === "LONG_QBTX" ? "belowBar" : "aboveBar",
            shape:    m.action === "LONG_QBTX" ? "arrowUp" : "arrowDown",
            color: m.correct === true ? "#16A34A" : m.correct === false ? "#F03A3E" : "#9CA3AF",
            text: (m.action === "LONG_QBTX" ? "多" : "空") + (m.correct === true ? "✓" : m.correct === false ? "✗" : ""),
          }));
        candleSeries.setMarkers(ms);
      }

      chart.timeScale().fitContent();

      ro = new ResizeObserver(() => {
        if (containerRef.current && chartRef.current) {
          chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
        }
      });
      ro.observe(containerRef.current);
    }

    init();
    return () => {
      cancelled = true;
      ro?.disconnect();
      ro = null;
      chartRef.current = null;
      chart?.remove();
    };
  }, [candles, sma20, sma200, high_52w, low_52w, plan, supply, demand, poc, markers]);

  const hasPlan = !!(plan && (plan.action === "LONG_QBTX" || plan.action === "SHORT_QBTZ"));

  return (
    <section className="bg-white rounded-xl border border-[#EDEDF0] overflow-hidden">
      <div className="px-5 py-3.5 border-b border-[#EDEDF0] flex items-center justify-between flex-wrap gap-2">
        <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
          📈 60 日价格走势{hasPlan ? " · 计划 / 区位 / 战绩" : ""}
        </span>
        <div className="flex items-center gap-2.5 text-[10px] font-mono flex-wrap">
          <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-[#F59E0B]" />SMA20</span>
          <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-[#8B5CF6]" />SMA200</span>
          {hasPlan && <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-[#2563EB]" />入场</span>}
          {hasPlan && <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-[#F03A3E]" />止损</span>}
          {hasPlan && <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-[#16A34A]" />目标</span>}
          <span className="flex items-center gap-1"><span className="w-3 h-px border-t border-dotted border-gray-400" />供给/需求·POC</span>
          <span className="flex items-center gap-1">↑✓/↓✗ 历史决策</span>
        </div>
      </div>
      <div ref={containerRef} className="w-full" style={{ height: 300 }} />
    </section>
  );
}
