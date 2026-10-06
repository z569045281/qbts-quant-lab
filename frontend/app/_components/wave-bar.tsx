"use client";

/* 🌊 浪潮状态栏(2026-10-06 用户点单:「QBTS 像海浪,一波一波,来得猛,拍到沙滩上就回调」)。
   后端 wave.py 用收盘价 20% zigzag 切浪;这里按**实时价**判断这一浪走到哪、有没有越过转折线。
   ⚠️ 地图,不是买卖信号:回测里浪的位置对之后涨跌没有稳定预测力;高抛低吸已判死。 */

import type { WaveState, WaveLegStats } from "../_lib/data";

const pct = (v: number, d = 1) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(d)}%`;

/** 当前幅度在历史同向浪里的分位:上涨浪 = 比多少比例的浪涨得多;回落浪 = 比多少比例的浪跌得深 */
function rank(stats: WaveLegStats | null, mag: number, up: boolean): number | null {
  if (!stats || stats.mags.length === 0) return null;
  const k = stats.mags.filter(m => (up ? m < mag : m > mag)).length;
  return k / stats.mags.length;
}

export function WaveBar({ wave, price, eq }: {
  wave: WaveState; price: number; eq?: (lvl: number) => string;
}) {
  const th = wave.threshold;
  const c = wave.current;
  if (c.trend === "none" || !price) return null;

  // 按实时价推进状态:越过 20% 转折线就翻浪
  let trend = c.trend;
  let anchor = c.anchor_price;
  let ext = c.trend === "up" ? Math.max(c.extreme_price, price) : Math.min(c.extreme_price, price);
  let flipped = false;
  if (trend === "down" && price >= ext * (1 + th)) {
    trend = "up"; anchor = ext; ext = price; flipped = true;
  } else if (trend === "up" && price <= ext * (1 - th)) {
    trend = "down"; anchor = ext; ext = price; flipped = true;
  }
  const up = trend === "up";
  const mag = price / anchor - 1;                 // 这一浪从起点走了多少
  const fromExt = price / ext - 1;                // 离本浪极值多远
  const confirm = up ? ext * (1 - th) : ext * (1 + th);
  const stats = up ? wave.legs.up : wave.legs.down;
  const r = rank(stats, mag, up);
  const daysRank = stats && !flipped
    ? stats.days.filter(d => d < c.days).length / stats.days.length : null;

  // 刻度:把当前幅度放在历史同向浪的 25/50/75 分位旁边
  const scaleMax = up ? Math.max(1.5, mag * 1.1) : Math.min(-0.6, mag * 1.1);
  const pos = (v: number) => `${Math.min(100, Math.max(0, (v / scaleMax) * 100))}%`;

  return (
    <details className={`group min-w-0 rounded-card border px-4 py-2.5 ${
      up ? "border-sky-200 bg-sky-50/60" : "border-amber-200 bg-amber-50/50"}`}>
      <summary className="cursor-pointer list-none [&::-webkit-details-marker]:hidden">
        <div className="flex items-center gap-x-3 gap-y-1 flex-wrap text-body">
          <span className={`text-meta px-2 py-0.5 rounded-full font-semibold ${
            up ? "bg-sky-600 text-on-solid" : "bg-amber-500 text-amber-950"}`}>
            {up ? "🌊 上涨浪" : "🏖️ 回落浪 · 退潮"}
          </span>
          <span className="text-gray-800">
            {up
              ? <>从浪底 <b className="font-mono">${anchor.toFixed(2)}</b> 涨了 <b className="font-mono text-sky-700">{pct(mag)}</b></>
              : <>从浪尖 <b className="font-mono">${anchor.toFixed(2)}</b> 回落 <b className="font-mono text-amber-700">{pct(mag)}</b></>}
            {r != null && (
              <span className="text-ink-muted"> · {up ? `比 ${(r * 100).toFixed(0)}% 的历史上涨浪涨得多` : `比 ${(r * 100).toFixed(0)}% 的历史回落浪跌得深`}</span>
            )}
            {!flipped && <span className="text-ink-muted"> · 第 {c.days} 个交易日{daysRank != null && daysRank >= 0.75 ? "(比多数浪都长)" : ""}</span>}
          </span>
          <span className="text-meta text-ink-faint">
            {up ? "跌回" : "反弹到"} <span className="font-mono">${confirm.toFixed(2)}</span>
            {eq ? ` ${eq(confirm)}` : ""} 才算{up ? "这一浪结束" : "新一浪开始"}
          </span>
          <span className="ml-auto text-meta text-brand group-open:hidden">展开 ›</span>
        </div>
      </summary>

      <div className="mt-3 space-y-3 text-body text-gray-700">
        {/* 刻度条 */}
        {stats && (
          <div>
            <div className="relative h-2.5 rounded-full bg-white border border-hairline">
              <div className={`absolute top-0 h-full rounded-full ${up ? "bg-sky-300" : "bg-amber-300"}`}
                // 色块从「离 0 较近的四分位」画到「较远的四分位」(回落浪的 p75 比 p25 浅)
                style={{ left: pos(up ? stats.mag_p25 : stats.mag_p75),
                         width: `calc(${pos(up ? stats.mag_p75 : stats.mag_p25)} - ${pos(up ? stats.mag_p25 : stats.mag_p75)})` }} />
              <div className="absolute top-[-3px] h-4 w-0.5 bg-gray-500" style={{ left: pos(stats.mag_median) }} />
              <div className={`absolute top-[-4px] h-[18px] w-[18px] -ml-[9px] rounded-full border-2 border-white ${up ? "bg-sky-600" : "bg-amber-600"}`}
                style={{ left: pos(mag) }} title={`现在 ${pct(mag)}`} />
            </div>
            <div className="mt-1 flex justify-between text-meta text-ink-faint font-mono">
              <span>0%</span>
              <span>{pct(scaleMax, 0)}</span>
            </div>
            <div className="text-meta text-ink-faint">色块 = 历史一半的浪落在这里 · 竖线 = 中位 {pct(stats.mag_median, 0)} · 圆点 = 现在</div>
          </div>
        )}

        <div className="grid gap-2 sm:grid-cols-2 text-meta">
          {wave.legs.up && (
            <div className="rounded-inner bg-white/70 px-2.5 py-1.5">
              🌊 上涨浪 {wave.legs.up.n} 个:中位 <b>{pct(wave.legs.up.mag_median, 0)}</b>(一半在 {pct(wave.legs.up.mag_p25, 0)}~{pct(wave.legs.up.mag_p75, 0)}),
              只用 <b>{wave.legs.up.days_median} 天</b> —— 来得又快又猛
            </div>
          )}
          {wave.legs.down && (
            <div className="rounded-inner bg-white/70 px-2.5 py-1.5">
              🏖️ 回落浪 {wave.legs.down.n} 个:中位 <b>{pct(wave.legs.down.mag_median, 0)}</b>(一半在 {pct(wave.legs.down.mag_p75, 0)}~{pct(wave.legs.down.mag_p25, 0)}),
              花 <b>{wave.legs.down.days_median} 天</b> —— 退得慢
            </div>
          )}
        </div>

        {/* flex-wrap:每个价位自己不断行,但价位之间可以换行 —— 否则手机上整张卡被撑宽 */}
        <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-meta">
          <span className="text-ink-faint">最近的浪:</span>
          {wave.pivots.slice(-6).map((p, i) => (
            <span key={i} className="whitespace-nowrap font-mono">
              {p.kind === "peak" ? "🔺" : "🔻"}{p.date.slice(5)} ${p.price.toFixed(2)}
            </span>
          ))}
          <span className="whitespace-nowrap font-mono">→ 现在 ${price.toFixed(2)}({up ? "离浪尖" : "离浪底"} {pct(fromExt)})</span>
        </div>

        <p className="text-meta text-ink-muted">
          切法:收盘价反向走满 {Math.round(th * 100)}% 才算一浪结束(数据自 {wave.since})。⚠️ {wave.note}
        </p>
      </div>
    </details>
  );
}
