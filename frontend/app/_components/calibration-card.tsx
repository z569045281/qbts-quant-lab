"use client";

import { useEffect, useState } from "react";
import { getCalibration } from "../_lib/data";

export function CalibrationCard() {
  const [cal, setCal] = useState<Awaited<ReturnType<typeof getCalibration>>>(null);

  useEffect(() => {
    getCalibration().then(setCal).catch(() => {});
  }, []);

  if (!cal) return null;

  const bySorted = Object.entries(cal.by_source)
    .sort((a, b) => b[1].n - a[1].n)
    .slice(0, 12);

  const hitColor = (r: number) => r >= 0.55 ? "text-emerald-600"
                                 : r >= 0.45 ? "text-amber-500"
                                              : "text-[#F03A3E]";

  return (
    <section className="bg-white rounded-xl border border-[#EDEDF0] overflow-hidden">
      <div className="px-5 py-3 border-b border-[#EDEDF0] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-base">📊</span>
          <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
            模型校准 · 每个信号源的实战命中率
          </span>
        </div>
      </div>
      <div className="px-5 py-4 grid grid-cols-1 lg:grid-cols-[200px_1fr] gap-5">
        {/* ── Left: overall stats ── */}
        <div className="space-y-2.5">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500">累计预测</div>
            <div className="text-2xl font-bold text-gray-900 font-mono">{cal.n_total}</div>
            <div className="text-[10px] text-gray-400">{cal.n_graded} 条已可评判</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500">整体方向命中</div>
            <div className={`text-2xl font-bold font-mono ${hitColor(cal.overall_hit_rate)}`}>
              {(cal.overall_hit_rate * 100).toFixed(1)}%
            </div>
            <div className="text-[10px] text-gray-400">
              {cal.n_graded >= 10 ? "样本足，可信" : `样本 < 10，仅参考`}
            </div>
          </div>
          {cal.n_total < 5 && (
            <div className="text-[10px] text-gray-400 italic leading-snug pt-2 border-t border-[#EDEDF0]">
              每次仪表盘加载会自动记录一条预测。5 天后系统会用真实 5 日收益评判，
              然后给每个信号源调整权重。N 越大越准。
            </div>
          )}
        </div>

        {/* ── Right: per-source hit rate + weight multiplier ── */}
        <div>
          <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-2">
            各信号源（按样本量排序）
          </div>
          {bySorted.length === 0 ? (
            <div className="text-xs text-gray-400 py-6 text-center">
              暂无可评判样本（需要 5 天前的预测 + 真实收益）
            </div>
          ) : (
            <div className="space-y-1">
              {bySorted.map(([src, info]) => (
                <div key={src} className="grid grid-cols-[1fr_60px_70px_70px] gap-2 text-xs items-center">
                  <span className="truncate text-gray-900 font-medium" title={src}>{src}</span>
                  <span className="font-mono text-[10px] text-gray-500 text-right">
                    {info.hits}/{info.n}
                  </span>
                  <span className={`font-mono text-xs font-semibold text-right ${hitColor(info.hit_rate)}`}>
                    {(info.hit_rate * 100).toFixed(0)}%
                  </span>
                  <span className={`font-mono text-[10px] text-right ${
                    info.weight_mult > 1.1 ? "text-emerald-600"
                    : info.weight_mult < 0.9 ? "text-[#F03A3E]"
                    : "text-gray-500"
                  }`}>
                    ×{info.weight_mult.toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          )}
          <p className="text-[10px] text-gray-400 mt-3 leading-snug">
            ×权重 = 学习到的乘数，下次 edge 计算会按这个调整该信号源的权重。
            5 次以上样本才公布（Bayesian 收缩防小样本噪声）。
          </p>
        </div>
      </div>
    </section>
  );
}
