"use client";

import { parseUtc } from "../_lib/format";

interface BriefPanelProps {
  brief:        string | null;
  generatedAt:  string | null;
  asOf:         string | null;
}

function _elapsedLabel(iso: string | null): string {
  const d = parseUtc(iso);
  if (!d) return "—";
  const ms = Date.now() - d.getTime();
  if (ms < 60_000)            return "刚刚";
  if (ms < 3_600_000)         return `${Math.floor(ms / 60_000)} 分钟前`;
  if (ms < 86_400_000)        return `${Math.floor(ms / 3_600_000)} 小时前`;
  return `${Math.floor(ms / 86_400_000)} 天前`;
}

export function BriefPanel({ brief, generatedAt, asOf }: BriefPanelProps) {
  return (
    <section className="bg-gradient-to-br from-white via-blue-50/30 to-white rounded-xl border border-blue-100 overflow-hidden shadow-sm">
      <div className="px-5 py-3 border-b border-blue-100 bg-blue-50/50 flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xl">✨</span>
          <span className="text-xs font-semibold text-[#006FFF] uppercase tracking-wider">
            AI 早盘简报
          </span>
        </div>
        {generatedAt && (
          <span className="text-[10px] text-gray-400 font-mono">
            生成于 {_elapsedLabel(generatedAt)} · 数据 {asOf?.slice(0, 10)}
          </span>
        )}
      </div>
      <div className="px-6 py-5">
        {brief ? (
          <div className="text-[15px] leading-[1.85] text-gray-800 space-y-2 font-medium">
            {brief
              .replace(/\n+/g, " ")
              .split(/(?<=[。！？])/)
              .map(s => s.trim())
              .filter(Boolean)
              .map((s, i) => (
                <p key={i} className="first-letter:text-[#006FFF] first-letter:font-bold">{s}</p>
              ))}
          </div>
        ) : (
          <div className="py-6 text-center">
            <p className="text-sm text-gray-500 mb-2">还没有早盘简报</p>
            <p className="text-xs text-gray-400">
              本地运行 publish.py 时会用 Claude 综合 8 个策略 + 新闻生成一段执行级建议并发布到这里。
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
