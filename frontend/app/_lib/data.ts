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

/* ── 🌍 地缘政治/政策雷达(伊朗战局/川普政策/量子政策) ────────────────────── */
export interface GeoItem {
  key:       string;
  track:     "iran" | "trump" | "quantum";
  track_cn:  string;
  title:     string;
  source:    string;
  published: string;              // 美东时间 "YYYY-MM-DDTHH:MM ET"(2026-07-10 起,曾是 UTC)
  url:       string;
  relevance: "high" | "medium" | "low";
  stance:    "risk_off" | "risk_on" | "neutral";
  note_cn:   string;
}
export interface GeoRadar {
  as_of:       string;
  risk_level:  "alert" | "watch" | "calm";
  risk_cn:     string;
  headline_cn: string;
  summary_cn:  string;
  items:       GeoItem[];
  alerted?:    string[];          // live_quote 携带的已推送 key(去重用)
}

export interface CatalystItem {
  key:        string;
  track:      "company" | "sector";
  track_cn:   string;
  title:      string;
  source:     string;
  published:  string;
  age_h?:     number | null;
  url:        string;
  impact:     "high" | "medium" | "low";
  direction:  "bullish" | "bearish" | "neutral";
  note_cn:    string;
}

/** 📣 公司催化剂雷达 — D-Wave 自身消息 + 板块同行(零决策权,只做事件背景) */
export interface CatalystRadar {
  as_of:        string;
  impact_level: "breaking" | "watch" | "quiet";
  impact_cn:    string;
  headline_cn:  string;
  summary_cn:   string;
  items:        CatalystItem[];
  alerted?:     string[];         // live_quote 携带的已推送 key(去重用)
}

/** ⚠️ 事件日熔断(第二十八轮):极端跳空 ≥±8% 或 breaking 催化剂 →
 *  技术面读数实测无分辨力(n=37, t=+0.36, p=0.72),系统既不劝进也不劝退。
 *  非事件日后端直接给 null,卡片自动消失。 */
export interface EventDay {
  is_event_day:    true;
  reasons:         string[];
  gap:             number | null;
  gap_basis:       string;
  catalyst_level?: string | null;
  technical_muted: boolean;
  evidence_cn:     string;
  note_cn:         string;
}

