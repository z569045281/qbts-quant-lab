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
  smc?: SmcAnalysis | null;
  volume_profile?:    VolumeProfile | null;
  regime?:            VolatilityRegime | null;
  nw_envelope?:       NwEnvelope | null;
  squeeze?:           SqueezeFuel | null;
  relative_strength?: RelativeStrength | null;
  journal?: DecisionJournal | null;
}

/* ── SMC (smart money concepts) structural read ─────────────────────────── */
export interface SmcZone {
  kind: "FVG" | "OB";
  type: "bullish" | "bearish";
  low:  number;
  high: number;
  date: string;
}
export interface SmcChecklistItem {
  key: string;
  label: string;
  ok: boolean;
  detail: string;
}
export interface SmcPlaybook {
  lock: "bull" | "bear" | "none";
  lock_reason: string;
  bias_note: string;
  state: "TRIGGER" | "ARMED" | "WAIT" | "NO_LOCK";
  state_cn: string;
  action: "buy" | "sell" | "wait";
  side_cn: string;
  equilibrium: number;
  discount_premium: "discount" | "premium";
  range_position: number;
  entry_zone: { low: number; high: number; basis: string } | null;
  stop: number | null;
  tp1: { price: number; basis: string } | null;
  tp2: { price: number; basis: string } | null;
  rr: number | null;
  rr_veto?: boolean;
  risk_note?: string | null;
  relay_ob: (SmcZone & { tf: string }) | null;
  relay_obs: (SmcZone & { tf: string })[];
  checklist: SmcChecklistItem[];
  conditions_met: string;
}
export interface SmcAnalysis {
  signal: -1 | 0 | 1;
  label:  "BUY" | "SELL" | "HOLD";
  trend:  "bullish" | "bearish" | "neutral";
  last_event: { date: string; kind: "BOS" | "CHoCH"; dir: "bullish" | "bearish"; level: number } | null;
  zone:   string;
  range_position: number;
  range:  { high: number; low: number };
  demand_zones: SmcZone[];
  supply_zones: SmcZone[];
  sweeps: { dir: "bullish" | "bearish"; level: number; date: string; note: string }[];
  rationale: string;
  price_used: number;
  ltf?: { trend: "bullish" | "bearish" | "neutral"; last_event: SmcAnalysis["last_event"] } | null;
  confluence?: "aligned" | "conflict" | "neutral";
  playbook?: SmcPlaybook | null;
}

/* ── volume profile / POC ────────────────────────────────────────────────── */
export interface VolumeProfile {
  signal: -1 | 0 | 1;
  label:  "BUY" | "SELL" | "HOLD";
  poc:    number;
  vah:    number;
  val:    number;
  price:  number;
  price_vs_value: "above" | "inside" | "below";
  hvn: number[];
  lvn: number[];
  naked_pocs_above: number[];
  naked_pocs_below: number[];
  nearest_magnet_up:   number | null;
  nearest_magnet_down: number | null;
  lookback_days: number;
  stance:        "观望" | "偏多" | "偏空";
  action_hint:   string;
  rationale: string;
  note: string;
}

/* ── volatility regime ───────────────────────────────────────────────────── */
export interface VolatilityRegime {
  regime: "expansion" | "contraction" | "normal";
  atr_pct?: number;
  atr_pct_percentile?: number;
  realized_vol_20d?: number;
  gap_mean_60d?: number;
  gap_gt5_pct?: number;
  stop_hint?: string;
  rationale: string;
}

/* ── Nadaraya-Watson envelope (non-repainting mean-reversion band) ────────── */
export interface NwBand {
  time: number; upper: number; lower: number;
  buy_line: number; sell_line: number; nw: number;
}
export interface NwEnvelope {
  active:       boolean;
  signal:       -1 | 0 | 1;
  stance?:      "near_lower" | "inside" | "near_upper";
  nw?:          number;
  upper?:       number;
  lower?:       number;
  buy_line?:    number;
  sell_line?:   number;
  position?:    number;
  position_pct?: number;
  slope?:       "up" | "down" | "flat";
  crossed_in?:  boolean;
  crossed_out?: boolean;
  broke_upper?: boolean;
  level?:       number;
  bands?:       NwBand[];
  note?:        string;
  rationale:    string;
}

