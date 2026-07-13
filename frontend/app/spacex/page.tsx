"use client";

import { useEffect, useState } from "react";
import { getSpacexState, type SpacexState, type SpacexDecision } from "../_lib/data";

/* ─────────────────────────────────────────────────────────────────────────
   🚀 SpaceX (SPCX) 第二仪表盘 — 决策**只由 DeepSeek V4 Pro 生成**(不用 Fable)。
   SPCX 是 2026 新 IPO(仅 ~20 根日线),技术指标预热失真;2026-08-06 首次财报+
   首次锁定期解禁是压倒性近期风险 → 页面把事件横幅顶在决策下方,技术位标注"薄数据"。
   数据来自 Supabase spacex_state(每日云端 publish 用 DeepSeek 刷新)。
   ───────────────────────────────────────────────────────────────────────── */

const ACT: Record<string, { cn: string; border: string; bg: string; chip: string; text: string }> = {
  BUY:    { cn: "买入",    border: "border-emerald-300", bg: "bg-emerald-50",  chip: "bg-emerald-500", text: "text-emerald-700" },
  HOLD:   { cn: "持有观望", border: "border-amber-300",   bg: "bg-amber-50",    chip: "bg-amber-500",   text: "text-amber-700"   },
  REDUCE: { cn: "减仓/回避", border: "border-rose-300",    bg: "bg-rose-50",     chip: "bg-rose-500",    text: "text-rose-700"    },
};

const pct = (n: number | null | undefined, d = 1) =>
  typeof n === "number" && isFinite(n) ? `${n >= 0 ? "+" : ""}${(n * 100).toFixed(d)}%` : "—";
const usd = (n: number | null | undefined) =>
  typeof n === "number" && isFinite(n) ? `$${n.toFixed(2)}` : "—";

function ConvictionMeter({ v }: { v: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex gap-0.5">
        {Array.from({ length: 10 }).map((_, i) => (
          <span key={i} className={`h-3 w-1.5 rounded-sm ${i < v ? "bg-[#006FFF]" : "bg-gray-200"}`} />
        ))}
      </div>
      <span className="text-xs font-mono font-semibold text-gray-600">{v}/10</span>
    </div>
  );
}