export interface Snapshot {
  as_of:        string;
  price:        number;
  today_change: number;
  site_check?:  SiteCheck;   // 🔬 全站六页体检(publish §4.8 回写)
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
  chart: {
    candles:  { time: number; open: number; high: number; low: number; close: number }[];
    sma20:    { time: number; value: number }[];
    sma200:   { time: number; value: number }[];
    high_52w: number;
    low_52w:  number;
    atr_14:   number;
  };
  etf_prices: { qbtx: number | null; qbtz: number | null };
  user_positions?: UserPosition[];   // 💼 实盘持仓(发布时的快照;编辑后以 POST 响应为准)
  strategy_replay?: StrategyReplay | null;  // 🏇 策略战绩页(/factors)的复算数据
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
  geopolitics?: GeoRadar | null;
  catalyst?:    CatalystRadar | null;
  event_day?:   EventDay | null;
  /** 数据源健康。上游给过坏 bar / 最新一根倒退时 ok=false —— 坏数据已被拦在
   *  缓存外,但必须让人看见,否则页面照常绿油油、没人知道读的是补回来的缓存。 */
  data_health?: { ok: boolean; issues: string[] } | null;
  smc?: SmcAnalysis | null;
  volume_profile?:    VolumeProfile | null;
  intrabar_profile?:  IntrabarProfile | null;
  regime?:            VolatilityRegime | null;
  dip_buy?:           DipBuy | null;
  champs?:            Champs | null;
  challenge_basket?:  ChallengeBasket | null;
  sector_rotation?:   SectorRotation | null;
  nw_envelope?:       NwEnvelope | null;
  squeeze?:           ShortFlow | null;
  relative_strength?: RelativeStrength | null;
  sentiment?: {
    buzz_score:      number | null;   // 0-100 attention/velocity
    sentiment_score: number | null;   // -1..+1
    trend:           string | null;   // rising / falling / stable
    mentions?:       number | null;
    bullish_pct?:    number | null;
    bearish_pct?:    number | null;
    signal:          -1 | 0 | 1;
    note:            string;
  } | null;
  journal?: DecisionJournal | null;
  waiting_for?: WaitingFor | null;   // 「今天在等什么」六扳机卡
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
/* ── LuxAlgo 原版面板 ──────────────────────────────────────────────────────
 * `SMC.docx`(LuxAlgo「Smart Money Concepts」Pine v5)的忠实移植输出，**零决策权**。
 * 存在的理由：用户对着 TradingView 上的 LuxAlgo 看盘，仪表盘得说同一套读数。
 * 注意它和上面 SmcAnalysis 的 range / 区域**定义不同**，数值本来就不一样。 */
export interface LuxStructureSide {
  trend: "bullish" | "bearish" | "neutral";
  last_event: { date: string; kind: "BOS" | "CHoCH"; dir: "bullish" | "bearish"; level: number } | null;
  pivot_high: number | null;
  pivot_low:  number | null;
}
export interface LuxZone { type: string; low: number; high: number; date: string; break_date?: string }
export interface LuxPanel {
  source: string;
  internal: LuxStructureSide;
  swing:    LuxStructureSide;
  candle_bias: "bullish" | "bearish" | "neutral";
  trailing: {
    top: number | null; bottom: number | null;
    top_date: string | null; bottom_date: string | null;
    top_label: string; bottom_label: string;
  };
  zones: { premium: [number, number]; equilibrium: [number, number];
           discount: [number, number]; position: number } | null;
  zone_cn: string | null;
  internal_ob: LuxZone[];
  swing_ob:    LuxZone[];
  fvg:         LuxZone[];
  fvg_total:   number;
  equal_hl: { kind: "EQH" | "EQL"; level: number; prev_level: number;
              from_date: string | null; date: string }[];
  swing_points: { tag: "HH" | "HL" | "LH" | "LL"; price: number; date: string }[];
  mtf: Record<string, number | string>;
  alerts: string[];
  atr200: number | null;
  defaults_on:  string[];
  defaults_off: string[];
  fvg_note:   string;
  range_note: string;
}

export interface SmcAnalysis {
  signal: -1 | 0 | 1;
  label:  "BUY" | "SELL" | "HOLD";
  /** LuxAlgo internal(5) —— 方向锁用它 */
  trend:  "bullish" | "bearish" | "neutral";
  /** LuxAlgo swing(50) —— 大级别背景。图上「Strong/Weak Low」标签由它决定；
   *  与 trend 背离是常态，以前只暴露一个才让人误以为是 bug（2026-07-29）。 */
  swing_trend?: "bullish" | "bearish" | "neutral";
  trend_divergence?: boolean;
  strong_low_label?: string;
  swing_pivot?:    { high: number | null; low: number | null };
  internal_pivot?: { high: number | null; low: number | null };
  epoch?: string;
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
  /** LuxAlgo 原版面板（只读复刻，不参与打分） */
  lux?: LuxPanel | null;
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

/* ── intrabar profile (单根日线 bar 内部:吸收/投降/派发) ──────────────────── */
export interface IntrabarProfile {
  available:      boolean;
  bar_date?:      string;
  n_subbars?:     number;
  day_high?:      number;
  day_low?:       number;
  close?:         number;
  intrabar_poc?:  number;
  poc_position?:  number;   // 0=贴当日低, 1=贴当日高
  clv?:           number;   // -1=收最低, +1=收最高
  up_vol_pct?:    number;
  down_vol_pct?:  number;
  net_delta_pct?: number;   // -1..+1
  read?:          "吸收" | "投降" | "派发" | "突破接受" | "低位承接" | "高位换手" | "均衡";
  stance?:        "偏多" | "偏空" | "中性";
  read_note?:     string;
  delta_disagree?: boolean;
  delta_strip?:   { date: string; delta_pct: number; sign: 1 | -1 }[];
  rationale?:     string;
  note?:          string;
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
  vol_target?: {            // 波动率目标仓位(0.6/vol,夹20-100%)— 回测验证的 sizing 规则
    target_vol: number; position_pct: number; note: string;
  } | null;
}

/* ── 冠军策略陪跑(35套动物园前两名,纸面测量) ─────────────────────────── */
export interface Champs {
  risk_on?: boolean | null;        // QQQ 是否在 50 日线上
  vt_pct: number;                  // 当前波动率目标敞口(未过滤)
  volreg?: {                       // ① QQQ50×波动率目标 虚拟净值 vs 死拿
    nav: number; bh_nav: number; start_date: string;
    exposure: number; ret_pct: number; bh_ret_pct: number;
  } | null;
  btc?: {                          // ③ BTC昨日绿×QQQ50×波目 虚拟净值(2026-07 第四轮)
    nav: number; start_date: string; exposure: number;
    btc_green?: boolean | null; ret_pct: number;
  } | null;
  clv?: {                          // ④ CLV强收盘×QQQ50×波目 虚拟净值(2026-07 第六轮)
    nav: number; start_date: string; exposure: number;
    clv?: number | null; ret_pct: number;
  } | null;
  veto?: {                         // ⑤ 配对超涨veto(QBTS贵IONQ 1σ清仓,第八轮)
    nav: number; start_date: string; exposure: number;
    z40?: number | null; vetoed?: boolean; ret_pct: number;
  } | null;
  qtum?: {                         // ⑥ QTUM昨日绿×QQQ50×波目(第八轮)
    nav: number; start_date: string; exposure: number;
    qtum_green?: boolean | null; ret_pct: number;
  } | null;
  tj?: {                           // ⑦ 特调双腿 事件式台账(第十轮,用户自创)
    open?: { entry_date: string; entry: number; shares: number } | null;
    sig?: { fast: number; slow: number; buy_base: boolean;
            sell_trim: boolean; sell_clear: boolean } | null;
    n_closed: number; n_win: number; realized: number;
    unreal?: number | null;
  } | null;
  swing: {                         // ② 5日swing×QQQ50 状态机
    lo5: number; hi5: number; close: number; would_trigger: boolean;
    open?: { entry_date: string; entry: number; days: number;
             unreal: number; unreal_pct: number; hi5: number } | null;
    n_closed: number; n_win: number; win_rate?: number | null; realized: number;
  };
}

/* ── QBTS 深坑抄底纸面台账(测量用,策略动物园胜率冠军但未验证) ──────────── */
export interface DipBuy {
  trigger_px: number; hi20: number; close: number;
  triggered: boolean; distance_pct: number;   // 负数 = 还要跌这么多才触发
  open?: { entry_date: string; entry: number; target: number; days: number;
           unreal: number; unreal_pct: number } | null;
  n_closed: number; n_win: number; win_rate?: number | null; realized: number;
  recent?: { entry_date: string; exit_date: string; pnl_pct: number; reason: string }[];
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

/* ── 空头动向(原挤空燃料,2026-07-04 依第五轮实证翻转:空头=聪明钱) ──────── */
export interface ShortFlow {
  signal: -1 | 0 | 1;             // -1 空头拥挤=偏空 · +1 空头撤退=顺风
  label:  "BUY" | "HOLD" | "SELL";
  stance: "crowded" | "neutral" | "retreat";
  stance_cn: string;
  short_ratio: number | null;
  short_z: number | null;
  context?: string | null;        // 期权 PCR / 13F 注脚
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
    day0_ret_pct?:   number | null;   // HOLD 判读:决策日当日涨跌(≥3% → correct=false 漏判)
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
  n_hold_graded?:  number;            // 观望判读(07-22 起):|决策日|<3% ✓ / ≥3% ✗漏判
  n_hold_correct?: number;
  hold_accuracy?:  number | null;
  lessons:   string[];
}

// 「今天在等什么」:六个一级扳机的距触发读数(纯展示,不进决策权重)
export interface WaitingTrigger {
  key:     string;
  name:    string;
  record:  string;           // 回测战绩标签
  fired:   boolean | null;   // null = 今天不适用(如周末BTC非周一)
  reading: string;
  hint:    string;
  aux?:    boolean;          // 辅助腿:只加信心不独立开枪
}
export interface WaitingFor {
  gate: { regime: string | null; note: string | null };
  triggers: WaitingTrigger[];
  n_fired: number;
  summary: string;
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
  // 第十五轮实测事件日影响系数(|ret| 相对无事件日的倍数;null=未测该类事件)
  coef?:       { spy: number; qtum: number; qbts: number; label: string } | null;
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
  bold_call_5d?: "up" | "down"; // 强制二选一的5日方向表态(与 action 解耦,每日影子评分)
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
  model?:             string;    // which model actually produced this decision (fable-5 or fallback)
  system_notes?:      { kind: "数据问题" | "改进建议"; note: string }[];  // AI 每日自检:数据问题/改进建议(给维护者)
  position_advice?:   PositionAdvice[];  // 💼 用户实盘持仓的逐笔操作建议
  shadow?:            boolean;   // true = 影子决策(零决策权,仅对照)
  shadow_ds?:         Decision;  // DeepSeek V4 Pro 影子决策(卡上可切换;8/15 同框宣判)
  shadow_v1_inverse?: {          // 2026-07-21:原始21%命中元模型整体反向的零决策权影子(纯机械,不可切换查看,只做每日徽章)
    source_model: string;
    v1_p_up:      number;
    v1_call:      "up" | "down";
    bold_call_5d: "up" | "down";
    p_up_5d:      number;
    note:         string;
  } | null;
}

/* ── 🔬 全站 AI 系统自检(publish §4.8 · 规则层+Haiku 六页体检) ──────────── */
export interface SiteCheckIssue {
  kind: "数据问题" | "改进建议";
  note: string;
  src?: "rule" | "ai";      // rule=确定性检查 · ai=Haiku 语义层
}
export type SiteCheckPage = "home" | "watch" | "dca" | "factors" | "challenge" | "spacex";
export interface SiteCheck {
  generated_at: string;
  n_issues:     number;
  pages:        Partial<Record<SiteCheckPage, SiteCheckIssue[]>>;
}

/* ── 💼 用户实盘持仓 ─────────────────────────────────────────────────────── */
export interface UserPosition {
  ticker: "QBTS" | "QBTX" | "QBTZ" | string;
  qty:    number;
  cost:   number;
  date?:  string;   // 买入日 YYYY-MM-DD
}
export interface PositionAdvice {
  ticker: string;
  advice: "持有" | "加仓" | "减仓" | "清仓";
  reason: string;
}

/* ── 🏇 策略战绩复算(/factors 页) ─────────────────────────────────────────── */
export interface ReplayTrade {
  buy_date:  string;
  buy_px:    number;
  open:      boolean;
  sell_date?: string;
  sell_px?:   number;
  days:      number;
  ret:       number;    // 段收益(NAV 口径,含仓位与成本)
  sym?:      string;    // 多标的策略(观察组⑪杠杆ETF)标注本段交易的票
}
export interface ReplayStrategy {
  key:   string;
  name:  string;
  emoji: string;
  rule:  string;
  tier?: "watch";      // 👀 观察组(观察名单候选的前向战绩,未晋升纸面马);缺省=在册马
  stats: { ret_full: number; ret_1y: number; max_dd: number;
           n_trades: number; n_wins: number; win_rate: number | null };
  current: { in_market: boolean; exposure: number;
             since?: string; entry_px?: number; unreal?: number; z40?: number | null;
             triggered_today?: boolean; sym?: string };
  trades: ReplayTrade[];
  n_trades_total: number;
}
export interface StrategyReplay {
  generated_at: string;
  as_of:        string;
  window_start: string;
  bh:           { ret_full: number; ret_1y: number; max_dd: number };
  strategies:   ReplayStrategy[];
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

/** 只取 snapshot 里的 site_check 切片(~2KB),各页横幅用——不用为一条横幅拉整个快照 */
export async function getSiteCheck(): Promise<SiteCheck | null> {
  if (!SUPABASE_CONFIGURED) {
    try {
      const r = await fetch(`${API}/dashboard/snapshot`);
      if (!r.ok) return null;
      return ((await r.json()) as Snapshot).site_check ?? null;
    } catch { return null; }
  }
  const { data, error } = await supabase
    .from("dashboard_state")
    .select("check:snapshot->site_check")
    .order("published_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error || !data) return null;
  return (data as { check: SiteCheck | null }).check ?? null;
}

/* ── live quote (written by quote_pusher.py every ~60s) ──────────────────── */
export interface LiveQuoteEntry {
  price:      number;
  prev_close: number | null;
  change_pct: number | null;
  bar_time:   string | null;
  // 🌙 夜盘(Blue Ocean via Alpaca overnight feed):mark = 盘口中点(薄市里比稀疏
  // 的最后成交诚实),ov_age_s = 该 mark 的新鲜度秒数,ov_trade = 最后成交(仅参考)
  ov_age_s?:  number;
  ov_bid?:    number;
  ov_ask?:    number;
  ov_trade?:  number;
}
export interface LiveQuote {
  session:    "closed" | "pre" | "regular" | "post" | "overnight";
  asof_et:    string;
  asof_epoch: number;
  quotes:     Partial<Record<"qbts" | "qbtx" | "qbtz", LiveQuoteEntry>>;
  // Intraday SMC refresh (cloud QuoteFunction, ~every 5 min) — the FULL analyze_smc
  // read (structure/zones/sweeps + playbook) so the page renders the whole SMC card
  // from one live source. Fresher than the daily snapshot, so the page prefers it.
  smc?: (SmcAnalysis & { asof?: string }) | null;
  // 周一开盘·周末BTC 信号(仅周一有值;mining.md 核心事实 #9,验证期)
  btc_weekend?: {
    date: string; weekend_ret: number; green: boolean;
    last_utc_day?: string; pushed?: boolean;
  } | null;
  // 🌍 地缘政治雷达(云端 ~30min 刷新,比每日快照新 → 页面优先读它)
  geo?: GeoRadar | null;
  // 📣 公司催化剂雷达(云端 ~10min 刷新,同上优先读 live 版)
  catalyst?: CatalystRadar | null;
  // ⚠️ 事件日熔断(每分钟判,盘前就能亮 —— 等 09:00 的 publish 就晚了,
  //    07-27 的跳空在 09:30 开盘那一刻就已经 +10.2%)
  event_day?: EventDay | null;
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
  fundamentals?: {                                  // 基本面红旗("该不该碰"层:runway/负毛利/高负债)
    flags: string[]; runway_years?: number | null; gross_margin?: number | null;
  } | null;
  stance:        string;        // 买入区 / 接近买点 / 观望 / 偏空回避 / —
  stance_emoji:  string;
  trend?:        "bullish" | "bearish" | "neutral" | null;
  regime?:       string | null;
  rsi?:          number | null;
  trigger?:      string;        // plain-language one-liner
  target_rr_veto?: boolean;     // 上方参照太近(不够1.5×止损),不设目标
  entry_limit?:  number | null; // 数值买点(回踩限价参考,纸面模拟用)
  sector?:       { ticker: string; label: string; quadrant: string } | null;  // 轮动地图板块
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
  epoch?: "v1" | "v2";   // 缺省 = v1(2026-07-13 机制大修前的旧账,展示时归档)
}
export interface PaperPending {
  ticker: string; limit: number; placed_date: string;
  signal_price?: number; target?: number | null;
}
export interface PaperSim {
  trade_usd: number;
  open: PaperOpen[];
  pending?: PaperPending[];     // v2:回踩限价挂单(触价才成交)
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
  avoid?:          { tickers: string[]; note: string } | null;  // ⛔ 避雷清单(偏空回避)
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
  ballast_etfs?: DcaResult[];  // 压舱石档(BND+GLDM):有卡片有权重,与股票核心合成 100%
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

/* ── 🚀 SpaceX (SPCX) 第二仪表盘 · DeepSeek-only 决策 ─────────────────────────── */
export interface SpacexData {
  ticker: string;
  price: number; prev_close: number; today_change: number;
  sma20: number | null; sma50: number | null; sma200: number | null;
  above_sma20: boolean | null; above_sma50: boolean | null; above_sma200: boolean | null;
  rsi14: number | null; atr14: number | null; atr_pct: number | null;
  ath: number; atl: number; drawdown_from_ath: number | null;
  high_52w: number; low_52w: number;
  ret_5d: number | null; ret_20d: number | null; vol_vs_20d: number | null;
  n_bars: number; thin_data: boolean; as_of: string;
}
export interface SpacexDriver { factor: string; stance: "bull" | "bear" | "neutral"; note: string; }
export interface SpacexCatalyst { date: string; event: string; impact: string; note: string; }
export interface SpacexDecision {
  action: "BUY" | "HOLD" | "REDUCE";
  conviction: number;
  summary: string;
  entry: number | null; stop: number | null; target: number | null; rr: number | null;
  horizon?: string;
  drivers: SpacexDriver[];
  catalysts_read?: string;
  risks: string[];
  lockup_note?: string;
  system_notes?: string[];
  model: string;
}
export interface SpacexNews { title: string; published: string; source: string; }
/* 抢先量三条腿(不吃日线历史长度)*/
export interface SpacexOptionTerm { expiry: string; dte: number | null; expected_move_pct: number | null; atm_iv: number | null; }
export interface SpacexOptions {
  spot: number;
  term: SpacexOptionTerm[];
  event_expiry: SpacexOptionTerm | null;
  event_date: string;
  near_expected_move_pct: number | null;
  skew_put_minus_call: number | null;
}
export interface SpacexIntraday {
  interval: string; n_bars: number;
  rsi14: number | null; atr14: number | null; atr_pct: number | null;
  sma20: number | null; above_sma20: boolean | null;
  sma50: number | null; above_sma50: boolean | null;
  vwap: number | null; above_vwap: boolean | null;
}
export interface SpacexPeer { ticker: string; name: string; vol: number; pure: boolean; }
export interface SpacexPeerPrior {
  spcx_own_vol: number | null; peer_prior: number | null;
  peers: SpacexPeer[]; shrink_weight: number | null; blended_vol: number | null; n_bars: number;
}
export interface SpacexState {
  generated_at: string;
  engine: string;
  data: SpacexData;
  news: SpacexNews[];
  options?: SpacexOptions | null;
  intraday?: SpacexIntraday | null;
  peer_prior?: SpacexPeerPrior | null;
  catalysts: SpacexCatalyst[];
  catalyst_asof: string;
  decision: SpacexDecision | null;
}

/** Latest SpaceX read (single 'current' row; null if table missing / not generated). */
export async function getSpacexState(): Promise<SpacexState | null> {
  const { data, error } = await supabase
    .from("spacex_state").select("data").eq("id", "current").maybeSingle();
  if (error || !data) return null;
  return data.data as SpacexState;
}

/** 🚀 单独重跑 SpaceX 生成(DeepSeek-only)。云 → Lambda Function URL;本地 → FastAPI。
 *  DeepSeek 推理可能 30–60s。成功后调用方应 re-fetch getSpacexState()。 */
export async function postSpacexRefresh(): Promise<{
  ok: boolean; decision?: { action: string; conviction: number } | null; error?: string;
}> {
  const url = process.env.NEXT_PUBLIC_PUBLISH_URL || `${API}/scan/watch`;
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "spacex", client: clientHints() }),
    });
    const j = await r.json().catch(() => null);
    if (!r.ok) return { ok: false, error: j?.error || `HTTP ${r.status}` };
    return j ?? { ok: false, error: "空响应" };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "请求失败" };
  }
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
  round?:       number;              // 第N期(缺省=1)
  runner?:      "local" | "cloud";   // 本地 bot / 云端 Lambda
  status:       "running" | "won" | "halted" | "ended";
  sleeve_start: number;
  sleeve_cash:  number;
  equity:       number;
  pnl:          number;
  pnl_pct:      number;
  peak_equity:  number;
  win_line:     number;
  floor_line:   number | null;      // 2026-07-21 三连亏复盘后可取消(null=不设地板,跑到期)
  position:     ChallengePosition | null;
  basket:       string[];
  deadline:     string;
  odds_note:    string;
  history:      string[];
  updated_at:   string;
  marathon?:     boolean;            // 🏁 2026-07-10 起:不设收手线,跑到 8/15
  milestone_at?: string;             // 首次 +10% 的时间(报喜不收手)
  cooldown_date?: string;            // 平仓当日冷却,次日再进场
  equity_curve?: [string, number][]; // [iso_ts, equity] 每跳(15min)一点
}

