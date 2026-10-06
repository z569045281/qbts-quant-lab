"use client";

/* 🌊 浪潮动画(2026-10-06 用户点单:「改成真实的动画海浪,要高端大气,能在正式对外展示上拿得出手」)。

   浪形就是 QBTS 自己的浪:最近几个浪尖/浪底 + 现在,按真实日期排在横轴上(所以「涨得陡、
   退得缓」是数据本身的形状),单调三次插值连成水面,下面是深海渐变。水面上有一条缓慢流动的
   泡沫线和一层远景波,现在的位置是一个浮标。

   HIG:动效只做氛围、信息全部有文字(motion.md › Best practices「Make motion optional」);
   打开「减少动态效果」或卡片不在视口 / 标签页在后台时,动画停在静止帧
   (accessibility.md「reduce automatic and repetitive animations」)。
   每帧只改 3 个 path 的 d 属性和浮标坐标,不触发 React 重渲染。 */

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useDarkMode } from "../_lib/theme";

export type ScenePivot = { kind: "peak" | "trough"; date: string; price: number; tentative?: boolean };

type Props = {
  pivots: ScenePivot[];          // 已确认的浪尖/浪底(按时间)
  price: number;                 // 实时价
  up: boolean;                   // 当前是上涨浪还是回落浪
  confirm: number;               // 越过这条线才算翻浪
  trigger?: number | null;       // 🧪 回测冠军的买入线(可选,只画一条淡线)
  ariaLabel: string;
};

/** Fritsch–Carlson 单调三次插值:过每个转折点、不越过它们(浪尖就是浪尖,不会画出假高点)。 */
function monotone(xs: number[], ys: number[]) {
  const n = xs.length;
  const dx: number[] = [], m: number[] = [];
  for (let i = 0; i < n - 1; i++) { dx.push(xs[i + 1] - xs[i]); m.push((ys[i + 1] - ys[i]) / dx[i]); }
  const c1: number[] = [m[0]];
  for (let i = 1; i < n - 1; i++) {
    if (m[i - 1] * m[i] <= 0) c1.push(0);
    else {
      const common = dx[i - 1] + dx[i];
      c1.push(3 * common / ((common + dx[i]) / m[i - 1] + (common + dx[i - 1]) / m[i]));
    }
  }
  c1.push(m[n - 2]);
  const c2: number[] = [], c3: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    const inv = 1 / dx[i], common = c1[i] + c1[i + 1] - 2 * m[i];
    c2.push((m[i] - c1[i] - common) * inv);
    c3.push(common * inv * inv);
  }
  return (x: number) => {
    let i = n - 2;
    for (let k = 0; k < n - 1; k++) if (x <= xs[k + 1]) { i = k; break; }
    const d = x - xs[i];
    return ys[i] + c1[i] * d + c2[i] * d * d + c3[i] * d * d * d;
  };
}

const DAY = 86_400_000;

