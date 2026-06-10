"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import type { IChartApi, ISeriesApi, CandlestickData, SeriesMarker, Time } from "lightweight-charts";
import { API } from "../_lib/api";
import { READONLY } from "../_lib/supabase";

interface FactorEntry {
  id: string;
  name: string;
  description: string;
  freq: string;
  overfit: boolean;
  is_win_rate: number;
  is_sharpe: number;
  is_max_drawdown: number;
  is_total_return: number;
  oos_win_rate: number;
  oos_max_drawdown: number;
  oos_risk_reward: number;
  oos_sharpe_ratio: number;
  oos_total_return: number;
  oos_n_trades: number;
  oos_n_stops?: number;            // Phase-1: stop-loss fires
  oos_worst_bar_loss?: number;     // Phase-1: worst single-bar loss (negative)
  q_ic_mean: number;
  q_icir: number;
  q_hit_rate?: number;             // Phase-2: directional accuracy on active bars
  q_n_signals?: number;            // Phase-2: count of active bars
  q_ic_pvalue?: number;            // Phase-2: p-value for IC
  type?: "ml" | "rule";            // Phase-3b: ML (LightGBM) vs rule (if-then) factor
  q_positive_ic_ratio: number;
  ic_decay: Record<string, number>;
  score: number;
  favorited: boolean;
}

interface LogLine {
  id: number;
  level: "info" | "success" | "error";
  msg: string;
  ts: string;
}

/* Phase 4 — live signal payload */
interface TodayFactorSignal {
  id: string;
  name: string;
  type: "ml" | "rule";
  freq: string;
  score: number;
  oos_sharpe: number;
  hit_rate: number;
  signal: -1 | 0 | 1;
  label: "BUY" | "SELL" | "HOLD" | "ERROR";
  weight?: number;
  error?: string;
}
interface TodaySignalsPayload {
  as_of:    string | null;
  close:    number | null;
  factors:  TodayFactorSignal[];
  ensemble: {
    signal:    -1 | 0 | 1;
    label:     "BUY" | "SELL" | "HOLD";
    raw_blend: number;
    n_active:  number;
    n_buy:     number;
    n_sell:    number;
    n_hold:    number;
  } | null;
  reason?: string;
}

interface AccountInfo {
  portfolio_value: number;
  cash: number;
  buying_power: number;
  daily_pnl: number;
  daily_pnl_pct: number;
}

interface PositionInfo {
  qty: number;
  side: string;
  avg_entry_price: number;
  current_price: number;
  market_value: number;
  unrealized_pl: number;
  unrealized_plpc: number;
}

interface SignalInfo {
  value: number;
  label: "BUY" | "SELL" | "HOLD";
  factor_name: string;
  factor_score: number;
  freq: string;
}

interface OrderRow {
  id: string;
  created_at: string;
  side: string;
  qty: number;
  filled_qty: number;
  filled_avg_price: number;
  status: string;
}

interface TradingStatus {
  configured: boolean;
  hint?: string;
  account?: AccountInfo;
  position?: PositionInfo | null;
  signal?: SignalInfo | null;
  orders?: OrderRow[];
}

type SortKey = "score" | "oos_sharpe_ratio" | "oos_win_rate" | "oos_max_drawdown" | "oos_total_return" | "q_icir" | "q_hit_rate";
type FilterTab = "all" | "passed" | "overfit" | "starred";

/* ── helpers ── */
function fmt(n: number, pct = false) {
  if (pct) return `${(n * 100).toFixed(1)}%`;
  return n.toFixed(3);
}

function fmtElapsed(s: number) {
  const m = Math.floor(s / 60), sec = s % 60;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

/* Terminal log colors — kept dark since terminal bg is dark */
const logColor: Record<string, string> = {
  info: "text-slate-400", success: "text-emerald-400", error: "text-red-400",
};
const logPrefix: Record<string, string> = {
  info: "›", success: "✓", error: "✗",
};

/* Metric badges — dark text for white card backgrounds */
function WinBadge({ v }: { v: number }) {
  const c = v > 0.55 ? "text-emerald-600" : v > 0.45 ? "text-amber-500" : "text-red-500";
  return <span className={`font-mono font-semibold text-xs ${c}`}>{fmt(v, true)}</span>;
}
function DDBadge({ v }: { v: number }) {
  const c = v > -0.2 ? "text-emerald-600" : v > -0.4 ? "text-amber-500" : "text-red-500";
  return <span className={`font-mono font-semibold text-xs ${c}`}>{fmt(v, true)}</span>;
}

/* IC decay sparkline — blue positive, red negative, light baseline */
function IcSparkline({ decay }: { decay: Record<string, number> }) {
  const vals = Object.entries(decay)
    .sort((a, b) => +a[0] - +b[0])
    .map(([, v]) => v);
  if (!vals.length) return <span className="text-gray-300 text-xs">—</span>;
  const W = 56, H = 18, peak = Math.max(...vals.map(Math.abs), 0.05);
  const bw = Math.floor(W / vals.length) - 1;
  return (
    <svg width={W} height={H} className="inline-block align-middle">
      <line x1={0} y1={H / 2} x2={W} y2={H / 2} stroke="#EDEDF0" strokeWidth={0.5} />
      {vals.map((v, i) => {
        const h = Math.max((Math.abs(v) / peak) * (H / 2 - 1), 1);
        const y = v >= 0 ? H / 2 - h : H / 2;
        const fill = v > 0.03 ? "#006FFF" : v > 0 ? "#93c5fd" : "#F03A3E";
        return <rect key={i} x={i * (bw + 1)} y={y} width={bw} height={h} fill={fill} rx={0.5} />;
      })}
    </svg>
  );
}

/* Export leaderboard to CSV */
function exportCSV(factors: FactorEntry[]) {
  const cols: (keyof FactorEntry)[] = [
    "name", "freq", "overfit",
    "is_sharpe", "is_win_rate",
    "oos_sharpe_ratio", "oos_win_rate", "oos_max_drawdown", "oos_total_return", "oos_n_trades",
    "oos_n_stops", "oos_worst_bar_loss",
    "q_hit_rate", "q_n_signals", "q_ic_mean", "q_icir", "q_ic_pvalue", "score",
  ];
  const rows = [cols.join(","), ...factors.map(f => cols.map(c => f[c]).join(","))];
  const blob = new Blob([rows.join("\n")], { type: "text/csv" });
  const url  = URL.createObjectURL(blob);
  Object.assign(document.createElement("a"), { href: url, download: "qbts_factors.csv" }).click();
  URL.revokeObjectURL(url);
}

/* ── Factor Chart (TradingView lightweight-charts) ── */
interface ChartData {
  factor_name: string;
  freq: string;
  ohlcv: { time: number; open: number; high: number; low: number; close: number }[];
  markers: { time: number; signal: number }[];
  split_time: number;
}

function FactorChart({ factorId, factorName, onClose }: {
  factorId: string;
  factorName: string;
  onClose: () => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<IChartApi | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let chart: IChartApi | null = null;
    let ro: ResizeObserver | null = null;

    async function init() {
      setLoading(true);
      setError(null);

      try {
        const [{ createChart }, res] = await Promise.all([
          import("lightweight-charts"),
          fetch(`${API}/factors/${factorId}/chart`),
        ]);

        if (cancelled) return;
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: ChartData = await res.json();
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
        /* IS / OOS split marker — find nearest candle to split_time */
        const splitBar = data.ohlcv.reduce((nearest, bar) =>
          Math.abs(bar.time - data.split_time) < Math.abs(nearest.time - data.split_time)
            ? bar : nearest,
          data.ohlcv[0]
        );
        const allMarkers: SeriesMarker<Time>[] = [
          ...markers,
          {
            time:     splitBar.time as Time,
            position: "aboveBar" as const,
            color:    "#f59e0b",
            shape:    "circle" as const,
            text:     "OOS",
            size:     0,
          },
        ].sort((a, b) => (a.time as number) - (b.time as number));
        candles.setMarkers(allMarkers);

        chart.timeScale().fitContent();
        setLoading(false);

        // ro is declared in outer scope so the cleanup function can disconnect it
        ro = new ResizeObserver(() => {
          if (containerRef.current && chartRef.current) {
            chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
          }
        });
        ro.observe(containerRef.current!);
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : "加载失败");
        setLoading(false);
      }
    }

    init();
    return () => {
      cancelled = true;
      // Disconnect ResizeObserver BEFORE removing the chart — otherwise the
      // observer fires one last time against an already-disposed chart object.
      ro?.disconnect();
      ro = null;
      chartRef.current = null;
      chart?.remove();
    };
  }, [factorId]);

  return (
    <div className="border-t-2 border-[#006FFF] bg-white">
      {/* Chart header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-[#EDEDF0]">
        <div>
          <span className="font-semibold text-gray-900 text-sm">{factorName}</span>
          <span className="ml-3 text-xs text-[#525461]">
            黄色虚线 = IS/OOS 分割点 &nbsp;·&nbsp;
            <span className="text-[#006FFF] font-medium">▲ 蓝色 = 买入</span>
            &nbsp;·&nbsp;
            <span className="text-[#F03A3E] font-medium">▼ 红色 = 卖出</span>
          </span>
        </div>
        <button
          onClick={onClose}
          className="text-[#525461] hover:text-gray-900 text-lg leading-none px-2 transition-colors"
        >
          ✕
        </button>
      </div>

      {/* Chart area */}
      <div className="relative">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/80 z-10">
            <span className="text-sm text-[#525461]">加载图表数据...</span>
          </div>
        )}
        {error && (
          <div className="py-16 text-center text-[#F03A3E] text-sm">{error}</div>
        )}
        <div ref={containerRef} className="w-full" />
      </div>
    </div>
  );
}