/* 挑战「今日照做」篮子 + 全场杠杆ETF扫描 —— 每日 publish 算好放进 snapshot.challenge_basket。 */
export interface ChallengeEtf {
  ticker: string;
  label?: string;          // 中文标签,如「生科 3×」(全场扫描行有)
  error?: string;
  close?: number; ma50?: number; above_50dma?: boolean;
  week_ret?: number; mom20?: number; uptrend?: boolean;
  tp?: number; stop?: number;
  adv20?: number | null;   // 20日均成交额(美元)
}
export interface ChallengeMarketScan {
  n_scanned: number;
  n_qualified: number;
  top: ChallengeEtf[];     // 合格者按20日动量取前N
  pick: string | null;
  note: string;
}
export interface ChallengeBasket {
  as_of: string | null;
  etfs: ChallengeEtf[];
  pick: string | null;
  n_qualified: number;
  market?: ChallengeMarketScan | null;
  note: string;
}

/* 板块轮动地图(RRG 近似)—— snapshot.sector_rotation。 */
export interface SectorPoint {
  ticker: string; label: string; emoji: string;
  trail: [number, number][];   // [RS-Ratio, RS-Momentum],最后一点=最新
  x: number; y: number;        // 最新坐标
  quadrant: "leading" | "weakening" | "lagging" | "improving";
  ret20: number;
}
export interface SectorRotation {
  as_of: string;
  benchmark: string;
  sectors: SectorPoint[];
  note: string;
}