export function WaveScene({ pivots, price, up, confirm, trigger, ariaLabel }: Props) {
  const uid = useId().replace(/:/g, "");
  const dark = useDarkMode();
  const wrapRef = useRef<HTMLDivElement>(null);
  const farRef = useRef<SVGPathElement>(null);
  const foamRef = useRef<SVGPathElement>(null);
  const glowRef = useRef<SVGPathElement>(null);
  const buoyRef = useRef<SVGGElement>(null);
  const [w, setW] = useState(720);
  const h = w < 520 ? 150 : 176;
  // 浮标的横坐标用到「现在」—— 服务端预渲染与浏览器各算一次会对不上(hydration 警告),挂载后再画
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // ── 几何:真实日期 → 横轴,价格 → 纵轴 ─────────────────────────────────
  const geo = useMemo(() => {
    // 手机宽度只画最近 4 个转折点 —— 5 月那种 10 天里三个转折,窄屏上标签会叠在一起
    const pts = (w < 520 ? pivots.slice(-4) : pivots).map(p => ({ ...p, t: Date.parse(p.date + "T00:00:00Z") }));
    const last = pts[pts.length - 1];
    const nowT = Math.max(Date.now(), last.t + DAY);
    const all: (ScenePivot & { t: number } | { kind: "now"; date: string; price: number; t: number; tentative?: false })[] =
      [...pts, { kind: "now" as const, date: "", price, t: nowT }];
    const padL = 18, padR = w < 520 ? 104 : 132, padT = 26, padB = 30;
    const prices = [...all.map(p => p.price), confirm, ...(trigger ? [trigger] : [])];
    const pMax = Math.max(...prices) * 1.04, pMin = Math.min(...prices) * 0.9;
    const t0 = all[0].t, t1 = nowT;
    const X = (t: number) => padL + (t - t0) / (t1 - t0) * (w - padL - padR);
    const Y = (p: number) => padT + (pMax - p) / (pMax - pMin) * (h - padT - padB);
    const xs = all.map(p => X(p.t)), ys = all.map(p => Y(p.price));
    const f = monotone(xs, ys);
    const N = 160, x0 = xs[0], x1 = xs[xs.length - 1];
    const samples: [number, number][] = [];
    for (let i = 0; i <= N; i++) { const x = x0 + (x1 - x0) * i / N; samples.push([x, f(x)]); }
    return { all, xs, ys, samples, Y, x0, x1, padR, nowX: x1, nowY: Y(price) };
  }, [pivots, price, confirm, trigger, w, h]);

  // 水面:主体 + 每帧扰动(振幅几像素,越靠近现在越平静 —— 浮标在的地方不该乱晃)
  const surface = (phase: number, amp: number, lambda: number, lift = 0) => {
    const { samples, x0, x1 } = geo;
    return samples.map(([x, y], i) => {
      const calm = 1 - 0.65 * ((x - x0) / (x1 - x0)) ** 3;
      const yy = y + lift + amp * calm * Math.sin((x / lambda) * Math.PI * 2 - phase);
      return `${i ? "L" : "M"}${x.toFixed(1)},${yy.toFixed(1)}`;
    }).join("");
  };
  const fillPath = (phase: number) =>
    `${surface(phase, 1.6, 120)}L${geo.x1.toFixed(1)},${h}L${geo.x0.toFixed(1)},${h}Z`;

  // ── 动画循环:只动 3 条 path + 浮标;减少动态效果 / 不可见时停 ─────────
  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    let raf = 0, visible = true, start = performance.now();
    const frame = (now: number) => {
      const s = (now - start) / 1000;
      const phase = s * 0.55;                       // 慢:一个波长约 11 秒
      farRef.current?.setAttribute("d", `${surface(phase * 0.6 + 1.3, 3, 170, 12)}L${geo.x1},${h}L${geo.x0},${h}Z`);
      glowRef.current?.setAttribute("d", fillPath(phase));
      foamRef.current?.setAttribute("d", surface(phase, 1.6, 120));
      buoyRef.current?.setAttribute("transform", `translate(0 ${(1.4 * Math.sin(s * 1.6)).toFixed(2)})`);
      raf = requestAnimationFrame(frame);
    };
    const paintStatic = () => {
      farRef.current?.setAttribute("d", `${surface(1.3, 3, 170, 12)}L${geo.x1},${h}L${geo.x0},${h}Z`);
      glowRef.current?.setAttribute("d", fillPath(0));
      foamRef.current?.setAttribute("d", surface(0, 1.6, 120));
      buoyRef.current?.setAttribute("transform", "translate(0 0)");
    };
    const run = () => {
      cancelAnimationFrame(raf);
      if (reduce.matches || !visible || document.hidden) { paintStatic(); return; }
      start = performance.now(); raf = requestAnimationFrame(frame);
    };
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; run(); });
    if (wrapRef.current) io.observe(wrapRef.current);
    reduce.addEventListener("change", run);
    document.addEventListener("visibilitychange", run);
    run();
    return () => {
      cancelAnimationFrame(raf); io.disconnect();
      reduce.removeEventListener("change", run);
      document.removeEventListener("visibilitychange", run);
    };
  }, [geo, h]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── 配色(深海;浅色/深色各一套)──────────────────────────────────────
  const c = dark
    ? { top: "#22D3EE", mid: "#1E40AF", deep: "#020617", far: "#38BDF8", foam: "rgba(236,254,255,0.85)",
        label: "#CBD5E1", soft: "#94A3B8", line: "rgba(148,163,184,0.55)", sky0: "#0B1220", sky1: "#0F172A" }
    : { top: "#38BDF8", mid: "#1D4ED8", deep: "#0B1E4A", far: "#93C5FD", foam: "rgba(255,255,255,0.92)",
        label: "#334155", soft: "#64748B", line: "rgba(100,116,139,0.55)", sky0: "#F0F9FF", sky1: "#FFFFFF" };

  const { all, xs, ys, Y, nowX, nowY } = geo;
  const fmt = (p: number) => `$${p.toFixed(2)}`;
  const cy = Y(confirm), ty = trigger ? Y(trigger) : null;
  const labelX = w - geo.padR + 10;

  return (
    <div ref={wrapRef} className="relative w-full select-none" style={{ minHeight: h }}>
      {mounted && <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={ariaLabel} className="block">
        <defs>
          <linearGradient id={`sky${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={c.sky1} />
            <stop offset="1" stopColor={c.sky0} />
          </linearGradient>
          <linearGradient id={`sea${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={c.top} stopOpacity="0.95" />
            <stop offset="0.45" stopColor={c.mid} stopOpacity="0.92" />
            <stop offset="1" stopColor={c.deep} stopOpacity="1" />
          </linearGradient>
          <linearGradient id={`fade${uid}`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#fff" stopOpacity="0" />
            <stop offset="0.03" stopColor="#fff" stopOpacity="1" />
          </linearGradient>
          <mask id={`m${uid}`}><rect x="0" y="0" width={w} height={h} fill={`url(#fade${uid})`} /></mask>
          <radialGradient id={`glow${uid}`}>
            <stop offset="0" stopColor={up ? "#FDE68A" : "#FEF3C7"} stopOpacity="0.95" />
            <stop offset="1" stopColor={up ? "#FDE68A" : "#FEF3C7"} stopOpacity="0" />
          </radialGradient>
        </defs>

        <rect x="0" y="0" width={w} height={h} rx="12" fill={`url(#sky${uid})`} />

        <g mask={`url(#m${uid})`}>
          {/* 远景波:更浅、更慢、略低 —— 给画面一点纵深 */}
          <path ref={farRef} fill={c.far} fillOpacity={dark ? 0.18 : 0.35} />
          {/* 海水主体 */}
          <path ref={glowRef} fill={`url(#sea${uid})`} />
          {/* 水面泡沫线 */}
          <path ref={foamRef} fill="none" stroke={c.foam} strokeWidth="1.6" strokeLinecap="round" />
        </g>

        {/* 转折确认线 */}
        <line x1={geo.x0} x2={w - 8} y1={cy} y2={cy} stroke={c.line} strokeDasharray="4 4" />
        {/* 「现在」标签与确认线标签离得太近时,把确认线标签挪开,别叠字 */}
        {(() => {
          const dy = Math.abs(nowY - cy) < 22 ? (cy < nowY ? -14 : 14) : 0;
          return (
            <>
              <text x={labelX} y={cy - 5 + dy} fontSize="11" fill={c.soft}>{up ? "跌回" : "反弹到"} {fmt(confirm)}</text>
              <text x={labelX} y={cy + 9 + dy} fontSize="10" fill={c.soft}>{up ? "这一浪结束" : "新一浪开始"}</text>
            </>
          );
        })()}
        {ty != null && Math.abs(ty - cy) > 16 && (
          <>
            <line x1={geo.x0} x2={w - 8} y1={ty} y2={ty} stroke="#8B5CF6" strokeOpacity="0.45" strokeDasharray="1 4" />
            <text x={labelX} y={ty - 4} fontSize="10" fill="#8B5CF6" fillOpacity="0.85">🧪 {fmt(trigger!)}</text>
          </>
        )}

        {/* 浪尖 / 浪底标注:浪尖写在水面上方,浪底写进水里(白字) */}
        {all.slice(0, -1).map((p, i) => {
          const peak = p.kind === "peak";
          const y = ys[i];
          // 贴左边的往右写,贴着浮标的往左写 —— 不出画框、不压浮标
          const nearL = xs[i] < 44, nearR = xs[i] > nowX - 48;
          const x = nearL ? xs[i] + 2 : nearR ? xs[i] - 6 : xs[i];
          const anchor = nearL ? "start" : nearR ? "end" : "middle";
          return (
            <g key={i}>
              {peak && <circle cx={xs[i]} cy={y} r="9" fill={`url(#glow${uid})`} />}
              <text x={x} y={peak ? y - 9 : y + 16} fontSize="11" fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
                textAnchor={anchor} fill={peak ? c.label : "rgba(255,255,255,0.95)"}>
                {fmt(p.price)}
              </text>
              <text x={x} y={peak ? y - 21 : y + 28} fontSize="9.5" textAnchor={anchor}
                fill={peak ? c.soft : "rgba(255,255,255,0.75)"}>
                {p.tentative ? "暂定" : p.date.slice(5).replace("-", "/")}
              </text>
            </g>
          );
        })}

        {/* 浮标 = 现在 */}
        <g ref={buoyRef}>
          <circle cx={nowX} cy={nowY} r="11" fill={up ? "#FBBF24" : "#F59E0B"} fillOpacity="0.22" className="wave-pulse" />
          <circle cx={nowX} cy={nowY} r="5.5" fill={up ? "#FBBF24" : "#F59E0B"} stroke="#fff" strokeWidth="2" />
        </g>
        <text x={labelX} y={nowY + 4} fontSize="12" fontWeight="600" fill={c.label}
          fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace">现在 {fmt(price)}</text>

        <style>{`
          .wave-pulse { transform-box: fill-box; transform-origin: center; animation: wavePulse 2.6s ease-out infinite; }
          @keyframes wavePulse { 0% { transform: scale(0.6); opacity: .55 } 100% { transform: scale(1.9); opacity: 0 } }
          @media (prefers-reduced-motion: reduce) { .wave-pulse { animation: none; } }
        `}</style>
      </svg>}
    </div>
  );
}
