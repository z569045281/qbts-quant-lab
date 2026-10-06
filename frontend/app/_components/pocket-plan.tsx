"use client";

/* 📌 我的定投方案 · Pocket 4 只(2026-10-06 定)。
   放在定投专区最上面;实时卡片由页面用 state.pocket_etfs 渲染,这里是方案本身:
   比例、执行规则、能长到多少(计算器)、为什么不追涨、让钱变快的杠杆。
   结论来自当天的对话与数据核对 —— 具体数字(费率/CAPE/历史回报)都在 SOURCES。 */

import { useEffect, useState } from "react";

export const POCKET_WEIGHTS: Record<string, number> = {
  "DHHF.AX": 60, "CRED.AX": 20, "IEM.AX": 10, "IOO.AX": 10,
};

const PLAN = [
  { t: "DHHF", w: 60, name: "全球多元", why: "核心:约 8,000 家公司,澳洲 38% / 美国 40% / 其他发达 15% / 新兴 7%", fee: "0.19%", color: "bg-brand" },
  { t: "CRED", w: 20, name: "澳洲公司债", why: "压舱石:股灾时缓冲;澳元计价,没有汇率风险", fee: "0.25%", color: "bg-slate-500" },
  { t: "IEM",  w: 10, name: "新兴市场", why: "估值倾斜:全球最便宜的一块(CAPE 约 19,美股 41)", fee: "0.69%", color: "bg-amber-500" },
  { t: "IOO",  w: 10, name: "全球 100", why: "配角:科技巨头,最多 25%(前 10 大占 57%)", fee: "0.40%", color: "bg-purple-500" },
];

const KEY = "pocket-calc-v1";
const $ = (n: number) => `$${Math.round(n).toLocaleString("en-US")}`;

function fv(monthly: number, years: number, r: number, grow: number) {
  let bal = 0;
  for (let m = 0; m < years * 12; m++) {
    bal = bal * (1 + r / 12) + monthly * Math.pow(1 + grow, Math.floor(m / 12));
  }
  return bal;
}