/* ── 🎯 极度超卖游击战(TradingView webhook 观察模块,零决策权) ─────────── */
export interface GuerrillaTrade {
  ticker: string; entry: number; stop: number; target: number; rr: number;
  shares?: number; opened_at: string;
  exit?: number; exit_why?: "stop" | "target"; ret_pct?: number; pnl?: number;
  closed_at?: string; status: "open" | "closed";
}
export interface GuerrillaState {
  open: GuerrillaTrade[];                                   // 在场仓位(open:* 行)
  ledger: { trades: GuerrillaTrade[]; n_trades?: number;
            n_win?: number; realized?: number } | null;     // 已结算流水
  cooldowns: { ticker: string; until_iso: string; until_epoch: number;
               reason?: string }[];                          // 冷却中的标的
}

/** 游击战状态 — 直读 guerrilla_state 表(webhook 驱动,不随每日快照)。
 *  表不存在/未建 → null(页面不渲染该卡,优雅缺席)。 */
export async function getGuerrillaState(): Promise<GuerrillaState | null> {
  try {
    const { data, error } = await supabase.from("guerrilla_state").select("id,data");
    if (error || !data) return null;
    const open: GuerrillaTrade[] = [];
    const cooldowns: GuerrillaState["cooldowns"] = [];
    let ledger: GuerrillaState["ledger"] = null;
    const now = Date.now() / 1000;
    for (const row of data) {
      const d = row.data as Record<string, unknown>;
      if (row.id.startsWith("open:")) open.push(d as unknown as GuerrillaTrade);
      else if (row.id === "ledger") ledger = d as GuerrillaState["ledger"];
      else if (row.id.startsWith("cooldown:")) {
        const until = Number(d.cooldown_until_epoch ?? 0);
        if (until > now)
          cooldowns.push({ ticker: row.id.slice(9), until_epoch: until,
                           until_iso: String(d.cooldown_until_iso ?? ""),
                           reason: d.armed_reason as string | undefined });
      }
    }
    return { open, ledger, cooldowns };
  } catch {
    return null;
  }
}

