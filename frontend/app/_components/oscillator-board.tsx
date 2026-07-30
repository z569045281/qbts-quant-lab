"use client";

import type { OscBand, OscRow, Oscillators } from "../_lib/data";

/* ─────────────────────────────────────────────────────────────────────────
   🌡️ 超买 / 超卖状态板。

   用户 2026-07-30:"为什么不显示当前的超买还是超卖,感觉很有用啊"。读数一直
   在算(WaveTrend / 特调%R / RSI2 / RSI14 / NW 包络),但只以"距扳机多远"的形式
   零散露过面,没人回答"现在贵还是便宜"这句话本身。

   形式上的两个决定:
   ① **一根轴,全表共用**:左=便宜(超卖)、右=贵(超买)。各行的原生数字与原生
      阈值照原样标出(刻度线),不做归一化篡改。
   ② **不给合成分数**。一个 0–100「超卖分」看起来就是信号,而它没有前向验证。
      只陈列 + 数个数(几项超卖 / 几项偏冷)。

   配色:diverging = 两极 + 中性灰(emerald #059669 ↔ #F03A3E,浅色底上六项
   色觉检查全过:正常视觉 ΔE 32.5 / deutan 9.6)。**颜色永不单独承载信息** ——
   每行都带文字档位(超卖/偏冷/中性/偏热/超买)与原生数值。
   ───────────────────────────────────────────────────────────────────────── */

const BAND: Record<OscBand, { dot: string; chip: string; label: string }> = {
  os:   { dot: "bg-emerald-600", chip: "bg-emerald-100 text-emerald-800", label: "超卖" },
  cool: { dot: "bg-emerald-400", chip: "bg-emerald-50 text-emerald-700",  label: "偏冷" },
  mid:  { dot: "bg-gray-400",    chip: "bg-gray-100 text-gray-600",       label: "中性" },
  warm: { dot: "bg-red-300",     chip: "bg-red-50 text-red-700",          label: "偏热" },
  ob:   { dot: "bg-[#F03A3E]",   chip: "bg-red-100 text-red-800",         label: "超买" },
};

const STATE_CHIP: Record<Oscillators["state"], string> = {
  cold: "bg-emerald-100 text-emerald-800",
  cool: "bg-emerald-50 text-emerald-700",
  mid:  "bg-gray-100 text-gray-600",
  warm: "bg-red-50 text-red-700",
  hot:  "bg-red-100 text-red-800",
};

/** 驾驶舱里的一行:一眼给出档位,细节在「结构」标签 */
export function OscillatorStrip({ osc, onOpen }: { osc: Oscillators; onOpen: () => void }) {
  const ext = osc.rows.reduce((a, r) =>
    Math.min(r.pos, 1 - r.pos) < Math.min(a.pos, 1 - a.pos) ? r : a, osc.rows[0]);
  return (
    <div className="bg-white rounded-2xl shadow-[0_1px_2px_rgba(0,0,0,0.05)] px-4 py-2
                    flex items-center gap-x-3 gap-y-1 flex-wrap text-[12px]">
      <span className="text-[11px] font-semibold text-[#525461] uppercase tracking-wider shrink-0">
        🌡️ 超买/超卖
      </span>
      <span className={`px-2 py-0.5 rounded-full font-bold ${STATE_CHIP[osc.state]}`}>
        {osc.state_cn}
      </span>
      {/* 全表共用的那根轴,压成一条:每行一个点,一眼看出扎堆在哪半边 */}
      <span className="relative h-3 flex-1 min-w-[140px] max-w-[280px]" aria-hidden>
        <span className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1 rounded-full
                         bg-gradient-to-r from-emerald-100 via-gray-100 to-red-100" />
        <span className="absolute top-1/2 -translate-y-1/2 w-px h-2 bg-gray-300" style={{ left: "50%" }} />
        {osc.rows.map(r => (
          <span key={r.key} title={`${r.name} ${r.value_cn}(${r.band_cn})`}
                className={`absolute top-1/2 w-2 h-2 -translate-y-1/2 -translate-x-1/2 rounded-full
                            ring-2 ring-white ${BAND[r.band].dot}`}
                style={{ left: `${r.pos * 100}%` }} />
        ))}
      </span>
      <span className="text-[#525461] tabular-nums">
        {osc.n_os} 超卖 · {osc.n_cool} 偏冷 · {osc.n_warm} 偏热 · {osc.n_ob} 超买
      </span>
      {ext && (
        <span className="text-gray-400">
          最极端 <b className="text-gray-600">{ext.name} {ext.value_cn}</b>
        </span>
      )}
      <span className={`shrink-0 ${osc.fired.length ? "text-emerald-700 font-semibold" : "text-gray-400"}`}>
        {osc.fired.length ? `扳机已触发:${osc.fired.join("、")}` : "无在册扳机触发"}
      </span>
      <button onClick={onOpen}
              className="ml-auto shrink-0 text-[11px] text-[#006FFF] hover:underline
                         focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#006FFF]">
        逐项看 ›
      </button>
    </div>
  );
}