function DecisionHero({ d }: { d: SpacexDecision }) {
  const a = ACT[d.action] ?? ACT.HOLD;
  return (
    <section className={`rounded-2xl border ${a.border} ${a.bg} p-5 shadow-sm`}>
      <div className="flex items-center gap-3 flex-wrap">
        <span className={`px-3 py-1 rounded-full text-white text-sm font-bold ${a.chip}`}>{a.cn}</span>
        <ConvictionMeter v={d.conviction} />
        <span className="ml-auto text-[10px] px-2 py-0.5 rounded bg-black/5 text-gray-500 font-mono">
          🧠 {d.model}
        </span>
      </div>
      <p className="mt-3 text-[15px] font-semibold text-gray-900 leading-relaxed">{d.summary}</p>

      {/* 入场/止损/目标/RR */}
      {(d.entry || d.stop || d.target) && (
        <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2">
          {[
            { k: "入场", v: usd(d.entry), c: "text-gray-900" },
            { k: "止损", v: usd(d.stop), c: "text-rose-600" },
            { k: "目标", v: usd(d.target), c: "text-emerald-600" },
            { k: "盈亏比", v: d.rr ? `${d.rr}` : "—", c: "text-[#006FFF]" },
          ].map(x => (
            <div key={x.k} className="bg-white/70 rounded-lg px-2.5 py-2">
              <div className="text-[10px] text-gray-400">{x.k}</div>
              <div className={`font-mono font-bold text-sm ${x.c}`}>{x.v}</div>
            </div>
          ))}
        </div>
      )}
      {d.horizon && <div className="mt-2 text-[11px] text-gray-500">时间跨度:{d.horizon}</div>}

      {/* drivers */}
      {d.drivers?.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {d.drivers.map((dr, i) => {
            const s = dr.stance === "bull" ? "🟢" : dr.stance === "bear" ? "🔴" : "⚪";
            return (
              <div key={i} className="flex gap-2 text-[12px]">
                <span>{s}</span>
                <span className="font-semibold text-gray-700 shrink-0">{dr.factor}</span>
                <span className="text-gray-500">{dr.note}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* lockup note — 单独强调 */}
      {d.lockup_note && (
        <div className="mt-3 rounded-lg bg-white/70 border border-amber-200 px-3 py-2">
          <div className="text-[11px] font-semibold text-amber-700">🔓 对 8/6 解禁的判断</div>
          <p className="text-[12px] text-gray-600 mt-0.5 leading-relaxed">{d.lockup_note}</p>
        </div>
      )}

      {/* risks */}
      {d.risks?.length > 0 && (
        <div className="mt-3">
          <div className="text-[11px] font-semibold text-gray-500 mb-1">⚠️ 风险</div>
          <ul className="space-y-0.5">
            {d.risks.map((r, i) => (
              <li key={i} className="text-[12px] text-gray-600 flex gap-1.5"><span className="text-rose-400">·</span>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {d.system_notes && d.system_notes.length > 0 && (
        <details className="mt-3 text-[11px]">
          <summary className="cursor-pointer text-gray-400 select-none">🔍 模型自检 ▾</summary>
          <ul className="mt-1 space-y-0.5">
            {d.system_notes.map((n, i) => <li key={i} className="text-gray-500">· {n}</li>)}
          </ul>
        </details>
      )}
    </section>
  );
}

export default function SpacexPage() {
  const [state, setState] = useState<SpacexState | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let stop = false;
    (async () => { const s = await getSpacexState(); if (!stop) { setState(s); setLoading(false); } })();
    return () => { stop = true; };
  }, []);

  const dd = state?.data;
  const up = (dd?.today_change ?? 0) >= 0;

  return (
    <main className="max-w-[900px] mx-auto px-4 sm:px-6 py-5 sm:py-6 space-y-4">
      {/* 标题 */}
      <section className="rounded-2xl border border-[#EDEDF0] bg-gradient-to-br from-slate-900 to-slate-800 p-5 shadow-sm text-white">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-lg">🚀</span>
          <span className="text-base font-bold">SpaceX · SPCX</span>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/15 font-mono">DeepSeek 决策</span>
          {dd && (
            <span className="ml-auto flex items-baseline gap-2">
              <span className="text-xl font-mono font-bold">{usd(dd.price)}</span>
              <span className={`text-sm font-semibold ${up ? "text-emerald-400" : "text-rose-400"}`}>{pct(dd.today_change)}</span>
            </span>
          )}
        </div>
        <p className="mt-1.5 text-[11px] text-slate-300/80 leading-relaxed">
          独立于 QBTS 主仪表盘的第二块屏 · 决策由 <b>DeepSeek V4 Pro</b> 单独生成(不调用 Fable)
          {state?.generated_at && <> · 更新于 {state.generated_at.slice(0, 10)}</>}
        </p>
      </section>

      {loading ? (
        <div className="text-sm text-[#525461] flex items-center gap-2 px-1">
          <span className="inline-block w-2.5 h-2.5 rounded-full bg-[#006FFF] animate-pulse" /> 读取 SpaceX 决策…
        </div>
      ) : !state ? (
        <div className="rounded-2xl border border-[#EDEDF0] bg-white p-8 text-center">
          <p className="text-sm text-gray-500">尚未生成 SpaceX 数据。</p>
          <p className="mt-1 text-[11px] text-gray-400 leading-relaxed">
            需要先在 Supabase 建 <code className="font-mono bg-gray-100 px-1 rounded">spacex_state</code> 表
            (<code className="font-mono bg-gray-100 px-1 rounded">sql/spacex_migration.sql</code>),
            再等云端每日 publish 用 DeepSeek 刷新一次。
          </p>
        </div>
      ) : (
        <>
          {/* 决策 hero(或占位) */}
          {state.decision ? (
            <DecisionHero d={state.decision} />
          ) : (
            <section className="rounded-2xl border border-dashed border-gray-300 bg-white p-6 text-center">
              <p className="text-sm text-gray-600 font-medium">DeepSeek 决策待生成</p>
              <p className="mt-1 text-[11px] text-gray-400 leading-relaxed">
                数据已就绪,但决策为空 —— 云端尚未配 DeepSeek 密钥或本次调用失败。
                下次每日 publish 成功后这里会出现 DeepSeek 的判断。
              </p>
            </section>
          )}

          {/* 🔓 事件横幅(压倒性近期风险)*/}
          {state.catalysts?.length > 0 && (
            <section className="rounded-2xl border border-amber-300 bg-amber-50 p-4 shadow-sm">
              <div className="text-xs font-bold text-amber-800 mb-2">📅 事件日历(压倒机械技术位)· as of {state.catalyst_asof}</div>
              <div className="space-y-2">
                {state.catalysts.map((c, i) => (
                  <div key={i} className="flex gap-2 text-[12px]">
                    <span className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold h-fit ${
                      c.impact === "high" ? "bg-rose-500 text-white" : "bg-amber-400 text-amber-900"}`}>
                      {c.date}
                    </span>
                    <div>
                      <span className="font-semibold text-gray-800">{c.event}</span>
                      <p className="text-gray-600 leading-relaxed">{c.note}</p>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* 技术读数 */}
          {dd && (
            <section className="rounded-2xl border border-[#EDEDF0] bg-white p-4 shadow-sm">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs font-semibold text-gray-700">📊 技术读数</span>
                <span className="text-[10px] text-gray-400">{dd.n_bars} 根日线 · {dd.as_of}</span>
              </div>
              {dd.thin_data && (
                <div className="mb-3 rounded-lg bg-orange-50 border border-orange-200 px-3 py-2 text-[11px] text-orange-700 leading-relaxed">
                  ⚠️ 新 IPO 仅 {dd.n_bars} 根日线 —— RSI/均线尚在预热、<b>极不可靠</b>。以事件、价格结构与风险管理为准,别信技术指标的绝对值。
                </div>
              )}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {[
                  { k: "距历史高点", v: pct(dd.drawdown_from_ath, 0), sub: `高 ${usd(dd.ath)}` },
                  { k: "近5日", v: pct(dd.ret_5d), sub: `20日 ${pct(dd.ret_20d)}` },
                  { k: "RSI14", v: dd.rsi14 != null ? `${dd.rsi14}` : "—", sub: dd.thin_data ? "预热失真" : "" },
                  { k: "日波幅 ATR", v: pct(dd.atr_pct), sub: `${usd(dd.atr14)}` },
                  { k: "20日线", v: dd.sma20 != null ? usd(dd.sma20) : "数据不足", sub: dd.above_sma20 == null ? "" : dd.above_sma20 ? "现价上方" : "现价下方" },
                  { k: "52周区间", v: `${usd(dd.low_52w)}`, sub: `高 ${usd(dd.high_52w)}` },
                  { k: "今日量能", v: dd.vol_vs_20d != null ? `×${dd.vol_vs_20d}` : "—", sub: "vs 20日均量" },
                  { k: "历史区间", v: `${usd(dd.atl)}`, sub: `高 ${usd(dd.ath)}` },
                ].map(x => (
                  <div key={x.k} className="bg-gray-50/70 rounded-lg px-2.5 py-2">
                    <div className="text-[10px] text-gray-400">{x.k}</div>
                    <div className="font-mono font-semibold text-gray-800 text-sm">{x.v}</div>
                    {x.sub && <div className="text-[9px] text-gray-400 font-mono">{x.sub}</div>}
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* 新闻 */}
          {state.news?.length > 0 && (
            <section className="rounded-2xl border border-[#EDEDF0] bg-white p-4 shadow-sm">
              <div className="text-xs font-semibold text-gray-700 mb-2">📰 近3日头条(喂给 DeepSeek 的原料)</div>
              <ul className="space-y-1.5">
                {state.news.map((n, i) => (
                  <li key={i} className="text-[12px] text-gray-600 flex gap-1.5 leading-relaxed">
                    <span className="text-gray-300">·</span>
                    <span>{n.title}{n.source && <span className="text-gray-400"> — {n.source}</span>}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}

      <footer className="text-center text-[10px] text-gray-400 pb-4 leading-relaxed">
        🚀 SpaceX 第二仪表盘 · 决策仅由 DeepSeek 生成、<b>非投资建议</b> ·
        SPCX 为新 IPO,历史极短、波动巨大,锁定期解禁是重大供给风险 · 点位为情景锚定,确切顶底不可知
      </footer>
    </main>
  );
}