/** Latest challenge state (single 'current' row; null until the bot first pushes). */
export async function getCryptoChallenge(): Promise<CryptoChallenge | null> {
  const { data, error } = await supabase
    .from("crypto_challenge").select("data").eq("id", "current").maybeSingle();
  if (error || !data) return null;
  return data.data as CryptoChallenge;
}

/** 👀 点击审计:浏览器能诚实拿到的设备提示(计算机名拿不到 — Web 没有这 API)。
 *  随按钮 POST 附带,Lambda 连同来源 IP/UA 一起写进 publish_audit。 */
export function clientHints(): Record<string, string> {
  try {
    const nav = navigator as Navigator & { userAgentData?: { platform?: string } };
    return {
      tz:       Intl.DateTimeFormat().resolvedOptions().timeZone ?? "",
      lang:     navigator.language ?? "",
      platform: nav.userAgentData?.platform || navigator.platform || "",
      screen:   `${window.screen?.width ?? "?"}x${window.screen?.height ?? "?"}`,
    };
  } catch {
    return {};
  }
}

export interface PublishAuditRow {
  id:     number;
  ts:     string;      // timestamptz
  action: string;
  ip:     string | null;
  ua:     string | null;
  client: { tz?: string; lang?: string; platform?: string; screen?: string } | null;
}

