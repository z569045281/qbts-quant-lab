"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getCryptoChallenge, type CryptoChallenge } from "../_lib/data";

const money = (n: number | undefined) =>
  typeof n === "number" ? `$${n.toLocaleString("en-US", { maximumFractionDigits: 2 })}` : "—";

const STATUS: Record<string, { label: string; cls: string }> = {
  running: { label: "进行中", cls: "bg-blue-50 text-[#006FFF] border-blue-200" },
  won:     { label: "🏆 已达标", cls: "bg-emerald-50 text-emerald-600 border-emerald-200" },
  halted:  { label: "🛑 已停止", cls: "bg-red-50 text-red-600 border-red-200" },
  ended:   { label: "⏱ 到期结束", cls: "bg-gray-50 text-gray-600 border-gray-200" },
};

function daysLeft(deadline: string): number {
  const ms = new Date(deadline + "T23:59:59Z").getTime() - Date.now();
  return Math.max(0, Math.ceil(ms / 86_400_000));
}

export default function ChallengePage() {
  const [c, setC]         = useState<CryptoChallenge | null>(null);
  const [loaded, setLoad] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getCryptoChallenge()
      .then(setC)
      .catch(e => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoad(true));
  }, []);

  if (!loaded) {
    return <main className="max-w-[900px] mx-auto px-6 py-10 text-sm text-[#525461]">加载挑战状态中…</main>;
  }
  if (error) {
    return (
      <main className="max-w-[900px] mx-auto px-6 py-10">
        <div className="bg-white rounded-xl border border-red-200 p-6">
          <div className="text-sm font-semibold text-[#F03A3E] mb-2">⚠️ 加载失败</div>
          <pre className="text-xs font-mono text-[#525461] bg-red-50 rounded-md px-3 py-2 whitespace-pre-wrap">{error}</pre>
        </div>
      </main>
    );
  }
  if (!c) {
    return (
      <main className="max-w-[900px] mx-auto px-6 py-10">
        <div className="bg-white rounded-xl border border-[#EDEDF0] p-8 text-center">
          <div className="text-4xl mb-3">🎰</div>
          <h1 className="text-lg font-bold text-gray-900">$1000 → +$100 一个月挑战</h1>
          <p className="text-sm text-[#525461] mt-2">挑战尚未初始化 —— bot 首次推送状态后这里就会亮起来。</p>
        </div>
      </main>
    );
  }

  const s     = STATUS[c.status] ?? STATUS.running;
  const gained = Math.max(0, c.pnl);
  const target = c.win_line - c.sleeve_start;                  // $100 / $500
  const prog  = Math.min(100, Math.max(0, (c.pnl / target) * 100));
  const pos   = c.position;
  const win   = c.status === "won";
  const marathon = !!c.marathon;
  const gainColor = c.pnl > 0 ? "text-emerald-600" : c.pnl < 0 ? "text-[#F03A3E]" : "text-gray-900";

  return (
    <main className="max-w-[900px] mx-auto px-4 sm:px-6 py-5 sm:py-6 space-y-5">
      {/* ── Hero: equity + progress toward +$100 ── */}
      <section className="bg-white rounded-xl border border-[#EDEDF0] px-6 py-5">
        <div className="flex items-start justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-lg font-bold text-gray-900">
              {marathon
                ? <>🏁 {money(c.sleeve_start)} 马拉松挑战 · 跑到 {c.deadline.slice(5).replace("-", "/")}</>
                : <>🎰 {money(c.sleeve_start)} → +{money(target)} 一个月挑战</>}
              {(c.round ?? 1) > 1 && <span className="ml-2 text-xs font-medium text-[#006FFF] bg-blue-50 border border-blue-200 rounded-full px-2 py-0.5 align-middle">第 {c.round} 期</span>}
            </h1>
            <p className="text-xs text-[#525461] mt-0.5">
              纸面盘（Alpaca paper）· {c.runner === "cloud"
                ? <><span className="font-medium">云端 Lambda 全自动</span> · 全场杠杆 ETF 动量</>
                : <><span className="font-medium">无加密</span> · 杠杆指数 ETF 动量</>} · 触碰即落袋
            </p>
          </div>
          <span className={`text-xs px-2.5 py-1 rounded-full border font-medium ${s.cls}`}>{s.label}</span>
        </div>

        <div className="mt-5 flex items-end gap-6 flex-wrap">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500">账本权益</div>
            <div className="text-3xl font-bold font-mono text-gray-900">{money(c.equity)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500">盈亏</div>
            <div className={`text-3xl font-bold font-mono ${gainColor}`}>
              {c.pnl >= 0 ? "+" : ""}{money(c.pnl)}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500">收益率</div>
            <div className={`text-2xl font-bold font-mono ${gainColor}`}>{c.pnl_pct >= 0 ? "+" : ""}{c.pnl_pct}%</div>
          </div>
          <div className="ml-auto text-right">
            <div className="text-[10px] uppercase tracking-wider text-gray-500">剩余天数</div>
            <div className="text-2xl font-bold font-mono text-gray-900">
              {win ? "—" : daysLeft(c.deadline)}
            </div>
            <div className="text-[10px] text-gray-400">截止 {c.deadline}</div>
          </div>
        </div>

        {/* progress bar toward the +10% line(马拉松=里程碑,老规则=达标线) */}
        <div className="mt-5">
          <div className="flex justify-between text-[11px] text-[#525461] mb-1">
            <span>{marathon ? "里程碑" : "目标"}进度 · 赚到 {money(gained)} / {money(target)}
              {marathon && c.milestone_at && <span className="ml-1 text-emerald-600 font-medium">🏆 已达成,继续跑</span>}</span>
            <span className="font-mono">{prog.toFixed(0)}%</span>
          </div>
          <div className="h-2.5 rounded-full bg-[#EDEDF0] overflow-hidden">
            <div className={`h-full rounded-full transition-all ${(win || (marathon && c.milestone_at)) ? "bg-emerald-500" : "bg-[#006FFF]"}`}
                 style={{ width: `${Math.max(prog, 2)}%` }} />
          </div>
          <div className="flex justify-between text-[10px] text-gray-400 mt-1 font-mono">
            <span>本金 {money(c.sleeve_start)}</span>
            <span>地板 {money(c.floor_line)}</span>
            <span>{marathon ? "里程碑" : "达标"} {money(c.win_line)}</span>
          </div>
        </div>
      </section>

      {/* ── 📈 资金曲线 ── */}
      {(c.equity_curve?.length ?? 0) >= 2 && (
        <section className="bg-white rounded-xl border border-[#EDEDF0] px-6 py-4">
          <div className="flex items-baseline justify-between mb-2">
            <h2 className="text-sm font-semibold text-gray-900">📈 资金曲线</h2>
            <span className="text-[10px] text-gray-400">每 15 分钟一点 · 峰值 {money(c.peak_equity)}</span>
          </div>
          <EquityChart curve={c.equity_curve!} start={c.sleeve_start}
                       winLine={c.win_line} floorLine={c.floor_line} />
        </section>
      )}

      {/* ── 复盘与心法入口 ── */}
      <Link href="/challenge/lessons"
            className="block bg-gradient-to-r from-[#EEF4FF] to-[#F3EEFF] rounded-xl border border-blue-200
                       px-6 py-4 hover:shadow-md transition-shadow">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-gray-900">🧠 复盘与心法 · 从这次挑战学到什么</div>
            <div className="text-xs text-[#525461] mt-0.5">
              哪些能每月照做、哪些是运气、赔率的诚实数学 —— 以及按同一套纪律,<b>今天</b>该做什么
            </div>
          </div>
          <span className="text-[#006FFF] text-lg shrink-0">→</span>
        </div>
      </Link>

      {/* ── Current position ── */}
      <section className="bg-white rounded-xl border border-[#EDEDF0] px-6 py-4">
        <h2 className="text-sm font-semibold text-gray-900 mb-3">当前持仓</h2>
        {pos ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <Stat label="标的" value={pos.symbol} mono />
            <Stat label="数量 / 成本" value={`${pos.qty} 股 · ${money(pos.invested)}`} mono />
            <Stat label="入场 → 现价" value={`${money(pos.entry_px)} → ${money(pos.cur_px)}`} mono />
            <Stat label="浮动盈亏"
                  value={pos.unreal != null ? `${pos.unreal >= 0 ? "+" : ""}${money(pos.unreal)}` : "—"}
                  mono cls={pos.unreal != null ? (pos.unreal >= 0 ? "text-emerald-600" : "text-[#F03A3E]") : ""} />
            <Stat label="止盈 (TP)" value={money(pos.tp_px)} mono cls="text-emerald-600" />
            <Stat label="止损 (STOP)" value={money(pos.stop_px)} mono cls="text-[#F03A3E]" />
          </div>
        ) : (
          <p className="text-sm text-[#525461]">
            空仓 —— {c.status === "running"
              ? "等待篮子里出现上升趋势信号（保护本金，不硬凑单）。"
              : "挑战已结束。"}
          </p>
        )}
        <div className="mt-3 text-[11px] text-gray-400">
          篮子：{c.basket.join(" · ")}
        </div>
      </section>

      {/* ── Strategy / honest odds ── */}
      <section className="bg-white rounded-xl border border-[#EDEDF0] px-6 py-4 space-y-2 text-sm text-[#525461]">
        <h2 className="text-sm font-semibold text-gray-900">打法与赢面</h2>
        <p>只在 <b>上升趋势</b>（收盘价站上 50 日线且近一周上涨）时进场，集中押动量最强的杠杆 ETF
           {(c.round ?? 1) > 1 && <>（第 {c.round} 期起扩到<b>全场 ~40 只宇宙</b>，同款门槛）</>}，
           进场即挂 <b className="text-emerald-600">止盈</b> + <b className="text-[#F03A3E]">−12% 止损</b> 的 bracket 单，浮盈触 +10% 即落袋{marathon && <>（落袋当日冷却，次日再进场）</>}。
           {marathon
             ? <>🏁 <b>马拉松模式</b>：不设收手线，持续交易到 <b>{c.deadline}</b>，到期看 {money(c.sleeve_start)} 滚成多少；{money(c.win_line)} 只是里程碑，−15% 地板仍<b>硬性停手</b>。</>
             : <>权益触碰 <b>+{money(target)} 判赢收手</b>，−15% 触及地板则本期停手。</>}</p>
        <p className="text-[13px] bg-[#F6F6F8] rounded-md px-3 py-2 border border-[#EDEDF0]">
          📊 {c.odds_note}
        </p>
      </section>

      {/* ── Activity log ── */}
      {c.history?.length > 0 && (
        <section className="bg-white rounded-xl border border-[#EDEDF0] px-6 py-4">
          <h2 className="text-sm font-semibold text-gray-900 mb-2">交易日志</h2>
          <div className="space-y-1 max-h-72 overflow-y-auto">
            {[...c.history].reverse().map((h, i) => (
              <div key={i} className="text-[11px] font-mono text-[#525461] leading-relaxed">{h}</div>
            ))}
          </div>
        </section>
      )}

      <div className="text-center text-[10px] text-gray-400">
        状态由{c.runner === "cloud" ? "云端挑战 bot（AWS Lambda）" : "本地挑战 bot "}每 15 分钟推送到 Supabase · 更新于 {c.updated_at} · 纸面模拟, 非投资建议
      </div>
    </main>
  );
}