/* ── squeeze fuel composite ──────────────────────────────────────────────── */
export interface SqueezeFuel {
  signal: 0 | 1;
  label:  "BUY" | "HOLD";
  fuel_score: number;
  fuel_label: "高" | "中" | "低";
  components: { short: number; options: number; holdings: number };
  short_ratio: number;
  short_pressure_z: number | null;
  rationale: string;
}

/* ── relative strength vs peer basket ────────────────────────────────────── */
export interface RelativeStrength {
  signal: -1 | 0 | 1;
  label:  "BUY" | "SELL" | "HOLD";
  leadership: "leader" | "laggard" | "decoupled" | "inline";
  rel:        { "1d": number; "5d": number; "20d": number };
  qbts_ret:   { "1d": number; "5d": number; "20d": number };
  basket_ret: { "1d": number; "5d": number; "20d": number };
  beta_20d:   number | null;
  vix:        number | null;
  vix_chg_5d: number;
  risk:       "on" | "off" | "neutral";
  rationale:  string;
}

/* ── decision journal (past calls, graded) ──────────────────────────────── */
export interface JournalRecord {
  id:         string;
  date:       string;
  action:     "LONG_QBTX" | "SHORT_QBTZ" | "HOLD";
  conviction: number;
  p_up_5d:    number;
  price:      number;
  entry:      number | null;
  stop:       number | null;
  target:     number | null;
  summary:    string;
  status:     "pending" | "graded";
  result: {
    graded_at:  string;
    outcome:    "target_hit" | "stop_hit" | "drift" | "hold";
    correct:    boolean | null;
    ret_pct:    number | null;
    exit_day:   number | null;
    reflection: string | null;
    shadow_dir?:     -1 | 1 | null;   // HOLD: lean implied by p_up_5d
    shadow_correct?: boolean | null;  // HOLD: was that lean directionally right
  } | null;
}
export interface JournalPaper {
  trade_usd: number;
  realized:  number;
  n_trades:  number;
  n_win:     number;
  win_rate:  number | null;
  open: {
    action: "LONG_QBTX" | "SHORT_QBTZ";
    entry:  number;
    date:   string;
    stop:   number | null;
    target: number | null;
  } | null;
}
export interface DecisionJournal {
  records:   JournalRecord[];
  paper?:    JournalPaper;
  n_graded:  number;
  n_correct: number;
  accuracy:  number | null;
  n_shadow?:         number;          // graded calls incl. HOLD shadow leans
  n_shadow_correct?: number;
  shadow_accuracy?:  number | null;   // directional accuracy incl. observed HOLDs
  lessons:   string[];
}

