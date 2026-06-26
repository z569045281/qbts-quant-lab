"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getWatchScan, postWatchAction, WATCH_EDITABLE,
  type WatchScan, type ScanResult, type PaperSim,
} from "../_lib/data";
import { fmtLocalDateTime } from "../_lib/format";

/* ─────────────────────────────────────────────────────────────────────────
   🔭 自选扫描 — 分散高波动篮子的每日买点扫描（独立于 QBTS 决策仪表盘）。
   每只票跑通用信号(SMC 结构 / 成交量画像 / 波动 regime),给出买点立场 + 大白话
   触发条件 + 关键价位 + 自己的历史命中率。可在页面上加/删自选。
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

function ScanCard({ r, editable, onRemove }: {
  r: ScanResult; editable: boolean; onRemove: (t: string) => void;
}) {
  const s = STANCE[r.stance] ?? FALLBACK;
  const up = (r.today_change ?? 0) >= 0;
  const rec = r.record;

  if (r.error) {
    return (
      <div className="relative rounded-2xl border border-[#E5E5EA] bg-white p-4 flex items-center gap-3">
        <span className="text-lg">⚠️</span>
        <span className="font-bold text-gray-800">{r.ticker}</span>
        <span className="text-xs text-gray-400">{r.theme} · 数据拉取失败</span>
        {editable && <RemoveBtn t={r.ticker} onRemove={onRemove} />}
      </div>
    );
  }

  return (
    <div className={`relative rounded-2xl border ${s.border} ${s.bg} p-4 shadow-sm`}>
      {editable && <RemoveBtn t={r.ticker} onRemove={onRemove} />}
      {/* 头行 */}
      <div className="flex items-center gap-2 flex-wrap pr-6">
        <span className="text-lg leading-none">{r.stance_emoji}</span>
        <span className="text-lg font-bold text-gray-900">{r.ticker}</span>
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 font-medium">{r.theme}</span>
        <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold ${s.chip}`}>{r.stance}</span>
        <span className="ml-auto text-sm font-mono text-gray-900">${r.price?.toFixed(2)}</span>
        <span className={`text-sm font-semibold ${up ? "text-emerald-600" : "text-[#F03A3E]"}`}>
          {up ? "▲" : "▼"} {pct(Math.abs(r.today_change ?? 0))}
        </span>
      </div>

      {/* 数据不足警告（新 IPO 等，技术信号不可靠）*/}
      {r.thin_data && (
        <div className="mt-2 text-[11px] leading-relaxed rounded-lg px-2.5 py-1.5 bg-red-50 text-red-600 border border-red-100">
          ⚠️ 仅 {r.bars ?? "<60"} 天历史 —— 技术信号是噪声、不可靠,已排除出模拟交易
        </div>
      )}

      {/* 评分条 + 历史命中 */}
      <div className="flex items-center gap-2 mt-2.5">
        <span className="text-[10px] text-gray-400 w-12">买点分</span>
        <div className="flex-1 h-1.5 rounded-full bg-gray-100 overflow-hidden">
          <div className={`h-full ${s.bar}`} style={{ width: `${r.score}%` }} />
        </div>
        <span className="text-xs font-mono font-semibold text-gray-600 w-8 text-right">{r.score}</span>
        {rec && rec.n > 0 && rec.hit_rate != null && (
          <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
            rec.hit_rate >= 0.55 ? "bg-emerald-50 text-emerald-600"
            : rec.hit_rate >= 0.45 ? "bg-amber-50 text-amber-600" : "bg-red-50 text-red-500"}`}
            title="这只票过往扫描判断的命中率（5个交易日后评判）">
            命中 {(rec.hit_rate * 100).toFixed(0)}% ({rec.correct}/{rec.n})
          </span>
        )}
      </div>

      {r.trigger && <p className="mt-2.5 text-[13px] leading-relaxed text-gray-800">{r.trigger}</p>}

      {r.levels && (r.levels.buy_zone || r.levels.target) && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] font-mono">
          {r.levels.buy_zone && <span className="text-emerald-700">买入参考 {r.levels.buy_zone}</span>}
          {r.levels.target && <span className="text-blue-600">上方目标 {r.levels.target}</span>}
        </div>
      )}

      {/* 出场提示（如有持仓）— 纯按今日价 vs 目标/均线判定，不追踪你的成本 */}
      {r.exit_hint && (
        <div className={`mt-2 flex items-start gap-1.5 text-[11px] leading-relaxed rounded-lg px-2.5 py-1.5 ${
          r.exit_hint.kind === "profit" ? "bg-blue-50 text-blue-700"
          : r.exit_hint.kind === "risk" ? "bg-red-50 text-red-600"
          : "bg-amber-50 text-amber-700"}`}>
          <span className="font-semibold shrink-0">{r.exit_hint.tag}</span>
          <span>{r.exit_hint.text}</span>
        </div>
      )}

      {/* 解禁倒计时（事件叠加层 — 机械信号看不见的供给冲击）*/}
      {r.lockup && typeof r.lockup.days === "number" && (
        <div className={`mt-2 text-[11px] leading-relaxed rounded-lg px-2.5 py-1.5 border ${
          r.lockup.big ? "bg-orange-50 text-orange-700 border-orange-200"
          : "bg-amber-50/60 text-amber-700 border-amber-100"}`}
          title={r.lockup.upcoming?.map(u => `${u.date}（${u.days}天）· ${u.label}`).join("\n")}>
          <div className="flex items-start gap-1.5">
            <span className="shrink-0">⏳</span>
            <span>
              <b>距下次解禁还有 {r.lockup.days} 天</b>
              （{r.lockup.approx ? "约 " : ""}{r.lockup.next_date}）{r.lockup.big && " 🔴"}
              <span className="block">{r.lockup.label}</span>
              {r.lockup.note && <span className="block text-orange-600/70 mt-0.5">{r.lockup.note}</span>}
            </span>
          </div>
        </div>
      )}

      {/* 财报倒计时（机械信号看不见的跳空风险）*/}
      {r.earnings && (
        <div className={`mt-2 text-[11px] leading-relaxed rounded-lg px-2.5 py-1.5 border ${
          r.earnings.soon ? "bg-purple-50 text-purple-700 border-purple-200"
          : "bg-gray-50 text-gray-500 border-gray-100"}`}>
          📅 财报 <b>{r.earnings.days} 天后</b>（{r.earnings.date}）{r.earnings.soon && " 🔴 临近,持仓注意跳空风险"}
        </div>
      )}

      <div className="mt-2.5 flex flex-wrap gap-1.5 text-[10px]">
        {r.trend && (
          <span className={`px-1.5 py-0.5 rounded ${
            r.trend === "bullish" ? "bg-emerald-50 text-emerald-600"
            : r.trend === "bearish" ? "bg-red-50 text-red-600" : "bg-gray-50 text-gray-500"}`}>
            {TREND_CN[r.trend]}
          </span>
        )}
        {r.regime && <span className="px-1.5 py-0.5 rounded bg-gray-50 text-gray-500">{REGIME_CN[r.regime] ?? r.regime}</span>}
        {typeof r.vol_annual === "number" && <span className="px-1.5 py-0.5 rounded bg-gray-50 text-gray-500">年化波动 {Math.round(r.vol_annual * 100)}%</span>}
        {typeof r.rsi === "number" && <span className="px-1.5 py-0.5 rounded bg-gray-50 text-gray-500">RSI {r.rsi.toFixed(0)}</span>}
      </div>
    </div>
  );
}

