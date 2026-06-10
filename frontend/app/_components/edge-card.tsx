"use client";

interface EdgeContribution {
  source:   string;
  kind:     "mined" | "classic" | "news";
  signal:   -1 | 0 | 1;
  weight:   number;
  log_odds: number;
  detail:   string;
}

interface Edge {
  signal:              -1 | 0 | 1;
  label:               "BUY" | "SELL" | "HOLD";
  p_up:                number;
  expected_return_pct: number;
  kelly_fraction:      number;
  log_odds:            number;
  n_signals:           number;
  contributions:       EdgeContribution[];
  error?:              string;
}

interface SourceStatus {
  status:    "active" | "neutral" | "needs_setup" | "error";
  label:     string;
  rationale?: string;
}

interface EdgeCardProps {
  edge:           Edge;
  price:          number;
  capital:        number;     // user-supplied for sizing ($10k default)
  sourcesStatus?: Record<string, SourceStatus>;
}

const KIND_LABEL: Record<EdgeContribution["kind"], string> = {
  mined:   "ML 因子",
  classic: "经典策略",
  news:    "新闻情绪",
};
const KIND_COLOR: Record<EdgeContribution["kind"], string> = {
  mined:   "bg-violet-100 text-violet-700",
  classic: "bg-slate-100 text-slate-700",
  news:    "bg-amber-100 text-amber-700",
};

const SOURCE_LABEL: Record<string, string> = {
  options:  "期权流",
  intraday: "盘中量能",
  reddit:   "Reddit 散户情绪",
  holdings: "13F 机构持仓",
};
const STATUS_BADGE: Record<SourceStatus["status"], { emoji: string; cls: string; text: string }> = {
  active:      { emoji: "🟢", cls: "bg-emerald-50  text-emerald-700 border-emerald-200", text: "参与决策" },
  neutral:     { emoji: "⚪", cls: "bg-gray-50     text-gray-600    border-gray-200",    text: "中性观望" },
  needs_setup: { emoji: "🔧", cls: "bg-amber-50    text-amber-700   border-amber-200",   text: "需配置"   },
  error:       { emoji: "❌", cls: "bg-red-50      text-[#F03A3E]   border-red-200",     text: "拉取失败" },
};

