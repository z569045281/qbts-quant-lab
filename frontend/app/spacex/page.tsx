"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getSpacexState, postSpacexRefresh, WATCH_EDITABLE,
  type SpacexState, type SpacexDecision,
} from "../_lib/data";

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
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    const s = await getSpacexState();
    setState(s);
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function regenerate() {
    if (running) return;
    setRunning(true);
    setMsg("正在调用 DeepSeek 重新生成…(可能 30–60 秒)");
    const res = await postSpacexRefresh();
    if (res.ok) {
      setMsg(res.decision
        ? `✓ 完成:${res.decision.action} · 信心 ${res.decision.conviction}/10`
        : "✓ 数据已刷新,但决策为空(云端未配 DeepSeek 密钥或本次调用失败)");
      await load();
    } else {
      setMsg(`✗ 失败:${res.error ?? "未知错误"}`);
    }
    setRunning(false);
  }

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
        {WATCH_EDITABLE && (
          <div className="mt-3 flex items-center gap-2 flex-wrap">
            <button
              onClick={regenerate} disabled={running}
              className="px-3.5 py-1.5 rounded-lg bg-[#006FFF] text-white text-xs font-semibold
                         disabled:opacity-50 hover:bg-[#0060DB] transition-colors inline-flex items-center gap-1.5">
              {running
                ? <><span className="inline-block w-2 h-2 rounded-full bg-white/90 animate-pulse" /> 生成中…</>
                : <>🔄 立即用 DeepSeek 重新生成</>}
            </button>
            {msg && <span className="text-[11px] text-slate-300/90 font-mono">{msg}</span>}
          </div>
        )}
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

          {/* 抢先量导语 */}
          {(state.options || state.intraday || state.peer_prior) && (
            <div className="text-[11px] text-gray-500 leading-relaxed px-1">
              🎯 <b>抢先量三条腿</b>:新 IPO 日线太短、指标失真,下面三块都<b>不吃日线历史长度</b> ——
              期权是市场对未来的前瞻预测、盘中 1h 已有足够数据、同业借长历史估波动。
            </div>
          )}

          {/* ① 期权隐含波动(前瞻,头号腿)*/}
          {state.options?.term && state.options.term.length > 0 && (
            <section className="rounded-2xl border border-violet-200 bg-violet-50/50 p-4 shadow-sm">
              <div className="text-xs font-bold text-violet-800 mb-1">🔮 ① 期权隐含波动 · 市场对未来的预测(零历史需求)</div>
              <p className="text-[11px] text-violet-700/80 mb-3 leading-relaxed">
                ATM 跨式给出的<b>预期波动</b>就是市场预测的幅度。看期限结构的跳变 —— 覆盖 8/6 事件的到期被显著抬高,
                就是解禁+财报的溢价被定价了。<b>这是幅度、不是方向</b>。
              </p>
              <div className="space-y-1.5">
                {state.options.term.map((x, i) => {
                  const isEvent = state.options?.event_expiry?.expiry === x.expiry;
                  return (
                    <div key={i} className={`flex items-center gap-2 text-[12px] rounded-lg px-2.5 py-1.5 ${
                      isEvent ? "bg-rose-100 border border-rose-200" : "bg-white/70"}`}>
                      <span className="font-mono text-gray-500 w-24 shrink-0">{x.expiry}</span>
                      <span className="text-[10px] text-gray-400 w-14 shrink-0">还{x.dte ?? "?"}天</span>
                      <span className={`font-mono font-bold ${isEvent ? "text-rose-600" : "text-violet-700"}`}>
                        ±{x.expected_move_pct != null ? (x.expected_move_pct * 100).toFixed(1) : "—"}%
                      </span>
                      <span className="text-[10px] text-gray-400">IV {x.atm_iv != null ? (x.atm_iv * 100).toFixed(0) : "—"}%</span>
                      {isEvent && <span className="ml-auto text-[10px] font-bold text-rose-600">← 覆盖 8/6 事件</span>}
                    </div>
                  );
                })}
              </div>
              {state.options.skew_put_minus_call != null && (
                <div className="mt-2 text-[11px] text-gray-600">
                  IV 偏斜(看跌−看涨)= <b className="font-mono">{(state.options.skew_put_minus_call * 100).toFixed(0)} 点</b>
                  {" · "}{state.options.skew_put_minus_call > 0.01 ? "下行恐惧买盘更重" : state.options.skew_put_minus_call < -0.01 ? "偏追涨" : "基本对称"}
                </div>
              )}
            </section>
          )}

          {/* ② 盘中 1h(可靠技术面)*/}
          {state.intraday && (
            <section className="rounded-2xl border border-sky-200 bg-sky-50/50 p-4 shadow-sm">
              <div className="text-xs font-bold text-sky-800 mb-1">
                ⏱️ ② 盘中 {state.intraday.interval} 时间框 · 指标已预热可用({state.intraday.n_bars} 根 vs 日线 {dd?.n_bars})
              </div>
              {/* 对比杀手锏:日线 RSI vs 盘中 RSI */}
              {dd?.rsi14 != null && state.intraday.rsi14 != null && (
                <p className="text-[11px] text-sky-700/80 mb-3 leading-relaxed">
                  同一个 RSI,日线 <b className="font-mono">{dd.rsi14}</b>(仅 20 根、预热失真)vs 盘中
                  <b className="font-mono"> {state.intraday.rsi14}</b>(可信)—— 差这么多就是为什么别信日线。
                </p>
              )}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {[
                  { k: "盘中 RSI14", v: state.intraday.rsi14 != null ? `${state.intraday.rsi14}` : "—",
                    sub: state.intraday.rsi14 == null ? "" : state.intraday.rsi14 >= 70 ? "超买" : state.intraday.rsi14 <= 30 ? "超卖" : "中性" },
                  { k: "盘中 ATR", v: pct(state.intraday.atr_pct), sub: `${usd(state.intraday.atr14)}/时` },
                  { k: "vs 20周期线", v: state.intraday.above_sma20 == null ? "—" : state.intraday.above_sma20 ? "上方" : "下方", sub: usd(state.intraday.sma20) },
                  { k: "vs 锚定VWAP", v: state.intraday.above_vwap == null ? "—" : state.intraday.above_vwap ? "上方" : "下方", sub: usd(state.intraday.vwap) },
                ].map(x => (
                  <div key={x.k} className="bg-white/70 rounded-lg px-2.5 py-2">
                    <div className="text-[10px] text-gray-400">{x.k}</div>
                    <div className="font-mono font-semibold text-gray-800 text-sm">{x.v}</div>
                    {x.sub && <div className="text-[9px] text-gray-400 font-mono">{x.sub}</div>}
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* ③ 同业波动先验 */}
          {state.peer_prior?.blended_vol != null && (
            <section className="rounded-2xl border border-teal-200 bg-teal-50/50 p-4 shadow-sm">
              <div className="text-xs font-bold text-teal-800 mb-1">🛰️ ③ 同业波动先验 · 收缩估计(设仓位/止损宽度用)</div>
              <div className="flex items-baseline gap-2 flex-wrap mb-2">
                <span className="text-[11px] text-gray-500">自算 {pct(state.peer_prior.spcx_own_vol, 0)}(样本短)</span>
                <span className="text-gray-300">+</span>
                <span className="text-[11px] text-gray-500">纯太空同业 {pct(state.peer_prior.peer_prior, 0)}</span>
                <span className="text-gray-300">→</span>
                <span className="text-sm font-bold font-mono text-teal-700">可用波动 {pct(state.peer_prior.blended_vol, 0)}</span>
                <span className="text-[10px] text-gray-400">(收缩权重 {state.peer_prior.shrink_weight})</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {state.peer_prior.peers.map(p => (
                  <span key={p.ticker} className={`text-[10px] px-2 py-0.5 rounded-full font-mono ${
                    p.pure ? "bg-teal-100 text-teal-700" : "bg-gray-100 text-gray-500"}`}>
                    {p.ticker} {(p.vol * 100).toFixed(0)}%
                  </span>
                ))}
              </div>
              <p className="mt-2 text-[10px] text-gray-400 leading-relaxed">
                自己只有 {state.peer_prior.n_bars} 根日线 → 主要借同业;bar 越多、权重越交还给自己(纯太空同业=实心)。
              </p>
            </section>
          )}

          {/* 技术读数(日线,薄数据参考)*/}
          {dd && (
            <section className="rounded-2xl border border-[#EDEDF0] bg-white p-4 shadow-sm">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs font-semibold text-gray-700">📊 日线技术读数(薄数据·仅参考)</span>
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
