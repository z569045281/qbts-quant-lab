"use client";

import type { SecondBoard, SecondRecord } from "../_lib/data";

/* ─────────────────────────────────────────────────────────────────────────
   🔬 第二考场的卡片组件(/mu 页面用)。

   抽出来的理由不是"复用" —— 只有一个页面用它 —— 而是**可验证**:临时预览路由
   可以 import 这个真组件配假数据实截,而不是照抄一份 JSX 去截图(截拷贝等于
   没验证真东西)。2026-07-29 超买超卖卡就是照抄验证的,这次改进。
   ───────────────────────────────────────────────────────────────────────── */

const CALL = {
  up:   { chip: "bg-emerald-100 text-emerald-800", dot: "bg-emerald-600", cn: "看涨" },
  down: { chip: "bg-red-100 text-red-800",         dot: "bg-down",   cn: "看跌" },
} as const;

function pct(n: number | null | undefined, digits = 1): string {
  return typeof n === "number" && isFinite(n) ? `${n >= 0 ? "+" : ""}${(n * 100).toFixed(digits)}%` : "—";
}

/** 逐视界成绩表。技巧值 = 命中 − 基线,**这才是有没有本事的那一栏**。 */
function HorizonTable({ b }: { b: SecondBoard }) {
  const keys = ["1d", "2d", "3d", "5d"].filter(k => b.by_horizon[k]);
  if (keys.length === 0) {
    return (
      <p className="text-body text-gray-400 leading-relaxed">
        还没有到期的视界 —— 最快 1 个交易日后这里出现第一行。
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-body">
        <thead>
          <tr className="text-left text-gray-400 text-meta">
            <th className="py-1.5 pr-3 font-medium">视界</th>
            <th className="py-1.5 pr-3 font-medium">样本</th>
            <th className="py-1.5 pr-3 font-medium">命中</th>
            <th className="py-1.5 pr-3 font-medium">基线</th>
            <th className="py-1.5 pr-3 font-medium">技巧</th>
            <th className="py-1.5 font-medium">判决</th>
          </tr>
        </thead>
        <tbody>
          {keys.map(k => {
            const h = b.by_horizon[k];
            // 三态,不是两态:技巧恰好 0 = 与"无脑常喊一边"打平,既不是本事也不是
            // 反指 → 中性灰且不带 +/− 号(带号会读成"负的却标了个正")。
            const skillTone = h.skill_pp > 0 ? "text-emerald-700"
                            : h.skill_pp < 0 ? "text-down" : "text-gray-500";
            const skillTxt = h.skill_pp === 0 ? "0.0pp"
                           : `${h.skill_pp > 0 ? "+" : ""}${h.skill_pp.toFixed(1)}pp`;
            const mine = k === "2d" || k === "3d";
            return (
              <tr key={k} className={`border-t border-hairline ${mine ? "bg-brand/5" : ""}`}>
                <td className="py-1.5 pr-3 font-mono text-gray-800">
                  {k}
                  {mine && <span className="ml-1 text-meta text-brand">你的持有期</span>}
                </td>
                <td className="py-1.5 pr-3 tabular-nums text-gray-500">{h.n}</td>
                <td className="py-1.5 pr-3 tabular-nums text-gray-900 font-medium">
                  {(h.hit_rate * 100).toFixed(0)}%
                  <span className="text-gray-400 font-normal"> [{(h.ci95[0] * 100).toFixed(0)},{(h.ci95[1] * 100).toFixed(0)}]</span>
                </td>
                <td className="py-1.5 pr-3 tabular-nums text-gray-500">{(h.baseline * 100).toFixed(0)}%</td>
                <td className={`py-1.5 pr-3 tabular-nums font-semibold ${skillTone}`}>
                  {skillTxt}
                </td>
                <td className="py-1.5 text-gray-500">{h.verdict}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-meta text-gray-400 leading-relaxed">
        <b className="text-gray-600">基线</b>=这段时间里无脑天天喊同一边能拿到的命中率;
        <b className="text-gray-600">技巧</b>=命中 − 基线。<b className="text-[#B45309]">跟基线比,不跟 50% 比</b> ——
        单边下跌里光喊「跌」就能拿 83%,那不是本事。
      </p>
    </div>
  );
}

function RecordRow({ r }: { r: SecondRecord }) {
  const c = CALL[r.bold_call_5d];
  const fwd = r.horizons?.fwd_ret ?? {};
  const bold = r.horizons?.bold?.fable ?? {};
  return (
    <div className="border-b border-hairline last:border-0 py-2.5">
      <div className="flex items-center gap-2 flex-wrap text-body">
        {/* 显示 as_of(证据/价格属于哪根 bar,也是评分锚点),不是 date(哪天问的)。
            2026-09-02:后端锚点已改成 as_of,两者常差 1–3 天 —— 再按 date 标行,
            就会把日期摆在一串「从另一根 bar 起算」的收益旁边,正是后端刚修掉的错配。*/}
        <span className="font-mono text-gray-500" title={`表态问于 ${r.date}`}>
          {(r.as_of ?? r.date).slice(5)}
        </span>
        <span className={`px-1.5 py-0.5 rounded-inner font-bold text-meta ${c.chip}`}>{c.cn}</span>
        <span className="text-gray-400 tabular-nums">
          p{r.p_up_5d.toFixed(2)} · 信心{r.conviction} · ${r.price}
        </span>
        {r.technical_muted && (
          <span className="px-1.5 py-0.5 rounded-inner bg-amber-100 text-amber-800 text-meta font-medium">
            技术面熔断
          </span>
        )}
        <span className="ml-auto flex items-center gap-1.5">
          {["1d", "2d", "3d", "5d"].map(k => {
            const ok = bold[k];
            if (ok === undefined) return (
              <span key={k} className="text-meta text-gray-300 tabular-nums" title={`${k} 还没到期`}>
                {k}·—
              </span>
            );
            return (
              <span key={k}
                    title={`${k}: 实际 ${pct(fwd[k])} → ${ok ? "对" : "错"}`}
                    className={`text-meta tabular-nums font-medium ${ok ? "text-emerald-700" : "text-down"}`}>
                {k}{ok ? "✓" : "✗"}
              </span>
            );
          })}
        </span>
      </div>
      <p className="mt-1 text-meta text-ink-muted leading-snug">{r.why}</p>
    </div>
  );
}

export function Board({ b }: { b: SecondBoard }) {
  const c = CALL[b.latest.bold_call_5d];
  return (
    <div className="space-y-3">
      {/* 今天的表态 —— 这一页唯一的大字号 */}
      <section className="bg-surface rounded-card shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] p-5">
        <div className="flex items-baseline justify-between gap-2 flex-wrap mb-2">
          <span className="text-section font-semibold text-gray-900">
            🔬 {b.ticker} · 今日表态
          </span>
          <span className="flex items-center gap-2">
            <span className="text-meta px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 font-medium">
              纯测量 · 无动作
            </span>
            <span className="text-meta text-gray-400 font-mono"
                  title={`表态问于 ${b.latest.date}`}>
              数据截至 {b.latest.as_of ?? b.latest.date}
            </span>
          </span>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className={`w-3 h-3 rounded-full ${c.dot}`} aria-hidden />
          <span className="text-display font-bold text-gray-900">{c.cn}</span>
          <span className="text-card text-ink-muted tabular-nums">
            未来 5 日上涨概率 {(b.latest.p_up_5d * 100).toFixed(0)}% · 信心 {b.latest.conviction}/10
          </span>
          <span className="ml-auto text-card text-gray-400 tabular-nums">${b.latest.price}</span>
        </div>
        {b.latest.technical_muted && (
          <p className="mt-2 text-body text-amber-800 bg-amber-50 rounded-inner px-2.5 py-1.5 leading-snug">
            ⚠️ 技术面熔断日(跳空 ≥8%)—— 实测该档技术指标无分辨力(p=0.72),这条表态本身该打折看。
          </p>
        )}
        <p className="mt-2.5 text-body text-gray-700 leading-relaxed">{b.latest.why}</p>
        <p className="mt-2 text-meta text-gray-400">
          {b.latest.model} · 与 QBTS 决策同一个模型、同一套表态语义(换标准就不算第二个考场)
        </p>
      </section>

      {/* 成绩单 */}
      <section className="bg-surface rounded-card shadow-[0_1px_2px_rgba(0,0,0,0.05)] p-5">
        <div className="flex items-baseline justify-between gap-2 flex-wrap mb-2">
          <span className="text-section font-semibold text-gray-900">
            📊 逐视界成绩 · 共 {b.n_total} 条表态
          </span>
        </div>
        <HorizonTable b={b} />
        <p className="mt-3 text-meta text-gray-400 bg-sunken rounded-inner px-2.5 py-2 leading-relaxed">
          ⓘ 判活条件(在看到数据之前就写死了,审判日不许改):{b.rule}
        </p>
      </section>

      {/* 逐条 */}
      <section className="bg-surface rounded-card shadow-[0_1px_2px_rgba(0,0,0,0.05)] p-5">
        <span className="text-section font-semibold text-gray-900">
          🗒️ 逐条表态
        </span>
        <div className="mt-2">
          {b.records.map(r => <RecordRow key={r.id} r={r} />)}
        </div>
      </section>

      {/* 为什么是这只票 + 自己推翻的那条 */}
      <section className="bg-surface rounded-card shadow-[0_1px_2px_rgba(0,0,0,0.05)] p-5 space-y-3">
        <div>
          <span className="text-section font-semibold text-gray-900">
            为什么选 {b.ticker}
          </span>
          <p className="mt-1.5 text-body text-ink-muted leading-relaxed">{b.why_this_ticker}</p>
        </div>
        <div className="rounded-inner bg-amber-50 px-3 py-2.5">
          <span className="text-meta font-semibold text-[#B45309]">
            ⚠️ 选它的理由里有一条被当天实测推翻了
          </span>
          <p className="mt-1 text-body text-[#78350F] leading-relaxed">{b.known_weakness}</p>
        </div>
        <p className="text-meta text-gray-400 leading-relaxed">{b.discipline_cn}</p>
      </section>
    </div>
  );
}
