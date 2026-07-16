"use client";

import { useEffect, useState } from "react";
import { getSiteCheck, type SiteCheck, type SiteCheckPage } from "../_lib/data";

const PAGE_LABEL: Record<SiteCheckPage, string> = {
  home: "🎯 决策", watch: "🔭 自选", dca: "📥 定投",
  factors: "🏇 战绩", challenge: "🏁 挑战", spacex: "🚀 SpaceX",
};

/** 单页自检横幅:只渲染本页的发现,没有问题时完全不占位。
 *  数据来自 publish §4.8 的全站体检(dashboard_state.snapshot.site_check 切片)。 */
export function SelfCheckCard({ page, check: preloaded }:
                              { page: SiteCheckPage; check?: SiteCheck | null }) {
  const [check, setCheck] = useState<SiteCheck | null>(preloaded ?? null);

  useEffect(() => {
    if (preloaded !== undefined) { setCheck(preloaded); return; }
    getSiteCheck().then(setCheck).catch(() => {});
  }, [preloaded]);

  const issues = check?.pages?.[page] ?? [];
  if (issues.length === 0) return null;

  return (
    <section className="bg-white rounded-xl border border-amber-200/70 p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
          🔬 AI 系统自检 · 本页发现
        </span>
        {check?.generated_at && (
          <span className="text-[10px] text-gray-400 font-mono">
            {check.generated_at.slice(5, 16).replace("T", " ")} UTC
          </span>
        )}
      </div>
      <div className="space-y-1.5">
        {issues.map((n, i) => (
          <div key={i} className="flex items-start gap-2 text-sm leading-relaxed">
            <span className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded font-semibold mt-0.5 ${
              n.kind === "数据问题" ? "bg-amber-100 text-amber-700" : "bg-sky-100 text-sky-700"}`}>
              {n.kind}
            </span>
            <span className="text-gray-700">{n.note}</span>
            {n.src === "ai" && <span className="shrink-0 text-[10px] text-gray-300 mt-1">AI</span>}
          </div>
        ))}
      </div>
    </section>
  );
}

/** 决策页汇总卡:六页发现按 tab 分组一屏总览(本页 home 的问题也在其中)。 */
export function SiteCheckOverview({ check }: { check?: SiteCheck | null }) {
  if (!check || check.n_issues === 0) return null;
  const entries = (Object.keys(PAGE_LABEL) as SiteCheckPage[])
    .map(p => [p, check.pages?.[p] ?? []] as const)
    .filter(([, v]) => v.length > 0);
  if (entries.length === 0) return null;

  return (
    <section className="bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
          🔬 全站系统体检 · {check.n_issues} 项发现
        </span>
        <span className="text-[10px] text-gray-400 font-mono">
          {check.generated_at.slice(5, 16).replace("T", " ")} UTC
        </span>
      </div>
      <div className="space-y-3">
        {entries.map(([p, issues]) => (
          <div key={p}>
            <div className="text-[11px] font-semibold text-gray-500 mb-1">{PAGE_LABEL[p]}</div>
            <div className="space-y-1.5">
              {issues.map((n, i) => (
                <div key={i} className="flex items-start gap-2 text-sm leading-relaxed">
                  <span className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded font-semibold mt-0.5 ${
                    n.kind === "数据问题" ? "bg-amber-100 text-amber-700" : "bg-sky-100 text-sky-700"}`}>
                    {n.kind}
                  </span>
                  <span className="text-gray-700">{n.note}</span>
                  {n.src === "ai" && <span className="shrink-0 text-[10px] text-gray-300 mt-1">AI</span>}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-2.5 text-[10px] text-gray-400">
        每日 publish 后规则层+Haiku 对六个页面的数据体检 · 与决策模型的当日自检互补 · 修不修由你定
      </div>
    </section>
  );
}
