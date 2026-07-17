"use client";

/* 板块轮动地图(RRG 风格四象限)—— /challenge/lessons 页。
   颜色跟随「象限状态」(4 色,已跑 dataviz 校验:CVD ΔE 39.7 通过;琥珀对比度
   WARN 由每条轨迹的直接标注 + 底部数据表兜底),板块身份靠直接标注 + emoji,
   文字一律用墨色(不用系列色)。箭头 = 轨迹最新方向;动效:入场描线 + 箭头
   呼吸;prefers-reduced-motion 下全部静止。 */

import { useMemo, useState } from "react";
import type { SectorRotation, SectorPoint } from "../_lib/data";

const QUAD = {
  leading:   { color: "#006300", label: "领涨", glyph: "↗", hint: "强且更强" },
  weakening: { color: "#eda100", label: "转弱", glyph: "↘", hint: "还强但在衰减" },
  lagging:   { color: "#d03b3b", label: "落后", glyph: "↙", hint: "弱且仍弱" },
  improving: { color: "#2a78d6", label: "转强", glyph: "↖", hint: "弱但在回血" },
} as const;
type QuadKey = keyof typeof QUAD;

const W = 720, H = 560, PAD = 34;

/* Catmull-Rom → 三次贝塞尔:把周采样折线渲染成连续的蜗牛尾曲线 */
function smoothPath(pts: readonly (readonly [number, number])[]): string {
  if (pts.length < 3)
    return "M" + pts.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L");
  let d = `M ${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i],
          p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C ${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}

export function RotationMap({ data }: { data: SectorRotation }) {
  const [hover, setHover] = useState<string | null>(null);

  const { dom, sx, sy } = useMemo(() => {
    let m = 0;
    for (const s of data.sectors) for (const [x, y] of s.trail)
      m = Math.max(m, Math.abs(x - 100), Math.abs(y - 100));
    const dom = Math.max(2.5, Math.ceil(m * 1.2 * 2) / 2);
    return {
      dom,
      sx: (v: number) => PAD + ((v - (100 - dom)) / (2 * dom)) * (W - 2 * PAD),
      sy: (v: number) => PAD + ((100 + dom - v) / (2 * dom)) * (H - 2 * PAD),
    };
  }, [data]);

  /* 标签防碰撞:按 y 排序,同列(Δx<86px)且 Δy<13px 的往下挪 */
  const labelPos = useMemo(() => {
    const pos = data.sectors.map(s => ({
      t: s.ticker,
      x: sx(s.x) + 11,
      y: sy(s.y) + 4,
    })).sort((a, b) => a.y - b.y);
    for (let i = 1; i < pos.length; i++)
      for (let j = 0; j < i; j++)
        if (Math.abs(pos[i].x - pos[j].x) < 86 && pos[i].y - pos[j].y < 13)
          pos[i].y = pos[j].y + 13;
    return Object.fromEntries(pos.map(p => [p.t, p]));
  }, [data, sx, sy]);

  const cx = sx(100), cy = sy(100);
  const hovered = hover ? data.sectors.find(s => s.ticker === hover) : null;

  return (
    <div className="relative">
      <style>{`
        .rot-path { stroke-dasharray: 100; stroke-dashoffset: 100;
                    animation: rotDraw 1.1s ease-out forwards; }
        .rot-halo { animation: rotPulse 2.2s ease-in-out infinite; transform-origin: center; transform-box: fill-box; }
        .rot-spin { animation: rotSpin 9s linear infinite; transform-origin: center; transform-box: fill-box; }
        .rot-dim  { transition: opacity .18s ease; }
        @keyframes rotDraw  { to { stroke-dashoffset: 0; } }
        @keyframes rotPulse { 0%,100% { opacity: .45; transform: scale(1); }
                              50%     { opacity: .12; transform: scale(1.9); } }
        @keyframes rotSpin  { to { transform: rotate(360deg); } }
        @media (prefers-reduced-motion: reduce) {
          .rot-path { animation: none; stroke-dashoffset: 0; }
          .rot-halo, .rot-spin { animation: none; }
        }
      `}</style>

      <div className="overflow-x-auto">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[560px] h-auto select-none"
             role="img" aria-label="板块轮动地图:相对强度×相对动量四象限,箭头为最新方向">
          {/* 象限底色 */}
          <rect x={cx} y={PAD} width={W - PAD - cx} height={cy - PAD} fill={QUAD.leading.color} opacity="0.06" />
          <rect x={cx} y={cy} width={W - PAD - cx} height={H - PAD - cy} fill={QUAD.weakening.color} opacity="0.07" />
          <rect x={PAD} y={cy} width={cx - PAD} height={H - PAD - cy} fill={QUAD.lagging.color} opacity="0.05" />
          <rect x={PAD} y={PAD} width={cx - PAD} height={cy - PAD} fill={QUAD.improving.color} opacity="0.06" />

          {/* 中心线 + 外框(隐性网格) */}
          <line x1={cx} y1={PAD} x2={cx} y2={H - PAD} stroke="#e1e0d9" strokeWidth="1" />
          <line x1={PAD} y1={cy} x2={W - PAD} y2={cy} stroke="#e1e0d9" strokeWidth="1" />
          <rect x={PAD} y={PAD} width={W - 2 * PAD} height={H - 2 * PAD} fill="none" stroke="#e1e0d9" strokeWidth="1" rx="8" />

          {/* 象限角标(色点 + 墨字) */}
          {([
            ["leading",   W - PAD - 10, PAD + 18, "end"],
            ["weakening", W - PAD - 10, H - PAD - 10, "end"],
            ["lagging",   PAD + 10, H - PAD - 10, "start"],
            ["improving", PAD + 10, PAD + 18, "start"],
          ] as [QuadKey, number, number, "start" | "end"][]).map(([q, x, y, anchor]) => (
            <g key={q}>
              <circle cx={anchor === "end" ? x - (QUAD[q].label.length * 13 + 22) : x + 4} cy={y - 4} r="4" fill={QUAD[q].color} />
              <text x={anchor === "end" ? x : x + 14} y={y} textAnchor={anchor}
                    fontSize="13" fontWeight="600" fill="#52514e">
                {QUAD[q].label} {QUAD[q].glyph}
              </text>
            </g>
          ))}
          {/* 轴说明 */}
          <text x={W - PAD} y={cy - 6} textAnchor="end" fontSize="10" fill="#898781">相对强度 →</text>
          <text x={cx + 6} y={PAD + 12} fontSize="10" fill="#898781">相对动量 ↑</text>

          {/* 轨迹(先画非 hover,再画 hover 保证压在顶层) */}
          {[...data.sectors].sort((a, b) =>
            (a.ticker === hover ? 1 : 0) - (b.ticker === hover ? 1 : 0)).map(s => {
            const q = QUAD[(s.quadrant as QuadKey) ?? "lagging"] ?? QUAD.lagging;
            const pts = s.trail.map(([x, y]) => [sx(x), sy(y)] as const);
            const head = pts[pts.length - 1];
            const prev = pts[Math.max(0, pts.length - 2)];
            const ang = Math.atan2(head[1] - prev[1], head[0] - prev[0]) * 180 / Math.PI;
            const d = smoothPath(pts);
            const dimmed = hover !== null && hover !== s.ticker;
            const focus = hover === s.ticker;
            const isQ = s.ticker === "QTUM";
            const lp = labelPos[s.ticker];
            return (
              <g key={s.ticker} className="rot-dim" opacity={dimmed ? 0.18 : 1}
                 onMouseEnter={() => setHover(s.ticker)} onMouseLeave={() => setHover(null)}
                 style={{ cursor: "default" }}>
                {/* 轨迹线(描线动画;hover 加粗) */}
                <path d={d} pathLength={100} className="rot-path" fill="none"
                      stroke={q.color} strokeWidth={focus ? 2.8 : 1.8}
                      strokeLinecap="round" strokeLinejoin="round"
                      opacity={focus ? 0.95 : 0.55} />
                {/* 历史采样点:越旧越淡 */}
                {pts.slice(0, -1).map((p, i) => (
                  <circle key={i} cx={p[0]} cy={p[1]} r="1.8"
                          fill={q.color} opacity={0.08 + 0.3 * (i / pts.length)} />
                ))}
                {/* 箭头头部:呼吸光晕 + 白圈点 + 三角箭头 */}
                <circle cx={head[0]} cy={head[1]} r="9" fill={q.color} className="rot-halo" />
                {isQ && (
                  <circle cx={head[0]} cy={head[1]} r="13" fill="none" stroke={q.color}
                          strokeWidth="1.3" strokeDasharray="4 4" className="rot-spin" opacity="0.8" />
                )}
                <circle cx={head[0]} cy={head[1]} r="4.5" fill={q.color} stroke="#fff" strokeWidth="2" />
                <path d="M 5 0 L -3.5 4.5 L -1.5 0 L -3.5 -4.5 Z" fill={q.color}
                      transform={`translate(${(head[0] + 12 * Math.cos(ang * Math.PI / 180)).toFixed(1)},${(head[1] + 12 * Math.sin(ang * Math.PI / 180)).toFixed(1)}) rotate(${ang.toFixed(1)})`} />
                {/* 直接标注(墨字 + 白描边;量子加粗) */}
                <text x={lp.x + 10} y={lp.y} fontSize="11.5" fontWeight={isQ ? 800 : 600}
                      fill="#111318" stroke="#ffffff" strokeWidth="3" paintOrder="stroke">
                  {s.emoji} {s.label}
                </text>
                {/* 放大的命中区 */}
                <circle cx={head[0]} cy={head[1]} r="16" fill="transparent" />
              </g>
            );
          })}
        </svg>
      </div>

      {/* 悬停提示 */}
      {hovered && (() => {
        const q = QUAD[(hovered.quadrant as QuadKey) ?? "lagging"] ?? QUAD.lagging;
        const left = (sx(hovered.x) / W) * 100, top = (sy(hovered.y) / H) * 100;
        return (
          <div className="absolute z-10 pointer-events-none rounded-lg border border-[#EDEDF0] bg-white shadow-lg px-3 py-2 text-[12px] leading-relaxed"
               style={{ left: `${left}%`, top: `${top}%`,
                        transform: `translate(${left > 72 ? "-105%" : "8px"}, ${top > 75 ? "-115%" : "-40%"})` }}>
            <div className="font-semibold text-gray-900">{hovered.emoji} {hovered.label} <span className="font-mono text-gray-500">{hovered.ticker}</span></div>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: q.color }} />
              <span className="text-gray-700">{q.label}{q.glyph} · {q.hint}</span>
            </div>
            <div className="font-mono text-gray-500">RS {hovered.x.toFixed(1)} · 动量 {hovered.y.toFixed(1)} · 20日 {hovered.ret20 >= 0 ? "+" : ""}{(hovered.ret20 * 100).toFixed(1)}%</div>
          </div>
        );
      })()}

      {/* 图例(色点 + 墨字) */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2">
        {(Object.keys(QUAD) as QuadKey[]).map(q => (
          <span key={q} className="inline-flex items-center gap-1.5 text-[12px] text-[#52514e]">
            <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: QUAD[q].color }} />
            {QUAD[q].label}{QUAD[q].glyph}<span className="text-gray-400">{QUAD[q].hint}</span>
          </span>
        ))}
      </div>

      {/* 象限速览条:图上 17 个点挤时(07-17 用户找不到能源/金矿),文字条保底可扫 */}
      <div className="mt-1.5 space-y-0.5">
        {(Object.keys(QUAD) as QuadKey[]).map(q => {
          const members = data.sectors.filter(s => (s.quadrant ?? "lagging") === q);
          if (members.length === 0) return null;
          return (
            <div key={q} className="text-[12px] leading-relaxed">
              <span className="font-semibold" style={{ color: QUAD[q].color }}>
                {QUAD[q].label}{QUAD[q].glyph}
              </span>
              <span className="text-[#52514e] ml-1.5">
                {members.map(s => `${s.emoji}${s.label}`).join(" · ")}
              </span>
            </div>
          );
        })}
      </div>

      {/* 数据表(可及性兜底) */}
      <details className="mt-2">
        <summary className="text-[11px] text-gray-400 cursor-pointer hover:text-gray-600">数据表</summary>
        <div className="overflow-x-auto mt-1">
          <table className="text-[12px] w-full">
            <thead><tr className="text-left text-[10px] uppercase tracking-wider text-gray-500 border-b border-[#EDEDF0]">
              <th className="py-1 pr-3">板块</th><th className="py-1 pr-3">象限</th>
              <th className="py-1 pr-3">相对强度</th><th className="py-1 pr-3">相对动量</th><th className="py-1">20日</th>
            </tr></thead>
            <tbody>
              {[...data.sectors].sort((a, b) => b.x + b.y - a.x - a.y).map(s => (
                <tr key={s.ticker} className="border-b border-[#F4F4F6] last:border-0">
                  <td className="py-1 pr-3 text-gray-900">{s.emoji} {s.label} <span className="font-mono text-gray-400">{s.ticker}</span></td>
                  <td className="py-1 pr-3 text-gray-700">{QUAD[(s.quadrant as QuadKey) ?? "lagging"]?.label}{QUAD[(s.quadrant as QuadKey) ?? "lagging"]?.glyph}</td>
                  <td className="py-1 pr-3 font-mono text-gray-700">{s.x.toFixed(2)}</td>
                  <td className="py-1 pr-3 font-mono text-gray-700">{s.y.toFixed(2)}</td>
                  <td className={`py-1 font-mono ${s.ret20 >= 0 ? "text-emerald-600" : "text-[#F03A3E]"}`}>{s.ret20 >= 0 ? "+" : ""}{(s.ret20 * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

export type { SectorPoint };
