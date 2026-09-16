"use client";

import type { Champions } from "../_lib/data";

/* ─────────────────────────────────────────────────────────────────────────
   🏆 策略冠军 —— 2026-09-16 从首屏顶端搬到这里。

   它原本是页面的第一块。搬走的理由不是"太挤",是 champions.py 文件头自己
   记着的 142 份快照回放:

       IDLE 89 · SHORT_MUTED 50 · GATED 3 · **TRIGGER 0**

   97.9% 的日子它说的是「三名今天都没表态」或「一致偏空 —— 只作风控背景,
   不推送」,两句都等于**今天不用管它**;而 SHORT_MUTED 那 50 天它还是**红的**
   (border-red-200 bg-red-50/60)。全页最上面、三分之一的日子亮红、一次都没
   改变过当天动作 —— 这正是"进去不知道看什么"的第一因。

   现在:常驻在「战绩」标签(它本来就是一张排序显示卡);只有 state==TRIGGER
   那一天才回首屏,走警报槽同一条规矩 —— 不出事零像素。
   ───────────────────────────────────────────────────────────────────────── */

export function ChampionsCard({ ch }: { ch: Champions }) {
  const tone =
    ch.state === "TRIGGER" ? "border-emerald-400 bg-emerald-50"
    : ch.state === "GATED" ? "border-amber-300 bg-amber-50"
    : ch.state === "SHORT_MUTED" ? "border-red-200 bg-red-50/60"
    : "border-hairline bg-sunken";
  return (
    <div className={`rounded-card border-2 ${tone} px-4 py-3`}>
      <div className="flex items-center gap-2 flex-wrap mb-2">
        <span className="text-body font-bold text-ink">🏆 策略冠军</span>
        <span className="text-meta px-2 py-0.5 rounded-full bg-surface/70 font-mono text-ink-muted">
          共识 {ch.consensus}
        </span>
        <span className="text-meta px-2 py-0.5 rounded-full bg-surface/70 font-medium">
          {ch.gate.cn}
        </span>
        <span className="ml-auto text-body font-semibold text-ink">{ch.state_cn}</span>
      </div>
      <div className="space-y-1">
        {ch.members.map((m) => (
          <div key={m.key} className="flex items-start gap-2 text-body leading-snug">
            <span className={
              m.stance === "up" ? "text-emerald-600 font-bold"
              : m.stance === "down" ? "text-red-600 font-bold" : "text-ink-faint"}>
              {m.stance === "up" ? "▲" : m.stance === "down" ? "▼" : "○"}
            </span>
            <span className="font-medium text-ink shrink-0">{m.name}</span>
            <span className="text-meta font-mono text-ink-faint shrink-0">
              大波动日 {m.big_hit}%·n={m.big_n}
            </span>
            <span className="text-ink-muted ml-auto text-right truncate">{m.read}</span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-meta text-ink-muted leading-snug">{ch.gate.note}</p>
      <p className="mt-1 text-meta text-amber-700 leading-snug">{ch.unproven_note}</p>
    </div>
  );
}