function Row({ r }: { r: OscRow }) {
  const b = BAND[r.band];
  return (
    <div className="py-2 border-b border-[#F0F0F2] last:border-0">
      <div className="flex items-baseline gap-2 flex-wrap mb-1.5">
        <span className="text-[12px] font-medium text-gray-800">{r.name}</span>
        <span className="font-mono text-[13px] font-semibold text-gray-900 tabular-nums">{r.value_cn}</span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${b.chip}`}>{b.label}</span>
        {r.fired === true && (
          <span className="text-[10px] px-1.5 py-0.5 rounded font-bold bg-emerald-600 text-white">
            扳机已触发
          </span>
        )}
        <span className="ml-auto text-[10px] text-gray-400">{r.source}</span>
      </div>
      {/* 轨道:左便宜右贵。刻度线是该指标**自己的**阈值,不是统一分档 */}
      <div className="relative h-4">
        <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1.5 rounded-full
                        bg-gradient-to-r from-emerald-100 via-gray-100 to-red-100" />
        {r.marks.map(m => (
          <div key={m.label} className="absolute top-0 h-4 flex flex-col items-center"
               style={{ left: `${m.at * 100}%` }}>
            <div className="w-px h-2.5 bg-gray-400/70" />
            <span className="text-[8px] text-gray-400 leading-none whitespace-nowrap
                             absolute top-2.5 -translate-x-1/2 left-0">{m.label}</span>
          </div>
        ))}
        <div title={`${r.name} ${r.value_cn}(${b.label})`}
             className={`absolute top-1/2 w-2.5 h-2.5 -translate-y-1/2 -translate-x-1/2 rounded-full
                         ring-2 ring-white shadow-sm ${b.dot}`}
             style={{ left: `${r.pos * 100}%` }} />
      </div>
      <div className="mt-2.5 text-[10px] text-gray-400 leading-snug">{r.threshold_cn}</div>
      {r.hint_cn && (
        <div className="mt-1 text-[11px] text-emerald-700 bg-emerald-50 rounded px-2 py-1 leading-snug">
          → {r.hint_cn}
        </div>
      )}
    </div>
  );
}

/** 「结构」标签里的完整卡 */
export function OscillatorBoard({ osc }: { osc: Oscillators }) {
  return (
    <div className="bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] p-5">
      <div className="flex items-baseline justify-between gap-2 mb-1 flex-wrap">
        <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
          🌡️ 超买 / 超卖逐项
        </span>
        <span className="flex items-center gap-2">
          <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold ${STATE_CHIP[osc.state]}`}>
            {osc.state_cn}
          </span>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 font-medium">
            零决策权
          </span>
        </span>
      </div>
      <p className="text-[12px] text-[#525461] leading-relaxed">{osc.summary_cn}</p>
      <p className={`text-[12px] leading-relaxed mb-2 font-medium ${
        osc.fired.length ? "text-emerald-700" : "text-[#B45309]"}`}>
        {osc.caveat_cn}
      </p>
      <div className="flex justify-between text-[10px] text-gray-400 mb-1">
        <span>← 便宜(超卖)</span><span>贵(超买) →</span>
      </div>
      {osc.rows.map(r => <Row key={r.key} r={r} />)}
      <div className="mt-3 text-[10px] text-gray-400 bg-[#F6F6F8] rounded-lg px-2.5 py-2 leading-relaxed">
        ⓘ {osc.discipline_cn}
      </div>
      {/* 色觉/打印/强制配色下颜色可能失效 —— 表格视图保证信息不丢 */}
      <details className="group mt-2">
        <summary className="cursor-pointer list-none [&::-webkit-details-marker]:hidden
                            text-[11px] text-[#006FFF] hover:underline">
          <span className="group-open:hidden">看表格版(不依赖颜色) ›</span>
          <span className="hidden group-open:inline">收起表格</span>
        </summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-gray-400 text-left">
                <th className="py-1 pr-3 font-medium">读数</th>
                <th className="py-1 pr-3 font-medium">当前值</th>
                <th className="py-1 pr-3 font-medium">档位</th>
                <th className="py-1 font-medium">自己的阈值</th>
              </tr>
            </thead>
            <tbody>
              {osc.rows.map(r => (
                <tr key={r.key} className="border-t border-[#F0F0F2]">
                  <td className="py-1 pr-3 text-gray-700">{r.name}</td>
                  <td className="py-1 pr-3 font-mono text-gray-900 tabular-nums">{r.value_cn}</td>
                  <td className="py-1 pr-3 text-gray-700">{r.band_cn}</td>
                  <td className="py-1 text-gray-500">{r.threshold_cn}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