export function EdgeCard({ edge, price, capital, sourcesStatus }: EdgeCardProps) {
  if (edge.error) {
    return (
      <section className="bg-white rounded-xl border border-red-200 p-4 text-xs text-[#F03A3E]">
        Edge 计算失败: {edge.error}
      </section>
    );
  }

  const isBuy   = edge.label === "BUY";
  const isSell  = edge.label === "SELL";
  const bg      = isBuy ? "from-emerald-50 via-white to-white border-emerald-200"
                : isSell ? "from-red-50 via-white to-white border-red-200"
                : "from-gray-50 via-white to-white border-[#EDEDF0]";
  const accent  = isBuy ? "text-emerald-600" : isSell ? "text-[#F03A3E]" : "text-[#525461]";
  const dollarSize = Math.round(capital * Math.abs(edge.kelly_fraction));
  const dollarEV   = capital * edge.expected_return_pct;

  const pUpPct = edge.p_up * 100;

  // 0..100 visual position: 50% = neutral midpoint
  const barOffset = Math.max(0, Math.min(100, pUpPct));

  return (
    <section className={`bg-gradient-to-br ${bg} rounded-xl border-2 overflow-hidden shadow-sm`}>
      <div className="px-5 py-3 border-b border-current/10 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xl">🎯</span>
          <span className={`text-xs font-bold uppercase tracking-wider ${accent}`}>
            Meta-Model Edge · 系统综合判定
          </span>
        </div>
        <span className="text-[10px] text-gray-400 font-mono">
          {edge.n_signals} 个信号源 · log-odds {edge.log_odds > 0 ? "+" : ""}{edge.log_odds.toFixed(2)}
        </span>
      </div>

      <div className="px-5 py-5 grid grid-cols-1 lg:grid-cols-[1fr_1.4fr] gap-5">

        {/* ── Left: headline metrics ── */}
        <div className="space-y-3">
          {/* Big verdict + P(up) */}
          <div>
            <div className="text-[10px] uppercase tracking-widest text-gray-500 mb-1">系统判定</div>
            <div className={`text-4xl font-bold ${accent}`}>
              {isBuy ? "↗ 做多" : isSell ? "↘ 做空" : "— 观望"}
            </div>
          </div>

          {/* P(up) bar */}
          <div>
            <div className="flex justify-between text-[10px] text-gray-500 mb-1">
              <span>上行概率 P(up)</span>
              <span className="font-mono font-semibold text-gray-900">{pUpPct.toFixed(1)}%</span>
            </div>
            <div className="relative h-3 bg-gray-100 rounded-full overflow-hidden">
              <div className="absolute top-0 left-1/2 w-px h-full bg-gray-300" />
              <div className={`absolute top-0 h-full ${isBuy ? "bg-emerald-500" : "bg-[#F03A3E]"}`}
                   style={{
                     left:  isBuy ? "50%" : `${barOffset}%`,
                     width: `${Math.abs(barOffset - 50)}%`,
                   }} />
            </div>
            <div className="flex justify-between text-[9px] text-gray-400 mt-0.5">
              <span>0%</span><span>50%</span><span>100%</span>
            </div>
          </div>

          {/* EV + Kelly */}
          <div className="grid grid-cols-2 gap-2 pt-1">
            <div className="bg-white rounded-lg border border-[#EDEDF0] px-3 py-2">
              <div className="text-[9px] uppercase tracking-wider text-gray-500">期望收益 EV</div>
              <div className={`text-lg font-bold font-mono ${edge.expected_return_pct > 0 ? "text-emerald-600" : edge.expected_return_pct < 0 ? "text-[#F03A3E]" : "text-gray-500"}`}>
                {edge.expected_return_pct > 0 ? "+" : ""}{(edge.expected_return_pct * 100).toFixed(2)}%
              </div>
              <div className="text-[10px] text-gray-400">
                ${capital.toLocaleString()} → {dollarEV >= 0 ? "+" : ""}${dollarEV.toFixed(0)}
              </div>
            </div>
            <div className="bg-white rounded-lg border border-[#EDEDF0] px-3 py-2">
              <div className="text-[9px] uppercase tracking-wider text-gray-500">凯利仓位</div>
              <div className={`text-lg font-bold font-mono ${accent}`}>
                {edge.kelly_fraction > 0 ? "+" : ""}{(edge.kelly_fraction * 100).toFixed(1)}%
              </div>
              <div className="text-[10px] text-gray-400">
                ≈ ${dollarSize.toLocaleString()} 仓位
              </div>
            </div>
          </div>
        </div>

        {/* ── Right: contributing signals ── */}
        <div>
          <div className="text-[10px] uppercase tracking-widest text-gray-500 mb-2">
            信号贡献度（按强度排序）
          </div>
          <div className="space-y-1">
            {edge.contributions.length === 0 ? (
              <div className="text-xs text-gray-400 py-4 text-center">暂无活跃信号</div>
            ) : edge.contributions.map((c, i) => {
              const pct  = Math.abs(c.log_odds);
              const barW = Math.min(100, pct * 50);   // visual scale
              return (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className={`shrink-0 inline-block w-4 ${c.signal > 0 ? "text-emerald-600" : "text-[#F03A3E]"}`}>
                    {c.signal > 0 ? "↗" : "↘"}
                  </span>
                  <span className={`shrink-0 text-[9px] px-1.5 py-0.5 rounded font-semibold ${KIND_COLOR[c.kind]}`}>
                    {KIND_LABEL[c.kind]}
                  </span>
                  <span className="flex-1 truncate text-gray-900 font-medium" title={c.detail}>
                    {c.source}
                  </span>
                  <div className="shrink-0 flex items-center gap-1.5 w-32">
                    <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div className={`h-full ${c.signal > 0 ? "bg-emerald-500" : "bg-[#F03A3E]"}`}
                           style={{ width: `${barW}%` }} />
                    </div>
                    <span className="text-[10px] font-mono text-gray-500 w-10 text-right">
                      {c.log_odds > 0 ? "+" : ""}{c.log_odds.toFixed(2)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
          <p className="text-[10px] text-gray-400 mt-3 leading-relaxed">
            log-odds 加权合成 · ML 因子按 OOS Sharpe 给权重 · 经典策略按置信度 ·
            新闻仅作 tilt · Kelly 取半凯利上限 ±50%
          </p>
        </div>
      </div>

      {/* ── Source status grid (always visible — answers "why isn't X here?") ── */}
      {sourcesStatus && (
        <div className="px-5 py-3 border-t border-[#EDEDF0] bg-[#FAFBFC]">
          <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-2">
            🔍 全部信号源状态
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {Object.entries(sourcesStatus).map(([key, st]) => {
              const badge = STATUS_BADGE[st.status];
              return (
                <div key={key}
                     className={`rounded-md border px-2.5 py-2 ${badge.cls}`}
                     title={st.rationale || ""}>
                  <div className="flex items-center justify-between gap-1.5">
                    <span className="text-xs font-semibold truncate">
                      {SOURCE_LABEL[key] || key}
                    </span>
                    <span className="text-[10px] opacity-75">{badge.emoji}</span>
                  </div>
                  <div className="text-[10px] mt-0.5 opacity-75">{badge.text}</div>
                  {st.rationale && (
                    <div className="text-[10px] mt-1 leading-snug opacity-60 line-clamp-2">
                      {st.rationale}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}
