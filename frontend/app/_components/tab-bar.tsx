"use client";

import type { ReactNode } from "react";

/* ─────────────────────────────────────────────────────────────────────────
   二级导航。

   2026-07-29 大改的核心:改之前整页 21 个顶层区块**全是同一种白卡片、同一个
   圆角阴影、同一号标题** —— SMC 那 700 行和「今日行动」长得一样重,大脑没法
   排序,用户的原话是"复杂到我已经看不明白了"。所以问题不是信息量,是**没有
   层级**。首屏只回答一个问题(今天买什么、怎么下单),其余五类全部降到这里。

   这条 bar 自己 sticky:滚动时价格 + 裁决 + 导航永远不离开视野。
   ───────────────────────────────────────────────────────────────────────── */

export type TabKey = "today" | "structure" | "events" | "record" | "system";

export const TABS: { key: TabKey; label: string; hint: string }[] = [
  { key: "today",     label: "今日决策", hint: "持仓 · 关键驱动 · 在等什么 · 要闻" },
  { key: "structure", label: "结构",     hint: "SMC · 成交量画像 · 日内画像" },
  { key: "events",    label: "事件",     hint: "宏观日历 · 地缘雷达 · 公司催化剂" },
  { key: "record",    label: "战绩",     hint: "决策台账 · 策略陪跑 · 深坑报警器" },
  { key: "system",    label: "系统",     hint: "AI 自检 · 全站体检 · 控制台" },
];

export function TabBar({
  tab, onChange, rail, dots,
}: {
  tab: TabKey;
  onChange: (t: TabKey) => void;
  /** 压缩版价格 + 裁决,滚动时代替整个驾驶舱留在视野里 */
  rail: ReactNode;
  /** 需要提醒的标签 → 右上角红点(如地缘 alert / breaking 催化剂 / 自检有发现) */
  dots?: Partial<Record<TabKey, boolean>>;
}) {
  return (
    <div className="sticky top-0 z-30 -mx-4 sm:-mx-6 px-4 sm:px-6 py-2
                    bg-[#F5F5F7]/90 backdrop-blur-xl border-b border-black/[0.06]">
      <div className="max-w-[1200px] mx-auto flex items-center gap-3 flex-wrap">
        <div className="min-w-0 shrink-0">{rail}</div>
        <nav className="flex items-center gap-0.5 ml-auto overflow-x-auto" aria-label="仪表盘分区">
          {TABS.map(t => {
            const on = t.key === tab;
            return (
              <button
                key={t.key}
                onClick={() => onChange(t.key)}
                title={t.hint}
                aria-current={on ? "page" : undefined}
                className={`relative shrink-0 px-3 py-1.5 rounded-lg text-[13px] font-medium
                            transition-colors focus-visible:outline-2 focus-visible:outline-offset-2
                            focus-visible:outline-[#006FFF] ${
                  on ? "bg-gray-900 text-white shadow-sm"
                     : "text-[#525461] hover:bg-black/[0.05]"}`}
              >
                {t.label}
                {dots?.[t.key] && !on && (
                  <span className="absolute top-1 right-1.5 w-1.5 h-1.5 rounded-full bg-[#F03A3E]" />
                )}
              </button>
            );
          })}
        </nav>
      </div>
    </div>
  );
}