function Calculator() {
  const [monthly, setMonthly] = useState(500);
  const [years, setYears] = useState(30);
  const [grow, setGrow] = useState(3);
  useEffect(() => {
    try {
      const s = JSON.parse(localStorage.getItem(KEY) || "null");
      if (s) { setMonthly(s.monthly ?? 500); setYears(s.years ?? 30); setGrow(s.grow ?? 3); }
    } catch { /* 用默认值 */ }
  }, []);
  useEffect(() => {
    try { localStorage.setItem(KEY, JSON.stringify({ monthly, years, grow })); } catch { /* 忽略 */ }
  }, [monthly, years, grow]);

  const principal = (() => { let p = 0; for (let m = 0; m < years * 12; m++) p += monthly * Math.pow(1 + grow / 100, Math.floor(m / 12)); return p; })();
  const infl = Math.pow(1.03, years);
  const rows = [0.04, 0.06, 0.08].map(r => ({ r, n: fv(monthly, years, r, grow / 100) }));

  const field = (label: string, v: number, set: (n: number) => void, step: number, suffix = "") => (
    <label className="block">
      <span className="text-meta text-ink-muted">{label}</span>
      <div className="mt-0.5 flex items-center rounded-inner border border-hairline bg-surface px-2">
        <input type="number" inputMode="decimal" step={step} value={v}
          onChange={e => set(Math.max(0, Number(e.target.value) || 0))}
          className="w-full bg-transparent px-1 py-1.5 text-card font-mono outline-none" />
        {suffix && <span className="text-body text-ink-faint">{suffix}</span>}
      </div>
    </label>
  );

  return (
    <div className="rounded-inner border border-hairline bg-gray-50 px-3 py-3">
      <div className="text-body font-semibold text-gray-800">🧮 能长到多少</div>
      <div className="mt-2 grid grid-cols-3 gap-2">
        {field("每月投入($)", monthly, setMonthly, 100)}
        {field("坚持几年", years, setYears, 1)}
        {field("每年加投", grow, setGrow, 1, "%")}
      </div>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-body">
          <thead className="text-meta text-ink-faint text-left">
            <tr><th className="py-1 pr-2">年化</th><th className="pr-2 text-right">到时候的金额</th><th className="text-right">换成今天的钱(扣 3% 通胀)</th></tr>
          </thead>
          <tbody className="font-mono">
            {rows.map(({ r, n }) => (
              <tr key={r} className="border-t border-hairline">
                <td className="py-1 pr-2">{(r * 100).toFixed(0)}%</td>
                <td className="pr-2 text-right">{$(n)}</td>
                <td className="text-right font-semibold text-emerald-700">{$(n / infl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1.5 text-meta text-ink-muted">
        一共投入本金 {$(principal)}。这个组合(80% 股 + 20% 债)长期大概落在年化 5–7%,没人能保证;分红每年要交税,表里没扣。
      </p>
    </div>
  );
}

export function PocketPlan() {
  return (
    <section className="rounded-card border border-emerald-300 bg-emerald-50/30 p-4 sm:p-5 shadow-sm space-y-4">
      <div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-section">📌</span>
          <span className="text-card font-semibold text-gray-900">我的定投方案 · CommSec Pocket 4 只</span>
          <span className="ml-auto text-meta text-ink-faint">定于 2026-10-06</span>
        </div>
        <p className="mt-1 text-body text-gray-700">
          4 只都在澳洲注册(不用填 W-8BEN、没有美国遗产税风险),Pocket <b>2027-03-31 前免佣金</b>。
          这是 <b>10 年以上</b>的钱;买房首付另放,看「🏠 买房基金」。
        </p>
      </div>

      {/* 比例条 */}
      <div>
        <div className="flex h-7 overflow-hidden rounded-inner text-meta font-semibold text-white">
          {PLAN.map(p => (
            <div key={p.t} className={p.color} style={{ width: `${p.w}%` }} title={`${p.t} ${p.w}%`}>
              <span className="px-1.5 leading-7">{p.t} {p.w}%</span>
            </div>
          ))}
        </div>
        <div className="mt-2 space-y-1 text-body">
          {PLAN.map(p => (
            <div key={p.t} className="flex gap-2">
              <span className="w-12 shrink-0 font-mono font-semibold">{p.t}</span>
              <span className="text-gray-700">{p.name} · {p.why}</span>
              <span className="ml-auto shrink-0 font-mono text-ink-faint">{p.fee}</span>
            </div>
          ))}
        </div>
        <p className="mt-1.5 text-meta text-ink-muted">
          合起来:美国约 32%、澳洲 23%、新兴 14%、其他发达 11%、债券 20%;平均年费约 0.27%。
          想多押科技巨头,最多改成 DHHF 45 / IOO 25 / IEM 10 / CRED 20。
        </p>
      </div>

      {/* 执行规则 */}
      <div className="rounded-inner border border-hairline bg-surface px-3 py-2.5 text-body text-gray-700">
        <div className="font-semibold text-gray-800">✅ 怎么执行</div>
        <ol className="mt-1 ml-5 list-decimal space-y-0.5">
          <li>Pocket 里设<b>每月自动投资</b>,按 60 / 20 / 10 / 10 分。</li>
          <li><b>不卖出再平衡</b>:每月把新钱多放进占比偏低的那只(不卖就没有资本利得税),一年检查一次比例。</li>
          <li>跌的时候照买,不卖。能不能赚到下面的钱,就看这一条。</li>
          <li>2027-03-31 免佣结束后,每笔 $1,000 以内收 $2:每月总额只有几百块的话,改成每月只买一只最偏低的,轮着买。</li>
          <li>每次加薪,把每月投入同比例调高。</li>
        </ol>
      </div>

      <Calculator />

      {/* 为什么不追涨 */}
      <details className="rounded-inner border border-hairline bg-surface px-3 py-2.5">
        <summary className="cursor-pointer text-body font-semibold text-gray-800">🤔 DHHF 过去 5 年涨得少,为什么还选它</summary>
        <div className="mt-2 grid gap-3 sm:grid-cols-2 text-body">
          <div>
            <div className="text-meta text-ink-faint">过去 5 年(到 2026-10)</div>
            <table className="w-full font-mono"><tbody>
              <tr><td>IOO 全球 100</td><td className="text-right text-emerald-700">+126%</td></tr>
              <tr><td>DHHF</td><td className="text-right">+64%</td></tr>
              <tr><td>澳股 200(DHHF 里占 38%)</td><td className="text-right">+44%</td></tr>
            </tbody></table>
          </div>
          <div>
            <div className="text-meta text-ink-faint">2000–2009 那十年(含分红)</div>
            <table className="w-full font-mono"><tbody>
              <tr><td>IOO 全球 100</td><td className="text-right text-down">−1%</td></tr>
              <tr><td>标普 500</td><td className="text-right text-down">−8%</td></tr>
              <tr><td>纳指 100</td><td className="text-right text-down">−50%</td></tr>
              <tr><td>澳股(美元计)</td><td className="text-right text-emerald-700">+207%</td></tr>
            </tbody></table>
          </div>
        </div>
        <p className="mt-2 text-meta text-ink-muted">
          2000 年美股 CAPE 是 44,现在是 41。领涨的市场会轮换;按「过去 5 年谁涨得多」选基金,
          等于在最贵的时候买最贵的东西。DHHF 涨得少,是不把鸡蛋放一个篮子的代价。
        </p>
      </details>

      {/* 让钱变快的杠杆 */}
      <details className="rounded-inner border border-hairline bg-surface px-3 py-2.5">
        <summary className="cursor-pointer text-body font-semibold text-gray-800">🚀 嫌慢?真正让钱变快的是这些</summary>
        <div className="mt-2 text-body text-gray-700 space-y-1.5">
          <div className="text-meta text-ink-faint">30 年、年化 6%,换成今天的钱:</div>
          <table className="w-full"><tbody className="[&_td]:py-0.5">
            <tr><td>每月 $500,一直不变</td><td className="text-right font-mono">$20.7 万</td></tr>
            <tr><td>每月 $500,每年跟着加薪多存 3%</td><td className="text-right font-mono">$28.8 万</td></tr>
            <tr><td>每月 $1,500,每年多存 3%</td><td className="text-right font-mono font-semibold text-emerald-700">$86.5 万</td></tr>
            <tr><td>超级年金(年薪 $9 万时雇主交的 12%,你已经有了)</td><td className="text-right font-mono">$48.1 万</td></tr>
          </tbody></table>
          <ol className="ml-5 list-decimal space-y-0.5">
            <li><b>多存,而且投入跟着工资涨</b> —— 你自己能控制、效果最大的一项。</li>
            <li><b>收入</b>是最大的杠杆:年薪多 $1 万 ≈ 每月多存 $500,比把收益从 6% 提到 8% 管用。</li>
            <li><b>超级年金</b>:查管理费,投资选项选「高增长」(60 岁前取不出,适合最激进的选项)。</li>
            <li><b>买房</b>本身就是杠杆:首付 5–20% 拿整套房的涨幅 —— 看「🏠 买房基金」。</li>
          </ol>
          <div className="rounded-inner bg-amber-50 border border-amber-200 px-2 py-1.5 text-meta text-amber-800">
            更快但更险:GHHF(借钱买 DHHF,借款 30–40%,敞口约 1.4–1.7 倍,年费 0.35%)。股灾时可能跌 60% 以上,
            只适合 10 年以上、跌了绝不卖的钱。别用短线和杠杆 ETF 炒单只股票 —— 这套系统实测过,没有优势。
          </div>
        </div>
      </details>

      {/* 钱的先后顺序 */}
      <div className="text-body text-gray-700">
        <span className="font-semibold text-gray-800">💰 钱的先后顺序:</span>
        ① 应急金(3–6 个月生活费,放高息储蓄)→ ② 买房首付(储蓄 / 定存 / FHSS)→ ③ 剩下的长期钱放这 4 只。
      </div>
    </section>
  );
}