export interface MacroEvent {
  date:        string;
  time_et:     string;
  title:       string;
  impact:      "High" | "Medium";
  forecast:    string;
  previous:    string;
  actual:      string;    // filled by the feed after release
  nuclear:     boolean;
  hours_until?: number;   // negative = already released
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
  invalidation_price?: number;   // QBTS level that kills the plan (machine-checkable)
  plan_valid?:        boolean;   // false = stop/target geometry was inconsistent
  vivienne_note?:     string;    // plain-language, no-jargon note for a non-expert reader
  intraday_unstable?: boolean;   // true = today's call flip-flopped across regenerations
  intraday_actions?:  ("LONG_QBTX" | "SHORT_QBTZ" | "HOLD")[];  // actions seen today, in order
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

/* ── live quote (written by quote_pusher.py every ~60s) ──────────────────── */
export interface LiveQuoteEntry {
  price:      number;
  prev_close: number | null;
  change_pct: number | null;
  bar_time:   string | null;
}
export interface LiveQuote {
  session:    "closed" | "pre" | "regular" | "post";
  asof_et:    string;
  asof_epoch: number;
  quotes:     Partial<Record<"qbts" | "qbtx" | "qbtz", LiveQuoteEntry>>;
  // Intraday SMC refresh (cloud QuoteFunction, ~every 5 min) — the FULL analyze_smc
  // read (structure/zones/sweeps + playbook) so the page renders the whole SMC card
  // from one live source. Fresher than the daily snapshot, so the page prefers it.
  smc?: (SmcAnalysis & { asof?: string }) | null;
}

/** Live quote — Supabase row in deployed mode, local backend in dev. Null on failure. */
export async function getLiveQuote(): Promise<LiveQuote | null> {
  try {
    if (!SUPABASE_CONFIGURED) {
      const r = await fetch(`${API}/quote/live`);
      if (!r.ok) return null;
      return (await r.json()) as LiveQuote;
    }
    const { data, error } = await supabase
      .from("live_quote").select("data").eq("id", 1).maybeSingle();
    if (error || !data) return null;
    return data.data as LiveQuote;
  } catch {
    return null;
  }
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

/* ── 🔭 自选扫描 (watchlist scan) ─────────────────────────────────────────── */
export interface ScanResult {
  ticker:        string;
  theme:         string;
  price?:        number;
  today_change?: number;
  vol_annual?:   number | null;
  score:         number;        // 0-100 buy-setup proximity
  points?:       number;
  bars?:         number;        // daily bars available
  thin_data?:    boolean;       // <60 bars → technicals unreliable (e.g. fresh IPO)
  earnings?:     { date: string; days: number; soon: boolean } | null;  // 财报跳空风险
  dilution?:     {                                  // SEC 增发/稀释文件(事件面,机械扫描看不见)
    risk: boolean; level: "high" | "warn"; note: string;
    recent: { form: string; date: string }[];
  } | null;
  stance:        string;        // 买入区 / 接近买点 / 观望 / 偏空回避 / —
  stance_emoji:  string;
  trend?:        "bullish" | "bearish" | "neutral" | null;
  regime?:       string | null;
  rsi?:          number | null;
  trigger?:      string;        // plain-language one-liner
  levels?:       { buy_zone: string | null; target: string | null; stop_hint: string | null };
  exit_hint?:    { kind: "profit" | "risk" | "warn"; tag: string; text: string } | null;  // 如有持仓的轻量出场提示
  lockup?:       {                                  // 解禁倒计时(事件叠加层,仅展示)
    next_date?: string; days?: number; label?: string; approx?: boolean; big?: boolean;
    note?: string | null; ipo_price?: number | null;
    upcoming?: { date: string; label: string; days: number }[];
    next?: null;
  } | null;
  notes?:        string[];
  record?:       { n: number; correct: number; hit_rate: number | null } | null;  // this ticker's track record
  error?:        string | null;
}
export interface PaperOpen {
  ticker: string; theme?: string | null;
  entry_date: string; entry_price: number; current_price: number;
  pnl: number; pnl_pct: number; days: number;
}
export interface PaperClosed {
  ticker: string; theme?: string | null;
  entry_date: string; entry_price: number; exit_date: string; exit_price: number;
  pnl: number; pnl_pct: number; reason: string; days: number;
}
export interface PaperSim {
  trade_usd: number;
  open: PaperOpen[];
  closed: PaperClosed[];
  totals: {
    realized: number; unrealized: number; total: number;
    n_open: number; invested_open: number;
    n_closed: number; n_win: number; win_rate: number | null;
  };
}
export interface MarketContext {
  regime: "risk_on" | "caution" | "risk_off";
  note: string; vix: number; spy_vs_50dma: number; qqq_vs_50dma: number;
}
export interface ConcurrentBuys {
  tickers: string[]; avg_corr: number | null; note: string | null;
}
export interface WatchScan {
  generated_at:    string;
  tickers:         string[];
  results:         ScanResult[];
  record_overall?: { n: number; correct: number; hit_rate: number | null };
  paper?:          PaperSim | null;
  market?:         MarketContext | null;
  concurrent_buys?: ConcurrentBuys | null;
  commentary?:     string;
}

/** Latest watchlist scan (single 'current' row; null if not generated yet). */
export async function getWatchScan(): Promise<WatchScan | null> {
  const { data, error } = await supabase
    .from("watchlist_scan").select("data").eq("id", "current").maybeSingle();
  if (error || !data) return null;
  return data.data as WatchScan;
}

/** Whether watchlist editing is available (cloud Lambda URL or a local backend). */
export const WATCH_EDITABLE = !!(process.env.NEXT_PUBLIC_PUBLISH_URL) || !SUPABASE_CONFIGURED;

/* ── 📥 定投专区 (全球估值菜单 + 证据版加码) ──────────────────────────────────── */
export interface DcaResult {
  ticker:           string;
  name:             string;
  role?:            string;      // 美国核心 / 发达除美 / 新兴 / 美股便宜角落
  target_weight?:   number;      // 建议目标权重 %
  price?:           number;
  today_change?:    number;
  pe?:              number | null;
  earnings_yield?:  number | null;  // 1/PE ≈ 粗略长期预期年化(实际)
  cagr?:            number | null;  // 完整历史复合年化(含分红,总回报)
  cagr_years?:      number | null;  // CAGR 覆盖的年数
  valuation:        string;      // 便宜 / 中性 / 偏贵 / —
  valuation_emoji:  string;
  drawdown_pct?:    number;      // from 52w high (≤ 0)
  vs_200dma_pct?:   number;
  below_200?:       boolean;
  deploy?:          { tag: string; emoji: string; text: string };  // 证据版「何时多投」
  best_month?:      number;  best_month_avg?:  number;
  worst_month?:     number;  worst_month_avg?: number;
  winter_avg?:      number;  summer_avg?:      number;
  error?:           string | null;
}
export interface DcaState {
  generated_at: string;
  etfs:         string[];
  results:      DcaResult[];
  watch?:       DcaResult[];   // 择机观察(不进核心配置,便宜了再买)
  watch_note?:  string;
  allocation?:  { weights: Record<string, number>; note: string };
  macro?:       { us_cape: number; global_cape: number; as_of: string; note: string };
  ballast?:     string;
  principle:    string;
  separation?:  string;
}

/** Latest DCA seasonality read (single 'current' row; null if not generated yet). */
export async function getDcaState(): Promise<DcaState | null> {
  const { data, error } = await supabase
    .from("dca_state").select("data").eq("id", "current").maybeSingle();
  if (error || !data) return null;
  return data.data as DcaState;
}

/* ── 🔮 月度复盘 (model-written review of the accumulated track record) ────────── */
export interface Retrospective {
  generated_at:  string;
  period_start:  string | null;
  period_end:    string | null;
  report_md:     string;
  stats?:        Record<string, unknown>;
}

/** Latest persisted monthly retrospective (single 'current' row; null if none yet). */
export async function getRetrospective(): Promise<Retrospective | null> {
  const { data, error } = await supabase
    .from("retrospective").select("data").eq("id", "current").maybeSingle();
  if (error || !data) return null;
  return data.data as Retrospective;
}

/* ── 🎰 $1000→+$100 一个月挑战 (纸面盘, 无加密) ──────────────────────────────── */
export interface ChallengePosition {
  symbol: string; qty: number; entry_px: number; invested: number;
  tp_px: number; stop_px: number; cur_px?: number; unreal?: number;
}
export interface CryptoChallenge {
  status:       "running" | "won" | "halted";
  sleeve_start: number;
  sleeve_cash:  number;
  equity:       number;
  pnl:          number;
  pnl_pct:      number;
  peak_equity:  number;
  win_line:     number;
  floor_line:   number;
  position:     ChallengePosition | null;
  basket:       string[];
  deadline:     string;
  odds_note:    string;
  history:      string[];
  updated_at:   string;
}

/** Latest challenge state (single 'current' row; null until the bot first pushes). */
export async function getCryptoChallenge(): Promise<CryptoChallenge | null> {
  const { data, error } = await supabase
    .from("crypto_challenge").select("data").eq("id", "current").maybeSingle();
  if (error || !data) return null;
  return data.data as CryptoChallenge;
}

/** Edit the watchlist + re-scan. Cloud → Lambda Function URL; local → FastAPI.
 *  action: "watch_add" | "watch_remove" | "rescan". Re-scan can take ~30s. */
export async function postWatchAction(
  action: string, ticker?: string,
): Promise<{ ok: boolean; watchlist?: string[]; error?: string }> {
  const url = process.env.NEXT_PUBLIC_PUBLISH_URL || `${API}/scan/watch`;
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ...(ticker ? { ticker } : {}) }),
    });
    if (!r.ok) return { ok: false, error: `HTTP ${r.status}` };
    return await r.json();
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "请求失败" };
  }
}
