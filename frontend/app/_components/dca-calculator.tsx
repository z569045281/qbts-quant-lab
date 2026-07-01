"use client";

import { useEffect, useMemo, useState } from "react";
import type { DcaResult } from "../_lib/data";

/* ─────────────────────────────────────────────────────────────────────────
   💰 定投计算器 + 复利希望机
   - 输入本次要投多少钱 → 按建议权重拆到每只 ETF(顺手给出约买几股)
   - 「记一笔」累计到 localStorage:每次定投回来输入,累计已投入自动增长
   - 把【累计已投入】按年化复利投影到 10 / 20 / 30 年后,给你一点盼头
   ponytail: 存 localStorage(本机)。要多设备同步再上 Supabase dca_contributions 表。
   ───────────────────────────────────────────────────────────────────────── */

interface Contribution { date: string; amount: number; }
const KEY = "dca_contributions_v1";

const usd = (n: number) =>
  "$" + Math.round(n).toLocaleString("en-US");
const today = () => new Date().toISOString().slice(0, 10);

function load(): Contribution[] {
  try {
    const raw = localStorage.getItem(KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.filter(c => typeof c?.amount === "number" && c.amount > 0) : [];
  } catch { return []; }
}
function save(list: Contribution[]) {
  try { localStorage.setItem(KEY, JSON.stringify(list)); } catch { /* 忽略隐私模式写入失败 */ }
}

export function DcaCalculator({
  weights, results,
}: {
  weights: Record<string, number>;
  results: DcaResult[];
}) {
  const [amount, setAmount] = useState<string>("");
  const [rate, setRate] = useState<string>("7");        // 年化%,默认 7(接近全球股票长期名义回报的保守估计)
  const [list, setList] = useState<Contribution[]>([]);

  useEffect(() => { setList(load()); }, []);

  const priceOf = useMemo(() => {
    const m: Record<string, number> = {};
    for (const r of results) if (r.price) m[r.ticker] = r.price;
    return m;
  }, [results]);

  const weightSum = Object.values(weights).reduce((a, b) => a + b, 0) || 100;
  const amt = Math.max(0, parseFloat(amount) || 0);
  const r = Math.max(0, parseFloat(rate) || 0) / 100;

  // 本次拆分:金额 × 权重占比
  const split = Object.entries(weights).map(([t, w]) => {
    const money = amt * (w / weightSum);
    const px = priceOf[t];
    return { t, w, money, shares: px ? money / px : null, price: px ?? null };
  });

  const totalInvested = list.reduce((a, c) => a + c.amount, 0);
  const horizons = [10, 20, 30];
  // 已投入的钱从今天起再复利 N 年(不含未来还会继续投的钱——那是额外的希望)
  const fv = (years: number) => totalInvested * Math.pow(1 + r, years);

  function addOne() {
    if (amt <= 0) return;
    const next = [...list, { date: today(), amount: amt }];
    setList(next); save(next); setAmount("");
  }
  function removeAt(i: number) {
    const next = list.filter((_, idx) => idx !== i);
    setList(next); save(next);
  }

  return (
    <section className="bg-white rounded-2xl border border-[#EDEDF0] p-5 shadow-sm space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-base">💰</span>
        <span className="text-sm font-semibold text-gray-800">定投计算器 · 复利希望机</span>
        <span className="ml-auto text-[10px] text-gray-400">数据存在本机浏览器</span>
      </div>

      {/* 输入本次金额 */}
      <div className="flex items-end gap-2 flex-wrap">
        <label className="flex flex-col gap-1">
          <span className="text-[11px] text-gray-500">本次要定投多少钱($)</span>
          <input
            type="number" inputMode="decimal" min={0} placeholder="例如 500"
            value={amount} onChange={e => setAmount(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") addOne(); }}
            className="w-36 px-3 py-2 rounded-lg border border-gray-300 font-mono text-sm
                       focus:outline-none focus:ring-2 focus:ring-[#006FFF]/40"
          />
        </label>
        <button
          onClick={addOne} disabled={amt <= 0}
          className="px-4 py-2 rounded-lg bg-[#006FFF] text-white text-sm font-semibold
                     disabled:opacity-40 hover:bg-[#0060DB] transition-colors"
        >
          记一笔 ✓
        </button>
      </div>

      {/* 本次拆分到每只 ETF */}
      {amt > 0 && split.length > 0 && (
        <div className="rounded-xl border border-black/5 bg-gray-50/60 p-3">
          <div className="text-[11px] text-gray-500 mb-1.5">这笔 {usd(amt)} 按建议权重应该这样买:</div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {split.map(s => (
              <div key={s.t} className="bg-white rounded-lg px-2.5 py-2 border border-black/5">
                <div className="flex items-center gap-1">
                  <span className="text-sm font-bold text-gray-900">{s.t}</span>
                  <span className="text-[10px] text-gray-400">{s.w}%</span>
                </div>
                <div className="font-mono font-semibold text-[#006FFF] text-sm">{usd(s.money)}</div>
                {s.shares != null && (
                  <div className="text-[10px] text-gray-400 font-mono">≈{s.shares.toFixed(2)} 股 @${s.price!.toFixed(0)}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 累计 + 复利投影 */}
      <div className="rounded-xl bg-gradient-to-br from-blue-50 to-emerald-50 border border-blue-100 p-4">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <div className="text-[11px] text-gray-500">累计已投入({list.length} 笔)</div>
            <div className="text-2xl font-bold text-gray-900 font-mono">{usd(totalInvested)}</div>
          </div>
          <label className="flex items-center gap-1.5 text-[11px] text-gray-500">
            假设年化
            <input
              type="number" inputMode="decimal" value={rate}
              onChange={e => setRate(e.target.value)}
              className="w-14 px-2 py-1 rounded border border-gray-300 font-mono text-sm text-center
                         focus:outline-none focus:ring-2 focus:ring-[#006FFF]/40"
            />
            %
          </label>
        </div>

        {totalInvested > 0 && r > 0 ? (
          <div className="mt-3 grid grid-cols-3 gap-2">
            {horizons.map(y => {
              const v = fv(y);
              return (
                <div key={y} className="bg-white/80 rounded-lg px-2 py-2.5 text-center">
                  <div className="text-[11px] text-gray-500">{y} 年后</div>
                  <div className="text-base font-bold text-emerald-600 font-mono leading-tight">{usd(v)}</div>
                  <div className="text-[10px] text-gray-400 font-mono">×{(v / totalInvested).toFixed(1)}</div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="mt-2 text-[11px] text-gray-400">记一笔、并填个年化%,这里就会显示复利后的样子。</p>
        )}
        <p className="mt-2.5 text-[10px] text-gray-400 leading-relaxed">
          按【已投入总额】从今天起复利 {rate || "?"}% 计算(未含你以后还会继续投的钱——那是额外的希望)。
          这只是数学外推、不是承诺:真实市场会大起大落,7% 是全球股票长期名义回报的保守参考。
        </p>
      </div>

      {/* 历史记录 */}
      {list.length > 0 && (
        <details className="text-[12px]">
          <summary className="cursor-pointer text-gray-500 select-none">定投记录({list.length} 笔) ▾</summary>
          <ul className="mt-2 space-y-1">
            {[...list].reverse().map((c, i) => {
              const realIdx = list.length - 1 - i;
              return (
                <li key={realIdx} className="flex items-center gap-2 text-gray-600">
                  <span className="font-mono text-gray-400">{c.date}</span>
                  <span className="font-mono font-semibold text-gray-800">{usd(c.amount)}</span>
                  <button onClick={() => removeAt(realIdx)}
                    className="ml-auto text-[11px] text-gray-300 hover:text-red-500 transition-colors">删除</button>
                </li>
              );
            })}
          </ul>
        </details>
      )}
    </section>
  );
}