/** 隐藏查看窗的数据源(版本号连点3次)。表未建 → 返回 error 供 UI 提示跑迁移。 */
export async function getPublishAudit(limit = 100):
  Promise<{ rows: PublishAuditRow[]; error?: string }> {
  try {
    const { data, error } = await supabase
      .from("publish_audit").select("*")
      .order("ts", { ascending: false }).limit(limit);
    if (error) return { rows: [], error: error.message };
    return { rows: (data ?? []) as PublishAuditRow[] };
  } catch (e) {
    return { rows: [], error: e instanceof Error ? e.message : "读取失败" };
  }
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
      body: JSON.stringify({ action, ...(ticker ? { ticker } : {}), client: clientHints() }),
    });
    if (!r.ok) return { ok: false, error: `HTTP ${r.status}` };
    return await r.json();
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "请求失败" };
  }
}

/** 💼 编辑实盘持仓。action: "pos_add"(同 ticker 覆盖更新)| "pos_remove"。
 *  与自选编辑同一通道:云 → Lambda Function URL;本地 → FastAPI /scan/watch。 */
export async function postPositionAction(
  action: "pos_add" | "pos_remove",
  p: { ticker: string; qty?: number; cost?: number; date?: string },
): Promise<{ ok: boolean; positions?: UserPosition[]; error?: string }> {
  const url = process.env.NEXT_PUBLIC_PUBLISH_URL || `${API}/scan/watch`;
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ...p, client: clientHints() }),
    });
    const j = await r.json().catch(() => null);
    if (!r.ok) return { ok: false, error: j?.error || `HTTP ${r.status}` };
    return j ?? { ok: false, error: "空响应" };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "请求失败" };
  }
}