/** 纯 SVG 资金曲线:时间 × 权益,参考线 = 本金/里程碑/地板。静态导出零依赖。 */
function EquityChart({ curve, start, winLine, floorLine }:
    { curve: [string, number][]; start: number; winLine: number; floorLine: number }) {
  const W = 640, H = 240, PAD = { l: 54, r: 14, t: 12, b: 22 };
  const pts = curve
    .map(([t, v]) => ({ ms: new Date(t).getTime(), v }))
    .filter(p => Number.isFinite(p.ms) && Number.isFinite(p.v))
    .sort((a, b) => a.ms - b.ms);
  if (pts.length < 2) return null;

  const x0 = pts[0].ms, x1 = pts[pts.length - 1].ms || x0 + 1;
  const vs = pts.map(p => p.v);
  const yLo = Math.min(floorLine, ...vs) * 0.995;
  const yHi = Math.max(winLine, ...vs) * 1.005;
  const X = (ms: number) => PAD.l + ((ms - x0) / Math.max(1, x1 - x0)) * (W - PAD.l - PAD.r);
  const Y = (v: number) => PAD.t + (1 - (v - yLo) / (yHi - yLo)) * (H - PAD.t - PAD.b);

  const path = pts.map((p, i) => `${i ? "L" : "M"}${X(p.ms).toFixed(1)},${Y(p.v).toFixed(1)}`).join("");
  const area = `${path}L${X(x1).toFixed(1)},${(H - PAD.b).toFixed(1)}L${PAD.l},${(H - PAD.b).toFixed(1)}Z`;
  const last = pts[pts.length - 1];
  const up = last.v >= start;
  const line = up ? "#059669" : "#F03A3E";
  const fmtD = (ms: number) => {
    const d = new Date(ms);
    return `${d.getMonth() + 1}/${d.getDate()}`;
  };
  const Ref = ({ v, color, label }: { v: number; color: string; label: string }) => (
    <g>
      <line x1={PAD.l} x2={W - PAD.r} y1={Y(v)} y2={Y(v)} stroke={color} strokeWidth="1" strokeDasharray="4 4" opacity="0.55" />
      <text x={PAD.l - 6} y={Y(v) + 3.5} textAnchor="end" fontSize="10" fill={color} fontFamily="ui-monospace,monospace">
        {label}
      </text>
    </g>
  );

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="挑战资金曲线">
      <Ref v={winLine}   color="#059669" label={`$${winLine.toLocaleString()}`} />
      <Ref v={start}     color="#9CA3AF" label={`$${start.toLocaleString()}`} />
      <Ref v={floorLine} color="#F03A3E" label={`$${floorLine.toLocaleString()}`} />
      <path d={area} fill={line} opacity="0.08" />
      <path d={path} fill="none" stroke={line} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={X(last.ms)} cy={Y(last.v)} r="3.5" fill={line} />
      <text x={Math.min(X(last.ms), W - PAD.r - 4)} y={Math.max(Y(last.v) - 8, 11)} textAnchor="end"
            fontSize="11" fontWeight="600" fill={line} fontFamily="ui-monospace,monospace">
        ${last.v.toLocaleString("en-US", { maximumFractionDigits: 0 })}
      </text>
      <text x={PAD.l} y={H - 6} fontSize="10" fill="#9CA3AF" fontFamily="ui-monospace,monospace">{fmtD(x0)}</text>
      <text x={W - PAD.r} y={H - 6} textAnchor="end" fontSize="10" fill="#9CA3AF" fontFamily="ui-monospace,monospace">{fmtD(x1)}</text>
    </svg>
  );
}

function Stat({ label, value, mono, cls }: { label: string; value: string; mono?: boolean; cls?: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-gray-500">{label}</div>
      <div className={`font-semibold text-gray-900 ${mono ? "font-mono" : ""} ${cls ?? ""}`}>{value}</div>
    </div>
  );
}
