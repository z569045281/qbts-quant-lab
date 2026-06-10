"use client";

import { useEffect, useRef } from "react";
import type {
  IChartApi,
  CandlestickData,
  LineData,
  Time,
} from "lightweight-charts";

interface ChartCandle { time: number; open: number; high: number; low: number; close: number; }
interface ChartLine   { time: number; value: number; }

interface MiniChartProps {
  candles:   ChartCandle[];
  sma20:     ChartLine[];
  sma200:    ChartLine[];
  high_52w:  number;
  low_52w:   number;
}

export function MiniChart({ candles, sma20, sma200, high_52w, low_52w }: MiniChartProps) {
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
        height: 280,
        layout: { background: { color: "#ffffff" }, textColor: "#525461", fontSize: 11 },
        grid:   { vertLines: { color: "#F0F0F2" }, horzLines: { color: "#F0F0F2" } },
        rightPriceScale: { borderColor: "#EDEDF0" },
        timeScale: { borderColor: "#EDEDF0", timeVisible: false, secondsVisible: false },
        crosshair: { mode: 1 },
      });
      chartRef.current = chart;

      // Candlesticks
      const candleSeries = chart.addCandlestickSeries({
        upColor: "#22c55e", downColor: "#F03A3E",
        borderUpColor: "#22c55e", borderDownColor: "#F03A3E",
        wickUpColor: "#22c55e", wickDownColor: "#F03A3E",
      });
      candleSeries.setData(candles.map(c => ({ ...c, time: c.time as Time })) as CandlestickData[]);

      // SMA20 line
      if (sma20.length > 0) {
        const s20 = chart.addLineSeries({
          color: "#F59E0B", lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
        });
        s20.setData(sma20.map(p => ({ ...p, time: p.time as Time })) as LineData[]);
      }

      // SMA200 line
      if (sma200.length > 0) {
        const s200 = chart.addLineSeries({
          color: "#8B5CF6", lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
        });
        s200.setData(sma200.map(p => ({ ...p, time: p.time as Time })) as LineData[]);
      }

      // 52-week high/low horizontal lines
      candleSeries.createPriceLine({
        price: high_52w, color: "#9CA3AF", lineWidth: 1, lineStyle: 2,  // dashed
        axisLabelVisible: true, title: "52w High",
      });
      candleSeries.createPriceLine({
        price: low_52w, color: "#9CA3AF", lineWidth: 1, lineStyle: 2,
        axisLabelVisible: true, title: "52w Low",
      });

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
  }, [candles, sma20, sma200, high_52w, low_52w]);

  return (
    <section className="bg-white rounded-xl border border-[#EDEDF0] overflow-hidden">
      <div className="px-5 py-3.5 border-b border-[#EDEDF0] flex items-center justify-between">
        <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
          📈 60 日价格走势
        </span>
        <div className="flex items-center gap-3 text-[10px] font-mono">
          <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-[#F59E0B]" />SMA20</span>
          <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-[#8B5CF6]" />SMA200</span>
          <span className="flex items-center gap-1"><span className="w-3 h-px border-t border-dashed border-gray-400" />52w 高低</span>
        </div>
      </div>
      <div ref={containerRef} className="w-full" style={{ height: 280 }} />
    </section>
  );
}