/* Reusable card shell */
function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-white rounded-xl border border-[#EDEDF0] shadow-sm ${className}`}>
      {children}
    </div>
  );
}

/* Card section header */
function CardHeader({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="px-5 py-3.5 border-b border-[#EDEDF0] flex items-center justify-between">
      <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">{children}</span>
      {right && <div className="flex items-center gap-2">{right}</div>}
    </div>
  );
}

/* ── Phase 4: Today's Signals panel ── */
function TodaySignalsPanel() {
  const [data, setData] = useState<TodaySignalsPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshAt, setRefreshAt] = useState<number>(0);

  const refresh = useCallback(() => {
    setLoading(true);
    fetch(`${API}/today/signals?top_n=6`)
      .then(r => r.json())
      .then((d: TodaySignalsPayload) => {
        setData(d);
        setRefreshAt(Date.now());
      })
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  if (!data) {
    return (
      <Card className="px-5 py-5">
        <div className="text-sm text-[#525461]">
          {loading ? "正在拉取今日信号..." : "无数据 — 先在下方挖矿生成因子"}
        </div>
      </Card>
    );
  }

  const ens = data.ensemble;
  const ensColor = ens?.signal === 1   ? "text-emerald-600 bg-emerald-50 border-emerald-200"
                 : ens?.signal === -1  ? "text-[#F03A3E]  bg-red-50      border-red-200"
                 :                       "text-[#525461]  bg-[#F6F6F8]   border-[#EDEDF0]";

  return (
    <Card>
      <CardHeader
        right={
          <>
            <span className="text-xs text-gray-400">
              基准价 ${data.close?.toFixed(2) ?? "—"} · 截至 {data.as_of?.slice(0, 10) ?? "—"}
            </span>
            <button
              onClick={refresh}
              disabled={loading}
              className="px-2.5 py-1 text-xs text-[#006FFF] hover:bg-blue-50 rounded transition-colors disabled:opacity-50"
            >
              {loading ? "刷新中…" : "刷新"}
            </button>
          </>
        }
      >
        🎯 今日信号 · Top-6 因子综合
      </CardHeader>

      <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-5 p-5">
        {/* Big ensemble verdict */}
        <div className={`rounded-xl border-2 ${ensColor} p-5 flex flex-col items-center justify-center text-center`}>
          <div className="text-xs uppercase tracking-widest opacity-75 mb-2">综合判定</div>
          <div className="text-5xl font-bold mb-2">
            {ens?.label === "BUY"  ? "↗ 多" :
             ens?.label === "SELL" ? "↘ 空" :
             ens                   ? "— 观望" : "—"}
          </div>
          {ens && (
            <>
              <div className="text-xs font-mono opacity-75">
                混合强度 {ens.raw_blend > 0 ? "+" : ""}{(ens.raw_blend * 100).toFixed(0)}%
              </div>
              <div className="mt-3 flex gap-3 text-xs">
                <span className="text-emerald-700">▲{ens.n_buy}</span>
                <span className="text-gray-500">●{ens.n_hold}</span>
                <span className="text-[#F03A3E]">▼{ens.n_sell}</span>
              </div>
            </>
          )}
        </div>

        {/* Per-factor cards */}
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {data.factors.length === 0 ? (
            <div className="col-span-full text-sm text-[#525461]">无可用因子</div>
          ) : data.factors.map(f => {
            const sigColor = f.signal === 1   ? "text-emerald-600 border-emerald-200 bg-emerald-50"
                           : f.signal === -1  ? "text-[#F03A3E]   border-red-200      bg-red-50"
                           : f.label === "ERROR" ? "text-[#F03A3E] border-red-200    bg-red-50"
                           :                     "text-[#525461]   border-[#EDEDF0]   bg-[#F6F6F8]";
            return (
              <div key={f.id} className={`rounded-lg border ${sigColor} px-3 py-2.5`}>
                <div className="flex items-start justify-between mb-1.5">
                  <div className="text-xs font-medium text-gray-900 truncate flex-1" title={f.name}>
                    {f.name.length > 26 ? f.name.slice(0, 26) + "…" : f.name}
                  </div>
                  {f.type === "ml" && (
                    <span className="ml-1.5 shrink-0 px-1 py-0.5 text-[9px] font-bold rounded bg-violet-100 text-violet-700">ML</span>
                  )}
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-lg font-bold">
                    {f.signal === 1 ? "↗ 多" : f.signal === -1 ? "↘ 空" : f.label === "ERROR" ? "⚠" : "—"}
                  </span>
                  <div className="text-right text-[10px] font-mono text-gray-500">
                    <div>S {f.oos_sharpe.toFixed(1)}</div>
                    <div>权重 {((f.weight ?? 0) * 100).toFixed(0)}%</div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}

/**
 * The mining console talks to the local FastAPI backend (SSE mining, trading,
 * favorites, reset). It only works locally. On the read-only public deployment
 * (NEXT_PUBLIC_DEPLOY_READONLY=1) MinePage redirects to the dashboard instead.
 */
export default function MinePage() {
  const router = useRouter();
  useEffect(() => { if (READONLY) router.replace("/"); }, [router]);
  if (READONLY) {
    return (
      <main className="max-w-[1600px] mx-auto px-6 py-16 text-center text-sm text-[#525461]">
        因子挖矿控制台仅在本地可用，正在跳转到决策仪表盘…
      </main>
    );
  }
  return <MineConsole />;
}

function MineConsole() {
  /* ── core state ── */
  const [mining, setMining]       = useState(false);
  const [done, setDone]           = useState(false);
  const [rounds, setRounds]       = useState(8);
  const [autoLoop, setAutoLoop]   = useState(false);
  const [logs, setLogs]           = useState<LogLine[]>([]);
  const [factors, setFactors]     = useState<FactorEntry[]>([]);
  const [elapsed, setElapsed]     = useState(0);
  const [filter, setFilter]       = useState<FilterTab>("all");
  const [sortKey, setSortKey]     = useState<SortKey>("score");
  const [sortDir, setSortDir]     = useState<1 | -1>(-1);
  const [sentiment, setSentiment] = useState<{
    sentiment_label: string; bull_ratio: number;
    message_count: number; watchers: number | string; fetched_at: string;
  } | null>(null);
  const [ensemble, setEnsemble]   = useState<{
    kept_count: number; dropped_count: number;
    ens_win_rate: number; ens_sharpe_ratio: number;
    ens_max_drawdown: number; ens_total_return: number;
  } | null>(null);

  /* ── chart state ── */
  const [chartFactor, setChartFactor] = useState<{ id: string; name: string } | null>(null);

  /* ── trading state ── */
  const [trading, setTrading]               = useState<TradingStatus | null>(null);
  const [tradeExecuting, setTradeExecuting] = useState(false);
  const [tradeLogs, setTradeLogs]           = useState<LogLine[]>([]);
  const tradeLogId  = useRef(0);
  const tradeLogEnd = useRef<HTMLDivElement>(null);
  const tradeSrcRef = useRef<EventSource | null>(null);

  const logEndRef = useRef<HTMLDivElement>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const logId     = useRef(0);
  const startRef  = useRef<number>(0);

  /* ── initial leaderboard ── */
  useEffect(() => {
    fetch(`${API}/leaderboard`).then(r => r.json()).then(setFactors).catch(() => {});
  }, []);

  /* ── trading status polling ── */
  const fetchTradingStatus = useCallback(() => {
    fetch(`${API}/trading/status`)
      .then(r => r.json())
      .then(setTrading)
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchTradingStatus();
    const id = setInterval(fetchTradingStatus, 30_000);
    return () => clearInterval(id);
  }, [fetchTradingStatus]);

  useEffect(() => { tradeLogEnd.current?.scrollIntoView({ behavior: "smooth" }); }, [tradeLogs]);

  function addTradeLog(level: LogLine["level"], msg: string) {
    const ts = new Date().toLocaleTimeString("en-US", { hour12: false });
    setTradeLogs(prev => [...prev, { id: tradeLogId.current++, level, msg, ts }]);
  }

  function executeSignal() {
    if (tradeExecuting) return;
    setTradeLogs([]);
    setTradeExecuting(true);
    const src = new EventSource(`${API}/trading/execute`);
    tradeSrcRef.current = src;
    src.onmessage = (e) => {
      const p = JSON.parse(e.data);
      if (p.type === "log") addTradeLog(p.level ?? "info", p.msg);
      else if (p.type === "account") setTrading(prev => prev ? { ...prev, account: p.data } : prev);
      else if (p.type === "signal")  setTrading(prev => prev ? { ...prev, signal: p.data }  : prev);
      else if (p.type === "refresh") setTrading(prev => prev
        ? { ...prev, account: p.account, position: p.position, orders: p.orders } : prev);
      else if (p.type === "done") {
        addTradeLog(p.success ? "success" : "error", p.msg ?? (p.success ? "执行完成" : "执行失败"));
        setTradeExecuting(false);
        src.close();
        tradeSrcRef.current = null;
      }
    };
    src.onerror = () => {
      addTradeLog("error", "SSE 连接中断。");
      setTradeExecuting(false);
      src.close();
      tradeSrcRef.current = null;
    };
  }

  /* ── auto-scroll terminal ── */
  useEffect(() => { logEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [logs]);

  /* ── elapsed timer ── */
  useEffect(() => {
    if (!mining) return;
    startRef.current = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 1000);
    return () => clearInterval(id);
  }, [mining]);

  function addLog(level: LogLine["level"], msg: string) {
    const ts = new Date().toLocaleTimeString("en-US", { hour12: false });
    setLogs(prev => [...prev, { id: logId.current++, level, msg, ts }]);
  }

  /* ── sort toggle ── */
  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir(d => (d === -1 ? 1 : -1) as 1 | -1);
    else { setSortKey(key); setSortDir(-1); }
  }

  function SortTh({ k, label, accent = false }: { k: SortKey; label: string; accent?: boolean }) {
    const active = sortKey === k;
    return (
      <th
        onClick={() => toggleSort(k)}
        className={`px-3 py-3 text-right text-xs font-medium cursor-pointer select-none transition-colors
          ${active
            ? accent ? "text-[#006FFF]" : "text-gray-900"
            : "text-[#525461] hover:text-gray-700"}`}
      >
        {label} {active ? (sortDir === -1 ? "↓" : "↑") : ""}
      </th>
    );
  }

  /* ── derived: filtered + sorted factors ── */
  const starred = factors.filter(f => f.favorited).length;
  const visible = [...factors]
    .filter(f =>
      filter === "all"     ? true :
      filter === "passed"  ? !f.overfit :
      filter === "overfit" ? f.overfit :
      f.favorited
    )
    .sort((a, b) => sortDir * ((b[sortKey] ?? 0) - (a[sortKey] ?? 0)));

  const passed     = factors.filter(f => !f.overfit).length;
  const bestSharpe = factors.length ? Math.max(...factors.map(f => f.oos_sharpe_ratio)) : null;
  const bestPnlFactor = factors.length ? factors.reduce((a, b) => a.oos_total_return > b.oos_total_return ? a : b) : null;
  const bestPnl       = bestPnlFactor ? Math.round(bestPnlFactor.oos_total_return * 10000) : null;
  const bestPnlPct    = bestPnlFactor ? (bestPnlFactor.oos_total_return * 100).toFixed(1) : null;

  /* ── mining launcher ── */
  const launch = useCallback(() => {
    setDone(false);
    setElapsed(0);
    setMining(true);
    const src = new EventSource(`${API}/mining/stream?rounds=${rounds}`);
    sourceRef.current = src;
    src.onmessage = (e) => {
      const p = JSON.parse(e.data);
      if (p.type === "log") addLog(p.level ?? "info", p.msg);
      else if (p.type === "factor") {
        const f: FactorEntry = p.factor;
        setFactors(prev => [...prev.filter(x => x.id !== f.id), f]);
      }
      else if (p.type === "sentiment") setSentiment(p.data);
      else if (p.type === "ensemble")  setEnsemble(p.metrics);
      else if (p.type === "done") {
        addLog("success", p.msg);
        setMining(false);
        setDone(true);
        src.close();
        sourceRef.current = null;
      }
      else if (p.type === "error") addLog("error", p.msg ?? "未知错误");
    };
    src.onerror = () => {
      addLog("error", "SSE 连接中断。");
      setMining(false);
      src.close();
      sourceRef.current = null;
    };
  }, [rounds]);

  /* ── auto-loop ── */
  useEffect(() => {
    if (done && autoLoop && !mining) {
      addLog("info", "自动循环：准备下一轮挖矿...");
      const t = setTimeout(launch, 1500);
      return () => clearTimeout(t);
    }
  }, [done, autoLoop, mining, launch]);

  function handleMainBtn() {
    if (mining) {
      sourceRef.current?.close();
      sourceRef.current = null;
      setMining(false);
      addLog("error", "用户手动中止挖矿。");
    } else {
      setLogs([]);
      launch();
    }
  }

  async function toggleFavorite(e: React.MouseEvent, factorId: string) {
    e.stopPropagation(); // don't open the chart
    const res = await fetch(`${API}/factors/${factorId}/favorite`, { method: "POST" });
    if (!res.ok) return;
    const { favorited } = await res.json();
    setFactors(prev => prev.map(f => f.id === factorId ? { ...f, favorited } : f));
  }

  async function handleReset() {
    if (mining) return;
    sourceRef.current?.close();
    sourceRef.current = null;
    await fetch(`${API}/admin/reset`, { method: "POST" }).catch(() => {});
    // Reload leaderboard — favorited factors are preserved by the backend
    const kept = await fetch(`${API}/leaderboard`).then(r => r.json()).catch(() => []);
    setLogs([]);
    setFactors(kept);
    setSentiment(null);
    setEnsemble(null);
    setDone(false);
    setElapsed(0);
  }

  /* ────────────────────────────────────────────────────────────────
     RENDER
  ──────────────────────────────────────────────────────────────── */
  return (
    <div className="min-h-screen bg-[#F6F6F8] font-sans">

      {/* ── Top nav ── */}
      <header className="bg-[#006FFF] text-white px-6 py-0 flex items-center h-14 shadow-md">
        <div className="max-w-6xl w-full mx-auto flex items-center gap-4">
          <span className="font-bold text-base tracking-tight">QBTS Factor Miner</span>
          <span className="h-4 w-px bg-white/20" />
          <span className="text-xs text-blue-200">Autonomous AI Quant Lab · Walk-Forward OOS · IC/ICIR · Ensemble</span>
          <div className="ml-auto flex items-center gap-2 text-xs">
            {mining && (
              <span className="flex items-center gap-1.5 bg-white/10 rounded-full px-3 py-1">
                <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                LIVE · {fmtElapsed(elapsed)}
              </span>
            )}
          </div>
        </div>
      </header>

      <div className="max-w-6xl mx-auto px-6 py-6 space-y-5">

        {/* ── Stats bar ── */}
        {(mining || factors.length > 0) && (
          <div className="grid grid-cols-4 gap-4">
            {[
              { label: "已发现因子",    val: `${factors.length}`, unit: "个", blue: false },
              { label: "OOS 通过率",   val: factors.length ? `${((passed / factors.length) * 100).toFixed(0)}%` : "—", unit: "", blue: false },
              { label: "最佳 OOS 盈利 ($1w)", val: bestPnl !== null ? `${bestPnl >= 0 ? "+" : ""}$${bestPnl.toLocaleString()} (${bestPnl >= 0 ? "+" : ""}${bestPnlPct}%)` : "—", unit: "", blue: bestPnl !== null && bestPnl > 0 },
              { label: "运行时长",      val: fmtElapsed(elapsed), unit: "", blue: false, pulse: mining },
            ].map(({ label, val, unit, blue, pulse }) => (
              <Card key={label} className="px-5 py-4 text-center">
                <p className="text-xs text-[#525461] mb-1">{label}</p>
                <p className={`font-bold text-xl ${blue ? "text-[#006FFF]" : pulse ? "text-amber-500" : "text-gray-900"} ${pulse ? "animate-pulse" : ""}`}>
                  {val}{unit}
                </p>
              </Card>
            ))}
          </div>
        )}

        {/* ── Control panel ── */}
        <Card className="px-5 py-4">
          <div className="flex items-center gap-4 flex-wrap">
            {/* Rounds input */}
            <div className="flex items-center gap-2">
              <label className="text-sm text-[#525461]">挖矿轮数</label>
              <input
                type="number" min={1} max={50} value={rounds}
                onChange={e => setRounds(Math.max(1, Math.min(50, +e.target.value)))}
                disabled={mining}
                className="w-16 border border-[#EDEDF0] rounded-lg px-2.5 py-1.5 text-sm text-center
                           text-gray-900 bg-white focus:outline-none focus:ring-2 focus:ring-[#006FFF]/30
                           focus:border-[#006FFF] disabled:opacity-40 disabled:bg-gray-50 transition"
              />
              <span className="text-xs text-gray-400">/ 50</span>
            </div>

            {/* Auto-loop toggle */}
            <button
              onClick={() => setAutoLoop(v => !v)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-sm font-medium transition-all
                ${autoLoop
                  ? "border-amber-300 bg-amber-50 text-amber-700"
                  : "border-[#EDEDF0] bg-white text-[#525461] hover:border-gray-300 hover:text-gray-700"}`}
            >
              <span className={`w-2 h-2 rounded-full ${autoLoop ? "bg-amber-500 animate-pulse" : "bg-gray-300"}`} />
              自动循环 {autoLoop ? "ON" : "OFF"}
            </button>

            {/* Right-side buttons */}
            <div className="ml-auto flex items-center gap-2">
              {/* Reset button */}
              <button
                onClick={handleReset}
                disabled={mining}
                title="清空排行榜，重置所有状态"
                className="flex items-center gap-1.5 px-4 py-2.5 rounded-lg font-medium text-sm
                  border border-[#EDEDF0] bg-white text-[#525461] hover:text-[#F03A3E]
                  hover:border-red-200 hover:bg-red-50 transition-all disabled:opacity-40
                  disabled:cursor-not-allowed"
              >
                重置
              </button>

              {/* Main action button */}
              <button
                onClick={handleMainBtn}
                className={`flex items-center gap-2.5 px-8 py-2.5 rounded-lg font-semibold text-sm
                  text-white transition-all duration-200 shadow-sm
                  ${mining
                    ? "bg-[#F03A3E] hover:bg-red-500"
                    : done
                    ? "bg-emerald-600 hover:bg-emerald-700"
                    : "bg-[#006FFF] hover:bg-[#338CFF]"}`}
              >
                {mining && <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />}
                {mining ? "停止挖矿" : done ? "再次挖矿" : "启动全自动 AI 挖矿"}
              </button>
            </div>
          </div>
        </Card>

        {/* ── Sentiment ── */}
        {sentiment && (() => {
          const bull = sentiment.sentiment_label === "BULLISH";
          const bear = sentiment.sentiment_label === "BEARISH";
          return (
            <div className={`flex items-center gap-4 px-5 py-3 rounded-xl border text-sm
              ${bull ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                : bear ? "border-red-200 bg-red-50 text-red-800"
                : "border-[#EDEDF0] bg-white text-[#525461]"}`}>
              <span className="text-base">{bull ? "📈" : bear ? "📉" : "➡️"}</span>
              <span className="font-semibold">{sentiment.sentiment_label}</span>
              <span className="opacity-30">|</span>
              <span>多头 {(sentiment.bull_ratio * 100).toFixed(0)}%</span>
              <span className="opacity-30">|</span>
              <span>{sentiment.message_count} 条消息</span>
              <span className="opacity-30">|</span>
              <span>{typeof sentiment.watchers === "number" ? sentiment.watchers.toLocaleString() : sentiment.watchers} 关注</span>
              <span className="ml-auto text-xs opacity-40">StockTwits · {sentiment.fetched_at}</span>
            </div>
          );
        })()}

        {/* ── Terminal ── */}
        {(logs.length > 0 || mining) && (
          <Card className="overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-2.5 bg-[#1a1a1e] border-b border-white/5">
              <span className="w-3 h-3 rounded-full bg-[#F03A3E]" />
              <span className="w-3 h-3 rounded-full bg-amber-400" />
              <span className="w-3 h-3 rounded-full bg-emerald-500" />
              <span className="ml-2 text-xs text-gray-500 font-mono">qbts-miner — activity log</span>
              {mining && (
                <span className="ml-auto flex items-center gap-1.5 text-xs text-amber-400 font-mono">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                  LIVE · {fmtElapsed(elapsed)}
                </span>
              )}
            </div>
            <div className="bg-[#0f0f12] h-60 overflow-y-auto p-4 space-y-0.5 font-mono text-xs">
              {logs.map(line => (
                <div key={line.id} className="flex gap-3 leading-5">
                  <span className="shrink-0 text-gray-600 w-16">{line.ts}</span>
                  <span className={`shrink-0 ${logColor[line.level]}`}>{logPrefix[line.level]}</span>
                  <span className={logColor[line.level]}>{line.msg}</span>
                </div>
              ))}
              {mining && (
                <div className="flex gap-3 leading-5">
                  <span className="w-16" />
                  <span className="text-[#006FFF] animate-pulse">▌</span>
                </div>
              )}
              <div ref={logEndRef} />
            </div>
          </Card>
        )}

        {/* ── Phase 4: Today's Signals (live aggregate) ── */}
        <TodaySignalsPanel />

        {/* ── Leaderboard ── */}
        <Card className="overflow-hidden">
          <CardHeader
            right={
              <>
                <span className="text-xs text-gray-400">点列头排序</span>
                {factors.length > 0 && (
                  <button
                    onClick={() => exportCSV(factors)}
                    className="text-xs text-[#525461] hover:text-gray-900 border border-[#EDEDF0]
                               hover:border-gray-300 rounded-lg px-3 py-1.5 transition-colors bg-white"
                  >
                    导出 CSV
                  </button>
                )}
              </>
            }
          >
            <div className="flex items-center gap-1">
              {([
                { key: "all",     label: `全部 ${factors.length}` },
                { key: "passed",  label: `通过 ${passed}` },
                { key: "overfit", label: `过拟合 ${factors.length - passed}` },
                { key: "starred", label: `★ 收藏 ${starred}` },
              ] as { key: FilterTab; label: string }[]).map(({ key, label }) => (
                <button
                  key={key}
                  onClick={() => setFilter(key)}
                  className={`px-3 py-1 rounded-md text-xs font-medium transition-colors
                    ${filter === key
                      ? key === "starred"
                        ? "bg-amber-400 text-white"
                        : "bg-[#006FFF] text-white"
                      : "text-[#525461] hover:text-gray-900 hover:bg-[#F6F6F8]"}`}
                >
                  {label}
                </button>
              ))}
            </div>
          </CardHeader>

          {visible.length === 0 ? (
            <div className="py-16 text-center text-[#525461] text-sm">
              {factors.length === 0 ? "暂无因子 — 点击「启动全自动 AI 挖矿」开始" : "当前筛选无结果"}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-[#EDEDF0] bg-[#F6F6F8]">
                    <th className="px-3 py-3 text-center text-xs font-medium text-[#525461]">★</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-[#525461]">#</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-[#525461]">因子名称</th>
                    <th className="px-3 py-3 text-center text-xs font-medium text-[#525461]">周期</th>
                    <th className="px-3 py-3 text-right text-xs font-medium text-gray-400">IS Sharpe</th>
                    <th className="px-3 py-3 text-right text-xs font-medium text-[#525461]">止损/单日最大亏</th>
                    <th className="px-1 py-3 text-center text-gray-300">→</th>
                    <SortTh k="oos_sharpe_ratio" label="OOS Sharpe" accent />
                    <SortTh k="oos_win_rate"      label="OOS 胜率/次数"   accent />
                    <SortTh k="oos_total_return"  label="OOS 盈利 ($1w)"  accent />
                    <SortTh k="oos_max_drawdown"  label="OOS 回撤"        accent />
                    <SortTh k="q_hit_rate"       label="命中率/信号" accent />
                    <th className="px-3 py-3 text-right text-xs font-medium text-[#525461]">IC 衰减</th>
                    <SortTh k="score" label="评分" accent />
                  </tr>
                </thead>
                <tbody>
                  {visible.map((f, idx) => (
                    <tr
                      key={f.id}
                      onClick={() => setChartFactor(chartFactor?.id === f.id ? null : { id: f.id, name: f.name })}
                      className={`border-t transition-colors cursor-pointer
                        ${chartFactor?.id === f.id
                          ? "bg-blue-50 border-blue-100"
                          : f.overfit
                          ? "border-red-100 bg-red-50/50 hover:bg-red-50"
                          : "border-[#EDEDF0] hover:bg-[#F6F6F8]"}`}
                    >
                      <td className="px-3 py-3 text-center">
                        <button
                          onClick={ev => toggleFavorite(ev, f.id)}
                          className={`text-base leading-none transition-colors
                            ${f.favorited ? "text-amber-400 hover:text-amber-300" : "text-gray-300 hover:text-amber-400"}`}
                          title={f.favorited ? "取消收藏" : "收藏"}
                        >
                          {f.favorited ? "★" : "☆"}
                        </button>
                      </td>
                      <td className="px-4 py-3 text-gray-400 font-medium">{idx + 1}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2.5">
                          <span className={`shrink-0 w-2 h-2 rounded-full ${f.overfit ? "bg-[#F03A3E]" : "bg-emerald-500"}`} />
                          <div>
                            <div className="flex items-center gap-1.5">
                              <p className="text-gray-900 font-medium truncate max-w-[180px]">{f.name}</p>
                              {f.type === "ml" && (
                                <span title="LightGBM ML 因子"
                                      className="shrink-0 px-1.5 py-0.5 text-[10px] font-bold tracking-wider rounded
                                                 bg-violet-100 text-violet-700 border border-violet-200">
                                  ML
                                </span>
                              )}
                              {f.type === "rule" && (
                                <span title="if-then 规则因子"
                                      className="shrink-0 px-1.5 py-0.5 text-[10px] font-bold tracking-wider rounded
                                                 bg-slate-100 text-slate-600 border border-slate-200">
                                  规则
                                </span>
                              )}
                            </div>
                            <p className="text-[#525461] truncate max-w-[180px] mt-0.5 text-xs">{f.description}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-3 text-center">
                        <span className="text-[#525461] bg-[#F6F6F8] border border-[#EDEDF0] px-2 py-0.5 rounded-md text-xs font-mono">
                          {f.freq}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-right font-mono text-gray-400">{fmt(f.is_sharpe)}</td>
                      <td className="px-3 py-3 text-right">
                        {(() => {
                          const nStops = f.oos_n_stops;
                          const worst  = f.oos_worst_bar_loss;
                          if (nStops === undefined || worst === undefined) {
                            return <span className="text-gray-300 font-mono text-xs">—</span>;
                          }
                          const ratio  = (f.oos_n_trades ?? 0) > 0 ? nStops / (f.oos_n_trades ?? 1) : 0;
                          const stopColor = ratio <= 0.15 ? "text-emerald-600"
                                          : ratio <= 0.30 ? "text-amber-500" : "text-[#F03A3E]";
                          const lossColor = worst >= -0.04 ? "text-emerald-600"
                                          : worst >= -0.07 ? "text-amber-500" : "text-[#F03A3E]";
                          return (
                            <div className="flex flex-col items-end gap-0.5">
                              <span className={`font-mono ${stopColor}`}>{nStops}次</span>
                              <span className={`font-mono text-xs ${lossColor}`}>{(worst * 100).toFixed(1)}%</span>
                            </div>
                          );
                        })()}
                      </td>
                      <td className="px-1 py-3 text-center text-gray-300">›</td>
                      <td className="px-3 py-3 text-right">
                        <span className={`font-mono font-semibold
                          ${f.oos_sharpe_ratio > 0.5 ? "text-emerald-600"
                            : f.oos_sharpe_ratio > 0 ? "text-amber-500" : "text-[#F03A3E]"}`}>
                          {fmt(f.oos_sharpe_ratio)}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-right">
                        <div className="flex flex-col items-end gap-0.5">
                          <WinBadge v={f.oos_win_rate} />
                          <span className={`font-mono text-xs ${
                            (f.oos_n_trades ?? 0) >= 10 ? "text-[#525461]"
                            : "text-[#F03A3E]"
                          }`}>{f.oos_n_trades ?? 0}笔</span>
                        </div>
                      </td>
                      <td className="px-3 py-3 text-right">
                        {(() => {
                          const pnl = Math.round(f.oos_total_return * 10000);
                          const pct = (f.oos_total_return * 100).toFixed(1);
                          const pos = pnl >= 0;
                          const color = pos ? "text-emerald-600" : "text-[#F03A3E]";
                          return (
                            <div className="flex flex-col items-end gap-0.5">
                              <span className={`font-mono font-semibold ${color}`}>
                                {pos ? "+" : ""}${pnl.toLocaleString()}
                              </span>
                              <span className={`font-mono text-xs ${color} opacity-75`}>
                                {pos ? "+" : ""}{pct}%
                              </span>
                            </div>
                          );
                        })()}
                      </td>
                      <td className="px-3 py-3 text-right"><DDBadge v={f.oos_max_drawdown} /></td>
                      <td className="px-3 py-3 text-right">
                        {(() => {
                          const hr = f.q_hit_rate;
                          const ns = f.q_n_signals;
                          if (hr === undefined) {
                            // Backwards-compat: show old ICIR for pre-Phase-2 entries
                            return (
                              <span className={`font-mono font-semibold
                                ${(f.q_icir ?? 0) > 0.5 ? "text-[#006FFF]"
                                  : (f.q_icir ?? 0) > 0 ? "text-[#525461]" : "text-[#F03A3E]"}`}>
                                {fmt(f.q_icir ?? 0)}
                              </span>
                            );
                          }
                          const hrColor = hr >= 0.55 ? "text-emerald-600"
                                        : hr >= 0.52 ? "text-amber-500" : "text-[#F03A3E]";
                          const nsColor = (ns ?? 0) >= 30 ? "text-[#525461]" : "text-[#F03A3E]";
                          return (
                            <div className="flex flex-col items-end gap-0.5">
                              <span className={`font-mono font-semibold ${hrColor}`}>
                                {(hr * 100).toFixed(1)}%
                              </span>
                              <span className={`font-mono text-xs ${nsColor}`}>{ns ?? 0}信号</span>
                            </div>
                          );
                        })()}
                      </td>
                      <td className="px-3 py-3 text-right">
                        {f.ic_decay ? <IcSparkline decay={f.ic_decay} /> : <span className="text-gray-300">—</span>}
                      </td>
                      <td className="px-3 py-3 text-right">
                        <span className="text-[#006FFF] font-semibold font-mono">{fmt(f.score)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* ── inline chart panel ── */}
          {chartFactor && (
            <FactorChart
              factorId={chartFactor.id}
              factorName={chartFactor.name}
              onClose={() => setChartFactor(null)}
            />
          )}
        </Card>

        {/* ── Ensemble card ── */}
        {ensemble && (
          <Card className="overflow-hidden">
            <CardHeader
              right={
                <span className="text-xs text-[#525461]">
                  {ensemble.kept_count} 正交因子合并 · {ensemble.dropped_count} 相关因子已过滤
                </span>
              }
            >
              组合因子 Ensemble — OOS 盲测结果
            </CardHeader>
            <div className="p-5 grid grid-cols-4 gap-4">
              {[
                { label: "OOS Sharpe",   v: fmt(ensemble.ens_sharpe_ratio),       good: ensemble.ens_sharpe_ratio > 0.5 },
                { label: "OOS 胜率",     v: fmt(ensemble.ens_win_rate, true),      good: ensemble.ens_win_rate > 0.5 },
                { label: "OOS 最大回撤", v: fmt(ensemble.ens_max_drawdown, true),  good: ensemble.ens_max_drawdown > -0.3 },
                { label: "OOS 总收益",   v: fmt(ensemble.ens_total_return, true),  good: ensemble.ens_total_return > 0 },
              ].map(({ label, v, good }) => (
                <div key={label} className="bg-[#F6F6F8] rounded-lg px-4 py-4 text-center border border-[#EDEDF0]">
                  <p className="text-xs text-[#525461] mb-1.5">{label}</p>
                  <p className={`font-mono font-bold text-xl ${good ? "text-[#006FFF]" : "text-[#F03A3E]"}`}>{v}</p>
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* ── Trading Console ── */}
        {trading && (
          <Card className="overflow-hidden">
            <CardHeader
              right={
                <div className="flex items-center gap-2">
                  {trading.configured && (
                    <button
                      onClick={fetchTradingStatus}
                      className="text-xs text-[#525461] hover:text-gray-900 border border-[#EDEDF0]
                                 hover:border-gray-300 rounded-lg px-3 py-1.5 transition-colors bg-white"
                    >
                      刷新
                    </button>
                  )}
                  <span className={`text-xs px-2.5 py-1 rounded-full font-medium border
                    ${trading.configured
                      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                      : "bg-red-50 text-[#F03A3E] border-red-200"}`}>
                    {trading.configured ? "已连接 Alpaca" : "未配置"}
                  </span>
                </div>
              }
            >
              Alpaca Paper Trading
            </CardHeader>

            {/* not configured */}
            {!trading.configured && (
              <div className="p-6 space-y-4">
                <p className="text-sm text-gray-700">
                  Alpaca Paper Trading 未配置。在项目根目录 <code className="bg-[#F6F6F8] border border-[#EDEDF0] px-1.5 py-0.5 rounded text-xs font-mono">.env</code> 中添加：
                </p>
                <pre className="bg-[#0f0f12] text-emerald-400 rounded-xl p-4 text-xs font-mono leading-6 overflow-x-auto">
{`ALPACA_API_KEY=your_paper_api_key
ALPACA_SECRET_KEY=your_paper_secret_key`}
                </pre>
                <p className="text-xs text-[#525461]">
                  前往 <span className="text-[#006FFF] font-medium">alpaca.markets</span> 注册免费账户，切换到 Paper Trading 后生成 API Key。
                </p>
              </div>
            )}

            {/* configured */}
            {trading.configured && (
              <div className="p-5 space-y-4">

                {/* account bar */}
                {trading.account && (
                  <div className="grid grid-cols-4 gap-4">
                    {[
                      { label: "投资组合价值", val: `$${trading.account.portfolio_value.toLocaleString("en-US", { minimumFractionDigits: 2 })}`, highlight: false },
                      { label: "可用现金",     val: `$${trading.account.cash.toLocaleString("en-US", { minimumFractionDigits: 2 })}`,            highlight: false },
                      {
                        label: "今日 P&L",
                        val: `${trading.account.daily_pnl >= 0 ? "+" : ""}$${trading.account.daily_pnl.toFixed(2)}`,
                        sub: `${trading.account.daily_pnl_pct >= 0 ? "+" : ""}${trading.account.daily_pnl_pct.toFixed(2)}%`,
                        good: trading.account.daily_pnl >= 0,
                        pnl: true,
                        highlight: false,
                      },
                      { label: "购买力", val: `$${trading.account.buying_power.toLocaleString("en-US", { minimumFractionDigits: 2 })}`, highlight: false },
                    ].map(({ label, val, sub, good, pnl }) => (
                      <div key={label} className="bg-[#F6F6F8] border border-[#EDEDF0] rounded-xl px-4 py-4 text-center">
                        <p className="text-xs text-[#525461] mb-1">{label}</p>
                        <p className={`font-semibold text-base font-mono
                          ${pnl ? (good ? "text-emerald-600" : "text-[#F03A3E]") : "text-gray-900"}`}>
                          {val}
                        </p>
                        {sub && (
                          <p className={`text-xs font-mono mt-0.5 ${good ? "text-emerald-500" : "text-[#F03A3E]"}`}>{sub}</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {/* position + signal */}
                <div className="grid grid-cols-2 gap-4">
                  {/* position */}
                  <div className="border border-[#EDEDF0] rounded-xl p-4 bg-white space-y-2.5">
                    <p className="text-xs font-semibold text-[#525461] uppercase tracking-wider">当前持仓 · QBTS</p>
                    {trading.position ? (
                      <div className="space-y-2">
                        {[
                          { k: "数量",     v: `${trading.position.qty.toFixed(0)} 股` },
                          { k: "持仓方向", v: trading.position.side.toUpperCase(),
                            color: trading.position.side === "long" ? "text-emerald-600" : "text-[#525461]" },
                          { k: "均价",     v: `$${trading.position.avg_entry_price}` },
                          { k: "现价",     v: `$${trading.position.current_price}` },
                        ].map(({ k, v, color }) => (
                          <div key={k} className="flex justify-between items-center text-sm">
                            <span className="text-[#525461]">{k}</span>
                            <span className={`font-mono font-medium ${color ?? "text-gray-900"}`}>{v}</span>
                          </div>
                        ))}
                        <div className="flex justify-between items-center text-sm pt-2 border-t border-[#EDEDF0]">
                          <span className="text-[#525461]">浮动盈亏</span>
                          <div className="text-right">
                            <p className={`font-mono font-semibold ${trading.position.unrealized_pl >= 0 ? "text-emerald-600" : "text-[#F03A3E]"}`}>
                              {trading.position.unrealized_pl >= 0 ? "+" : ""}${trading.position.unrealized_pl.toFixed(2)}
                            </p>
                            <p className={`text-xs font-mono ${trading.position.unrealized_plpc >= 0 ? "text-emerald-500" : "text-[#F03A3E]"}`}>
                              {trading.position.unrealized_plpc >= 0 ? "+" : ""}{trading.position.unrealized_plpc.toFixed(2)}%
                            </p>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="py-6 text-center text-[#525461] text-sm">空仓</div>
                    )}
                  </div>

                  {/* signal + execute */}
                  <div className="border border-[#EDEDF0] rounded-xl p-4 bg-white space-y-3">
                    <p className="text-xs font-semibold text-[#525461] uppercase tracking-wider">最佳因子信号</p>
                    {trading.signal ? (
                      <>
                        <div className="flex justify-center py-3">
                          <span className={`text-2xl font-black px-8 py-3 rounded-xl
                            ${trading.signal.label === "BUY"  ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                              : trading.signal.label === "SELL" ? "bg-red-50 text-[#F03A3E] border border-red-200"
                              : "bg-[#F6F6F8] text-[#525461] border border-[#EDEDF0]"}`}>
                            {trading.signal.label === "BUY" ? "▲" : trading.signal.label === "SELL" ? "▼" : "—"} {trading.signal.label}
                          </span>
                        </div>
                        {[
                          { k: "因子",    v: trading.signal.factor_name, mono: false },
                          { k: "OOS评分", v: trading.signal.factor_score.toFixed(3), mono: true, blue: true },
                          { k: "周期",    v: trading.signal.freq, mono: true },
                        ].map(({ k, v, mono, blue }) => (
                          <div key={k} className="flex justify-between items-center text-sm">
                            <span className="text-[#525461]">{k}</span>
                            <span className={`${mono ? "font-mono" : ""} ${blue ? "text-[#006FFF] font-semibold" : "text-gray-900"} truncate max-w-[180px] text-right`}>{v}</span>
                          </div>
                        ))}
                      </>
                    ) : (
                      <div className="py-6 text-center text-[#525461] text-sm">先挖矿生成因子</div>
                    )}

                    <button
                      onClick={executeSignal}
                      disabled={tradeExecuting || !trading.signal}
                      className={`w-full py-2.5 rounded-lg font-semibold text-sm transition-all duration-200
                        ${tradeExecuting
                          ? "bg-amber-50 text-amber-700 border border-amber-200 cursor-wait"
                          : !trading.signal
                          ? "bg-[#F6F6F8] text-gray-400 border border-[#EDEDF0] cursor-not-allowed"
                          : "bg-[#006FFF] hover:bg-[#338CFF] text-white shadow-sm"}`}
                    >
                      {tradeExecuting
                        ? <span className="flex items-center justify-center gap-2">
                            <span className="w-3.5 h-3.5 border-2 border-amber-400/40 border-t-amber-500 rounded-full animate-spin" />
                            执行中...
                          </span>
                        : "执行信号下单"}
                    </button>
                  </div>
                </div>

                {/* execution log */}
                {tradeLogs.length > 0 && (
                  <div className="rounded-xl overflow-hidden border border-[#EDEDF0]">
                    <div className="px-4 py-2.5 bg-[#1a1a1e] border-b border-white/5 text-xs text-gray-500 font-mono flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#006FFF]" />
                      执行日志
                      {tradeExecuting && <span className="ml-auto text-amber-400 animate-pulse">● LIVE</span>}
                    </div>
                    <div className="bg-[#0f0f12] max-h-40 overflow-y-auto p-4 space-y-0.5 font-mono text-xs">
                      {tradeLogs.map(line => (
                        <div key={line.id} className="flex gap-3 leading-5">
                          <span className="shrink-0 text-gray-600 w-16">{line.ts}</span>
                          <span className={`shrink-0 ${logColor[line.level]}`}>{logPrefix[line.level]}</span>
                          <span className={logColor[line.level]}>{line.msg}</span>
                        </div>
                      ))}
                      {tradeExecuting && (
                        <div className="flex gap-3 leading-5">
                          <span className="w-16" />
                          <span className="text-[#006FFF] animate-pulse">▌</span>
                        </div>
                      )}
                      <div ref={tradeLogEnd} />
                    </div>
                  </div>
                )}

                {/* recent orders */}
                {trading.orders && trading.orders.length > 0 && (
                  <div className="rounded-xl overflow-hidden border border-[#EDEDF0]">
                    <div className="px-5 py-3 bg-[#F6F6F8] border-b border-[#EDEDF0] text-xs font-semibold text-[#525461] uppercase tracking-wider">
                      最近委托
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-[#EDEDF0]">
                            {["时间", "方向", "数量", "成交量", "成交价", "状态"].map((h, i) => (
                              <th key={h} className={`px-4 py-2.5 text-xs font-medium text-[#525461]
                                ${i === 0 ? "text-left" : i === 1 ? "text-center" : "text-right"}`}>
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {trading.orders.map(o => (
                            <tr key={o.id} className="border-t border-[#EDEDF0] hover:bg-[#F6F6F8] transition-colors">
                              <td className="px-4 py-3 text-[#525461] text-xs">{o.created_at}</td>
                              <td className="px-4 py-3 text-center">
                                <span className={`font-semibold text-xs px-2 py-0.5 rounded-md
                                  ${o.side === "BUY"
                                    ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                                    : "bg-red-50 text-[#F03A3E] border border-red-200"}`}>
                                  {o.side}
                                </span>
                              </td>
                              <td className="px-4 py-3 text-right font-mono text-gray-900">{o.qty.toFixed(0)}</td>
                              <td className="px-4 py-3 text-right font-mono text-[#525461]">{o.filled_qty.toFixed(0)}</td>
                              <td className="px-4 py-3 text-right font-mono text-gray-900">
                                {o.filled_avg_price > 0 ? `$${o.filled_avg_price}` : "—"}
                              </td>
                              <td className="px-4 py-3 text-right">
                                <span className={`text-xs px-2 py-0.5 rounded-md font-medium
                                  ${o.status === "filled"   ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                                    : o.status === "canceled" ? "bg-[#F6F6F8] text-[#525461] border border-[#EDEDF0]"
                                    : "bg-amber-50 text-amber-700 border border-amber-200"}`}>
                                  {o.status}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

              </div>
            )}
          </Card>
        )}

        {/* footer */}
        <div className="text-center text-xs text-gray-400 pb-4">
          QBTS Factor Miner · Walk-Forward OOS Validation · IC/ICIR · Factor Ensemble
        </div>

      </div>
    </div>
  );
}
