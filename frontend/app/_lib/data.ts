/**
 * Read-only data access for the deployed dashboard.
 *
 * Everything here reads from Supabase (populated by local `publish.py`). The
 * shapes are byte-for-byte the same JSON the FastAPI backend used to return,
 * so the rendering components are unchanged — only the data source moved.
 */
import { supabase } from "./supabase";

/* ── /dashboard/snapshot payload ─────────────────────────────────────────── */
export interface StrategySignal {
  name:        string;
  category:    string;
  signal:      -1 | 0 | 1;
  label:       "BUY" | "SELL" | "HOLD";
  confidence:  "low" | "medium" | "high";
  rationale:   string;
  references:  string[];
  metric_snapshot: Record<string, number | boolean | string>;
}

export interface NewsItem {
  title:     string;
  publisher: string;
  published: string;
  url:       string;
  summary:   string;
  ticker:    string;
  ai: {
    sentiment: "bullish" | "bearish" | "neutral";
    impact:    "high" | "medium" | "low";
    horizon:   string;
    reasoning: string;
  };
}

export interface Snapshot {
  as_of:        string;
  price:        number;
  today_change: number;
  strategies:   StrategySignal[];
  strategy_consensus: {
    label: "BUY" | "SELL" | "HOLD"; raw_score: number;
    n_buy: number; n_sell: number; n_hold: number; n_total: number;
  };
  news: {
    as_of: string | null;
    items: NewsItem[];
    aggregate: { label: string; signal: number; score: number;
      n_bull: number; n_bear: number; n_neutral: number; n_items: number };
  };
  verdict: {
    signal: -1 | 0 | 1;
    label:  "BUY" | "SELL" | "HOLD";
    score:  number;
  };
  chart: {
    candles:  { time: number; open: number; high: number; low: number; close: number }[];
    sma20:    { time: number; value: number }[];
    sma200:   { time: number; value: number }[];
    high_52w: number;
    low_52w:  number;
    atr_14:   number;
  };
  etf_prices: { qbtx: number | null; qbtz: number | null };
  brief:                string | null;
  brief_generated_at:   string | null;
  edge?: {
    signal:              -1 | 0 | 1;
    label:               "BUY" | "SELL" | "HOLD";
    p_up:                number;
    expected_return_pct: number;
    kelly_fraction:      number;
    log_odds:            number;
    n_signals:           number;
    contributions: Array<{
      source: string;
      kind:   "mined" | "classic" | "news";
      signal: -1 | 0 | 1;
      weight: number;
      log_odds: number;
      detail: string;
    }>;
    error?: string;
  };
  sources_status?: Record<string, {
    status:    "active" | "neutral" | "needs_setup" | "error";
    label:     string;
    rationale?: string;
  }>;
  decision?: Decision | null;
  decision_generated_at?: string | null;
  macro?: {
    as_of:       string;
    events:      MacroEvent[];
    nuclear:     MacroEvent[];
    risk_window: boolean;
    risk_note:   string;
  } | null;
}

export interface MacroEvent {
  date:     string;
  time_et:  string;
  title:    string;
  impact:   "High" | "Medium";
  forecast: string;
  previous: string;
  nuclear:  boolean;
}

/* ── AI trade decision (the user-facing verdict) ─────────────────────────── */
export interface DecisionDriver {
  name:      string;
  direction: "bullish" | "bearish";
  strength:  "强" | "中" | "弱";
  note:      string;
}
export interface DecisionCatalyst {
  date:   string;
  event:  string;
  impact: "高" | "中" | "低";
  note:   string;
}
export interface Decision {
  action:     "LONG_QBTX" | "SHORT_QBTZ" | "HOLD";
  conviction: number;          // 0-10
  p_up_5d:    number;          // 0-1
  summary:    string;
  trade_plan: {
    qbts_entry:  number;
    qbts_stop:   number;
    qbts_target: number;
    etf_ticker:  "QBTX" | "QBTZ" | null;
    etf_entry:   number | null;
    etf_stop:    number | null;
    etf_target:  number | null;
    rr_ratio:    number;
    suggested_position_pct: number;
    entry_condition: string;
  };
  key_drivers:        DecisionDriver[];
  risks:              string[];
  upcoming_catalysts: DecisionCatalyst[];
  invalidation:       string;
}

/* ── /dashboard/calibration payload ──────────────────────────────────────── */
export interface CalibrationBucket {
  predicted_p_up:    number;
  realized_hit_rate: number;
  n:                 number;
}
export interface SourceCal {
  n:           number;
  hits:        number;
  hit_rate:    number;
  weight_mult: number;
}
export interface Calibration {
  n_total:          number;
  n_graded:         number;
  overall_hit_rate: number;
  calibration:      CalibrationBucket[];
  by_source:        Record<string, SourceCal>;
}

/* ── factor row (factors table) ──────────────────────────────────────────── */
export interface FactorEntry {
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
  oos_n_stops?: number;
  oos_worst_bar_loss?: number;
  q_ic_mean: number;
  q_icir: number;
  q_hit_rate?: number;
  q_n_signals?: number;
  q_ic_pvalue?: number;
  type?: "ml" | "rule";
  q_positive_ic_ratio: number;
  ic_decay: Record<string, number>;
  score: number;
}

export interface ChartData {
  factor_name: string;
  freq: string;
  ohlcv: { time: number; open: number; high: number; low: number; close: number }[];
  markers: { time: number; signal: number }[];
  split_time: number;
}

export interface FactorRow {
  id:    string;
  score: number | null;
  data:  FactorEntry;
  code:  string | null;
  chart: ChartData | null;
}

const NO_DATA = "尚无发布数据 — 请先在本地运行 publish.py";

/** True when Supabase is actually configured (deployed mode).
 *  When false (local dev without Supabase), fall back to the local FastAPI
 *  backend directly — zero-config `npm run dev` + `uvicorn` workflow. */
const SUPABASE_CONFIGURED = !!process.env.NEXT_PUBLIC_SUPABASE_URL;

import { API } from "./api";

/** Latest published dashboard snapshot. */
export async function getSnapshot(): Promise<Snapshot> {
  if (!SUPABASE_CONFIGURED) {
    const r = await fetch(`${API}/dashboard/snapshot`);
    if (!r.ok) throw new Error(`本地后端 HTTP ${r.status} — 确认 uvicorn 已在 8000 端口启动`);
    return (await r.json()) as Snapshot;
  }
  const { data, error } = await supabase
    .from("dashboard_state")
    .select("snapshot")
    .order("published_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw new Error(error.message);
  if (!data) throw new Error(NO_DATA);
  return data.snapshot as Snapshot;
}

/** Latest published calibration (may be null if it failed to compute). */
export async function getCalibration(): Promise<Calibration | null> {
  const { data, error } = await supabase
    .from("dashboard_state")
    .select("calibration")
    .order("published_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return (data?.calibration ?? null) as Calibration | null;
}

/** All published factors, best score first. */
export async function getFactors(): Promise<FactorRow[]> {
  const { data, error } = await supabase
    .from("factors")
    .select("id, score, data, code, chart")
    .order("score", { ascending: false });
  if (error) throw new Error(error.message);
  return (data ?? []) as FactorRow[];
}
