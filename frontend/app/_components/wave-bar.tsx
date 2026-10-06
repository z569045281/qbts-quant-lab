"use client";

/* 🌊 浪潮状态栏(2026-10-06 用户点单:「QBTS 像海浪,一波一波,来得猛,拍到沙滩上就回调」)。
   后端 wave.py 用收盘价 20% zigzag 切浪;这里按**实时价**判断这一浪走到哪、有没有越过转折线。
   ⚠️ 地图,不是买卖信号:回测里浪的位置对之后涨跌没有稳定预测力;高抛低吸已判死。 */

import type { WaveState, WaveLegStats } from "../_lib/data";
import { WaveScene, type ScenePivot } from "./wave-scene";

const pct = (v: number, d = 1) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(d)}%`;

/** 当前幅度在历史同向浪里的分位:上涨浪 = 比多少比例的浪涨得多;回落浪 = 比多少比例的浪跌得深 */
function rank(stats: WaveLegStats | null, mag: number, up: boolean): number | null {
  if (!stats || stats.mags.length === 0) return null;
  const k = stats.mags.filter(m => (up ? m < mag : m > mag)).length;
  return k / stats.mags.length;
}

type Best = NonNullable<WaveState["best"]>;

/** 收起状态下的一行:回测冠军现在空仓还是持仓、什么价位会动 */
function BestLine({ best, price, eq }: { best: Best; price: number; eq?: (lvl: number) => string }) {
  const s = best.state;
  let text: string;
  if (s.in_position && s.entry != null) {
    text = `持有中:${s.entry_date?.slice(5)} 买在 $${s.entry.toFixed(2)}(${pct(price / s.entry - 1)})· 止盈 $${s.tp_price?.toFixed(2)} / 止损 $${s.stop_price?.toFixed(2)} / 还剩 ${s.days_left} 天`;
  } else if (s.trigger != null) {
    text = price >= s.trigger
      ? `空仓 · 现价已过 $${s.trigger.toFixed(2)},今天收盘守住就会买入`
      : `空仓 · 收盘站上 $${s.trigger.toFixed(2)}${eq ? ` ${eq(s.trigger)}` : ""} 会买入(还差 ${pct(s.trigger / price - 1)})`;
  } else {
    text = "空仓 · 等下一次回落后起浪";
  }
  return (
    <div className="mt-1 text-meta text-violet-700">
      🧪 回测冠军(过拟合,只观察):{text}
    </div>
  );
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

  // 动画用的转折点:已确认的 + 这一浪目前的极值(还没被反向 20% 确认,标「暂定」)
  const scenePivots: ScenePivot[] = wave.pivots.slice(-6).map(p => ({ ...p }));
  const lastDate = scenePivots[scenePivots.length - 1]?.date ?? "";
  if (flipped) {
    scenePivots.push({ kind: up ? "trough" : "peak", date: c.extreme_date, price: anchor });
  } else if (c.extreme_date > lastDate && Math.abs(c.extreme_price / price - 1) > 0.005) {
    scenePivots.push({ kind: up ? "peak" : "trough", date: c.extreme_date, price: c.extreme_price, tentative: true });
  }
  const sceneLabel = `QBTS 浪潮图:${up ? "上涨浪" : "回落浪"},从${up ? "浪底" : "浪尖"} $${anchor.toFixed(2)} ${up ? "涨了" : "回落"} ${pct(mag)};`
    + `${up ? "跌回" : "反弹到"} $${confirm.toFixed(2)} 才算${up ? "这一浪结束" : "新一浪开始"}。`
    + scenePivots.map(p => `${p.kind === "peak" ? "浪尖" : "浪底"} ${p.date} $${p.price.toFixed(2)}`).join(",");

  return (
    <details className="group min-w-0 rounded-card border border-hairline bg-surface px-4 py-3
                        shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)]">
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
        {wave.best && <BestLine best={wave.best} price={price} eq={eq} />}
        {scenePivots.length >= 2 && (
          <div className="mt-2.5 overflow-hidden rounded-inner">
            <WaveScene pivots={scenePivots} price={price} up={up} confirm={confirm}
              trigger={wave.best?.state.in_position ? null : wave.best?.state.trigger ?? null}
              ariaLabel={sceneLabel} />
          </div>
        )}
      </summary>

      <div className="mt-3 space-y-3 text-body text-gray-700">

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

        {wave.best && (
          <div className="rounded-inner border border-violet-200 bg-violet-50/60 px-2.5 py-2 text-meta text-gray-700">
            <div className="font-semibold text-violet-800">
              🧪 回测冠军(第四十六轮,11,200 组里事后挑出来的)
            </div>
            <div className="mt-0.5">
              规则:12% 浪「确认起浪」(从低点反弹 12%)当天收盘买 · 涨 +{Math.round(wave.best.params.tp * 100)}% 止盈
              · 跌 −{Math.round(wave.best.params.stop * 100)}% 止损 · 最多拿 {wave.best.params.tmax} 天
            </div>
            <div className="mt-0.5">
              {wave.best.study.window}:回测 <b>+{Math.round(wave.best.study.ret * 100).toLocaleString()}%</b>,
              一直拿着 +{Math.round(wave.best.study.bh * 100).toLocaleString()}%。
              <b className="text-down"> 但这是过拟合:</b>{wave.best.study.oos_note}。只观察,不是买卖建议,不推送。
            </div>
            {wave.best.trades.length > 0 && (
              <div className="mt-1.5 overflow-x-auto">
                <table className="w-full font-mono">
                  <thead className="text-ink-faint text-left"><tr><th className="pr-2">买入</th><th className="pr-2">卖出</th><th className="pr-2 text-right">结果</th><th>原因</th></tr></thead>
                  <tbody>
                    {[...wave.best.trades].reverse().map((t, i) => (
                      <tr key={i} className="border-t border-violet-100">
                        <td className="pr-2 whitespace-nowrap">{t.buy_date.slice(5)} ${t.buy.toFixed(2)}</td>
                        <td className="pr-2 whitespace-nowrap">{t.sell_date.slice(5)} ${t.sell.toFixed(2)}</td>
                        <td className={`pr-2 text-right ${t.ret >= 0 ? "text-emerald-600" : "text-down"}`}>{pct(t.ret)}</td>
                        <td className="font-sans">{t.why}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </details>
  );
}