function money(n: number): string {
  const s = n >= 0 ? "+" : "−";
  return `${s}$${Math.abs(n).toFixed(2)}`;
}
function pctSigned(n: number): string {
  return `${n >= 0 ? "+" : ""}${(n * 100).toFixed(1)}%`;
}

function PaperPanel({ p }: { p: PaperSim }) {
  const t = p.totals;
  const tone = (n: number) => (n > 0 ? "text-emerald-600" : n < 0 ? "text-[#F03A3E]" : "text-gray-500");
  return (
    <section className="rounded-2xl border border-[#E6E6EA] bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm">📊</span>
        <span className="text-xs font-semibold text-gray-800">模拟战绩 · 每个买入信号投 ${p.trade_usd.toFixed(0)}</span>
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-400">模拟 · 非真实交易</span>
      </div>

      {/* 总览 */}
      <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
        <div className="bg-[#FAFAFC] rounded-xl px-2 py-2">
          <div className="text-[10px] text-gray-400">总盈亏</div>
          <div className={`text-lg font-bold font-mono ${tone(t.total)}`}>{money(t.total)}</div>
        </div>
        <div className="bg-[#FAFAFC] rounded-xl px-2 py-2">
          <div className="text-[10px] text-gray-400">已平仓(落袋)</div>
          <div className={`text-sm font-semibold font-mono ${tone(t.realized)}`}>{money(t.realized)}</div>
        </div>
        <div className="bg-[#FAFAFC] rounded-xl px-2 py-2">
          <div className="text-[10px] text-gray-400">持仓浮动</div>
          <div className={`text-sm font-semibold font-mono ${tone(t.unrealized)}`}>{money(t.unrealized)}</div>
        </div>
        <div className="bg-[#FAFAFC] rounded-xl px-2 py-2">
          <div className="text-[10px] text-gray-400">平仓胜率</div>
          <div className="text-sm font-semibold font-mono text-gray-700">
            {t.win_rate != null ? `${(t.win_rate * 100).toFixed(0)}% (${t.n_win}/${t.n_closed})` : "—"}
          </div>
        </div>
      </div>

      {/* 当前持仓 */}
      {p.open.length > 0 && (
        <div className="mt-3">
          <div className="text-[11px] text-gray-500 mb-1">当前持仓 {p.open.length} 笔</div>
          <div className="space-y-1">
            {p.open.map(o => (
              <div key={o.ticker} className="flex items-center gap-2 text-[12px] bg-emerald-50/40 rounded-lg px-2.5 py-1.5">
                <span className="font-bold text-gray-800 w-12">{o.ticker}</span>
                <span className="text-gray-400 text-[11px]">{o.entry_date.slice(5)} 买 ${o.entry_price.toFixed(2)}</span>
                <span className="text-gray-400 text-[11px]">→ ${o.current_price.toFixed(2)}</span>
                <span className="text-gray-300 text-[10px]">{o.days}天</span>
                <span className={`ml-auto font-mono font-semibold ${tone(o.pnl)}`}>{money(o.pnl)} ({pctSigned(o.pnl_pct)})</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 已平仓 */}
      {p.closed.length > 0 && (
        <div className="mt-3">
          <div className="text-[11px] text-gray-500 mb-1">已平仓(最近 {p.closed.length} 笔)</div>
          <div className="space-y-1">
            {p.closed.map((c, i) => (
              <div key={`${c.ticker}-${c.exit_date}-${i}`} className="flex items-center gap-2 text-[12px] bg-[#FAFAFC] rounded-lg px-2.5 py-1.5">
                <span className="font-bold text-gray-800 w-12">{c.ticker}</span>
                <span className="text-gray-400 text-[11px]">{c.entry_date.slice(5)}→{c.exit_date.slice(5)} · {c.days}天</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{c.reason}</span>
                <span className={`ml-auto font-mono font-semibold ${tone(c.pnl)}`}>{money(c.pnl)} ({pctSigned(c.pnl_pct)})</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {p.open.length === 0 && p.closed.length === 0 && (
        <p className="mt-3 text-[11px] text-gray-400">还没有触发任何买入信号 — 出现 🟢买入区 时会自动模拟买入 ${p.trade_usd.toFixed(0)}。</p>
      )}
    </section>
  );
}

function RemoveBtn({ t, onRemove }: { t: string; onRemove: (t: string) => void }) {
  return (
    <button onClick={() => onRemove(t)} title={`从自选移除 ${t}`}
      className="absolute top-2 right-2 w-5 h-5 rounded-full text-gray-300 hover:text-red-500 hover:bg-red-50 text-xs leading-none flex items-center justify-center transition-colors">
      ✕
    </button>
  );
}

export default function WatchScanPage() {
  const [scan, setScan] = useState<WatchScan | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);   // non-null = an edit/scan in flight
  const [input, setInput] = useState("");

  const refresh = useCallback(async () => {
    const s = await getWatchScan();
    setScan(s); setLoading(false);
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  const runAction = async (action: string, ticker?: string, label?: string) => {
    setBusy(label ?? "扫描中");
    const res = await postWatchAction(action, ticker);
    if (!res.ok) { alert(`操作失败：${res.error ?? "未知错误"}`); setBusy(null); return; }
    await refresh();
    setBusy(null);
  };
  const handleAdd = () => {
    const t = input.trim().toUpperCase();
    if (!t) return;
    setInput("");
    runAction("watch_add", t, `添加 ${t} 并扫描`);
  };
  const handleRemove = (t: string) => {
    if (confirm(`把 ${t} 从自选移除?`)) runAction("watch_remove", t, `移除 ${t}`);
  };

  const genAt = fmtLocalDateTime(scan?.generated_at);   // UTC → 浏览器本地时区
  const ov = scan?.record_overall;

  return (
    <main className="max-w-[1100px] mx-auto px-4 sm:px-6 py-5 sm:py-6 space-y-4">
      {/* 标题 */}
      <section className="bg-white rounded-2xl border border-[#EDEDF0] p-5 shadow-sm">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-base">🔭</span>
          <span className="text-sm font-semibold text-gray-800">自选扫描 · 分散高波动篮子</span>
          {ov && ov.hit_rate != null && (
            <span className={`text-[11px] font-mono px-2 py-0.5 rounded-full font-bold ${
              ov.hit_rate >= 0.55 ? "bg-emerald-100 text-emerald-700"
              : ov.hit_rate >= 0.45 ? "bg-amber-100 text-amber-700" : "bg-red-100 text-red-600"}`}
              title="所有方向性扫描判断的总命中率（5个交易日后评判）">
              扫描命中 {(ov.hit_rate * 100).toFixed(0)}% ({ov.correct}/{ov.n})
            </span>
          )}
          {genAt && <span className="ml-auto text-[10px] text-gray-400 font-mono">扫描于 {genAt}</span>}
        </div>
        <p className="mt-2 text-xs text-[#525461] leading-relaxed">
          不同驱动的高波动板块,每天扫一遍——按"最接近买点"排序,给立场、大白话触发条件、关键价位,
          并记录自己的历史命中率(5 个交易日后评判)。<span className="text-gray-400">纯机械信号。</span>
        </p>
        <div className="mt-2 flex flex-wrap gap-2 text-[10px]">
          {[["🟢", "买入区"], ["🟡", "接近买点"], ["⚪", "观望"], ["🔴", "偏空回避"]].map(([e, l]) => (
            <span key={l} className="px-1.5 py-0.5 rounded bg-[#F6F6F8] text-gray-500">{e} {l}</span>
          ))}
        </div>

        {/* 管理自选 */}
        {WATCH_EDITABLE && (
          <div className="mt-3 pt-3 border-t border-[#F0F0F2] flex items-center gap-2 flex-wrap">
            <span className="text-[11px] text-gray-500">管理自选:</span>
            <input
              value={input}
              onChange={e => setInput(e.target.value.toUpperCase())}
              onKeyDown={e => { if (e.key === "Enter") handleAdd(); }}
              placeholder="股票代码 如 NVDA"
              disabled={!!busy}
              className="px-2.5 py-1 text-xs font-mono border border-[#D9D9DE] rounded-md w-36 focus:outline-none focus:border-[#006FFF] disabled:bg-gray-50"
            />
            <button onClick={handleAdd} disabled={!!busy || !input.trim()}
              className="px-3 py-1 text-xs font-medium bg-[#006FFF] text-white rounded-md hover:bg-blue-600 disabled:opacity-40">
              添加
            </button>
            {busy && (
              <span className="text-[11px] text-amber-600 flex items-center gap-1.5">
                <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                {busy}…(重新扫描约 30 秒)
              </span>
            )}
            {!busy && <span className="text-[10px] text-gray-400">点 ✕ 移除 · 改完会自动重新扫描</span>}
          </div>
        )}
      </section>

      {/* ⚠️ P0 信号未验证门 — 已评判样本不足时,警告勿据此加仓 */}
      {scan && (ov?.n ?? 0) < 30 && (
        <section className="rounded-2xl border border-amber-300 bg-amber-50 p-4 shadow-sm">
          <p className="text-[13px] leading-relaxed text-amber-800">
            ⚠️ <b>信号仍在验证期</b>:迄今只评判了 <b>{ov?.n ?? 0}/30</b> 笔方向判断,样本太小、
            还<b>无法证明这套信号能赚钱</b>。请把它当观察工具,<b>不要据此加仓或重仓</b>——
            等已评判 ≥30 笔且胜率/模拟收益稳定为正,再谈放大。
          </p>
        </section>
      )}

      {/* 🌐 大盘环境（机械信号看不见的大盘风向）*/}
      {scan?.market && (
        <section className={`rounded-2xl border p-3.5 shadow-sm ${
          scan.market.regime === "risk_on" ? "border-emerald-200 bg-emerald-50/50"
          : scan.market.regime === "risk_off" ? "border-red-200 bg-red-50/50"
          : "border-amber-200 bg-amber-50/40"}`}>
          <div className="flex items-center gap-2 flex-wrap text-[13px]">
            <span>🌐</span>
            <span className="font-semibold text-gray-800">
              {scan.market.regime === "risk_on" ? "大盘顺风" : scan.market.regime === "risk_off" ? "大盘逆风" : "大盘中性"}
            </span>
            <span className="text-[11px] font-mono text-gray-500">
              VIX {scan.market.vix} · SPY {(scan.market.spy_vs_50dma * 100).toFixed(1)}% · QQQ {(scan.market.qqq_vs_50dma * 100).toFixed(1)}% vs 50日线
            </span>
          </div>
          <p className="mt-1 text-[12px] leading-relaxed text-gray-600">{scan.market.note}</p>
        </section>
      )}

      {/* 🧺 多买入信号的组合相关性提醒 */}
      {scan?.concurrent_buys?.note && (
        <section className="rounded-2xl border border-indigo-200 bg-indigo-50/50 p-3.5 shadow-sm">
          <p className="text-[12px] leading-relaxed text-indigo-800">
            🧺 <b>组合提醒</b>:{scan.concurrent_buys.note}
          </p>
        </section>
      )}

      {/* 📣 今日看点（AI 大白话点评）*/}
      {scan?.commentary && (
        <section className="rounded-2xl border border-indigo-200 bg-gradient-to-br from-indigo-50 to-blue-50/40 p-4 shadow-sm">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-sm">📣</span>
            <span className="text-xs font-semibold text-indigo-700">今日看点</span>
          </div>
          <p className="text-[13px] leading-relaxed text-gray-700 whitespace-pre-line">{scan.commentary}</p>
        </section>
      )}

      {/* 📊 模拟战绩 */}
      {scan?.paper && <PaperPanel p={scan.paper} />}

      {/* 状态 / 卡片 */}
      {loading ? (
        <div className="text-sm text-[#525461] flex items-center gap-2 px-1">
          <span className="inline-block w-2.5 h-2.5 rounded-full bg-[#006FFF] animate-pulse" /> 读取扫描结果…
        </div>
      ) : !scan || scan.results.length === 0 ? (
        <div className="bg-white rounded-2xl border border-[#EDEDF0] p-8 text-center text-sm text-gray-400">
          尚未生成扫描 — 运行一次 <code className="font-mono bg-gray-100 px-1 rounded">publish.py</code>(或等每日自动任务)后这里就会有数据。
        </div>
      ) : (
        <div className={`grid grid-cols-1 md:grid-cols-2 gap-3 ${busy ? "opacity-50 pointer-events-none" : ""}`}>
          {scan.results.map(r => (
            <ScanCard key={r.ticker} r={r} editable={WATCH_EDITABLE} onRemove={handleRemove} />
          ))}
        </div>
      )}

      <footer className="text-center text-[10px] text-gray-400 pb-4 leading-relaxed">
        🔭 自选扫描 · 这些是高波动投机性标的的<b>扫描候选,非买入建议</b> · 系统只提示"哪只 / 什么价 / 什么时候"接近 setup,买卖与仓位由你决定 · 非投资建议
      </footer>
    </main>
  );
}
