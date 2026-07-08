"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  getSnapshot, getCryptoChallenge,
  type CryptoChallenge, type ChallengeBasket,
} from "../../_lib/data";

const pct = (n: number | undefined | null, digits = 1) =>
  typeof n === "number" ? `${n >= 0 ? "+" : ""}${(n * 100).toFixed(digits)}%` : "—";
const money = (n: number | undefined | null) =>
  typeof n === "number" ? `$${n.toLocaleString("en-US", { maximumFractionDigits: 2 })}` : "—";

/* ── 六条从第一期挑战里拆出来的可复制纪律 ── */
const RULES = [
  {
    icon: "🧱", title: "隔离本金",
    rule: "挑战仓是独立的 $1000,输光也不影响生活。",
    why: "军规⓪:投机总仓位 ≤ 总资产 10%。能亏得起,才拿得住纪律。",
  },
  {
    icon: "🌬️", title: "只在顺风进场",
    rule: "收盘站上 50 日线 且 近一周上涨 —— 两条硬门,缺一不玩。",
    why: "本库十三轮回测里「QQQ>50日线」是所有冠军策略的公共腿,被验证最多次的过滤器。空仓等待也是执行。",
  },
  {
    icon: "🎯", title: "集中最强动量",
    rule: "合格标的里只押动量最强的一只,不摊薄。",
    why: "杠杆 ETF 有波动衰减(第七轮实测),所以短持有 + 强动量,绝不长拿。",
  },
  {
    icon: "🔒", title: "进场即挂 bracket",
    rule: "+10% 止盈 / −12% 止损随单挂好,之后不看盘、不改单。",
    why: "把情绪从执行里物理隔离 —— 第一笔赢单是挂单自己成交的,不是盯出来的。",
  },
  {
    icon: "💰", title: "触线就收手",
    rule: "权益摸到 +$100 判赢,立刻全清落袋。",
    why: "第二笔只赚 $20 就平了,因为权益到线。浮盈变真钱,靠的就是这一步,不是行情。",
  },
  {
    icon: "🛑", title: "地板停手",
    rule: "权益 −15% 触地板($850),本月直接停手不再交易。",
    why: "输的月份亏损有上限,才能一直留在牌桌上等下一个顺风月。",
  },
];

export default function ChallengeLessonsPage() {
  const [basket, setBasket] = useState<ChallengeBasket | null>(null);
  const [chal, setChal]     = useState<CryptoChallenge | null>(null);
  const [loaded, setLoad]   = useState(false);

  useEffect(() => {
    Promise.allSettled([
      getSnapshot().then(s => setBasket(s.challenge_basket ?? null)),
      getCryptoChallenge().then(setChal),
    ]).finally(() => setLoad(true));
  }, []);

  const pickEtf = basket?.etfs.find(e => e.ticker === basket?.pick);

  return (
    <main className="max-w-[900px] mx-auto px-4 sm:px-6 py-5 sm:py-6 space-y-5">
      {/* ── Hero ── */}
      <section className="bg-white rounded-xl border border-[#EDEDF0] px-6 py-5">
        <div className="flex items-start justify-between flex-wrap gap-2">
          <h1 className="text-lg font-bold text-gray-900">🧠 千元挑战 · 复盘与心法</h1>
          <Link href="/challenge" className="text-xs text-[#006FFF] hover:underline">← 返回挑战看板</Link>
        </div>
        <p className="text-sm text-[#525461] mt-2 leading-relaxed">
          第一期(2026-07):$1,000 → <b className="text-emerald-600">$1,106.97(+10.7%)</b>,
          2 笔交易、6 个交易日,提前 24 天达标。
          这一页把这次赢拆开:<b>哪些是可以每月照做的纪律,哪些只是运气</b> ——
          以及按同一套纪律,今天该做什么。
        </p>
        {chal && (
          <p className="text-[11px] text-gray-400 mt-2 font-mono">
            live:状态 {chal.status} · 权益 {money(chal.equity)} · 更新于 {chal.updated_at}
          </p>
        )}
      </section>

      {/* ── 复盘:钱是怎么来的 ── */}
      <section className="bg-white rounded-xl border border-[#EDEDF0] px-6 py-4">
        <h2 className="text-sm font-semibold text-gray-900 mb-3">复盘 · 这 +10.7% 是怎么来的</h2>
        <ol className="space-y-2 text-sm text-[#525461]">
          <li className="flex gap-2">
            <span className="shrink-0 font-mono text-[11px] text-gray-400 pt-0.5">07-01</span>
            <span>进场 <b>LABU</b>(3× 生科多头)3 股 @ $289.90,随单挂 bracket(TP $323.23 / STOP $255.11),然后<b>什么都不做</b>。</span>
          </li>
          <li className="flex gap-2">
            <span className="shrink-0 font-mono text-[11px] text-gray-400 pt-0.5">07-07</span>
            <span>持有 6 天后止盈单自己成交:<b className="text-emerald-600">+$86.97</b> —— 占全部利润的 <b>81%</b>。</span>
          </li>
          <li className="flex gap-2">
            <span className="shrink-0 font-mono text-[11px] text-gray-400 pt-0.5">07-07</span>
            <span>按规则立刻再进 LABU;30 分钟后权益摸到 +$100 赢线,<b className="text-emerald-600">+$20</b> 全清收手。🏆</span>
          </li>
        </ol>
        <div className="mt-4 text-[13px] bg-amber-50 border border-amber-200 rounded-md px-3 py-2.5 text-amber-800 leading-relaxed">
          ⚠️ <b>不可复制的部分(诚实账):</b>挑战期恰逢 LABU 史诗级行情
          {typeof pickEtf?.mom20 === "number" && pickEtf.ticker === "LABU"
            ? <>(至今 20 日动量 <b>{pct(pickEtf.mom20)}</b>)</>
            : "(20 日动量一度接近翻倍)"}
          ,同期 SOXL / TQQQ 反而在 50 日线下走弱。
          「押合格者里最强的」是纪律,但强到这个程度是运气。
          <b>n=2 在统计上什么也证明不了</b> —— 这不是谦虚,是数学;赔率是否真有 60%,要靠多做几期攒样本。
        </div>
      </section>

      {/* ── 六条可复制的纪律 ── */}
      <section className="bg-white rounded-xl border border-[#EDEDF0] px-6 py-4">
        <h2 className="text-sm font-semibold text-gray-900 mb-3">可以复制的六条纪律</h2>
        <div className="grid sm:grid-cols-2 gap-3">
          {RULES.map(r => (
            <div key={r.title} className="rounded-lg border border-[#EDEDF0] bg-[#FAFAFB] px-4 py-3">
              <div className="text-sm font-semibold text-gray-900">{r.icon} {r.title}</div>
              <div className="text-[13px] text-gray-700 mt-1">{r.rule}</div>
              <div className="text-[12px] text-[#8A8A8E] mt-1.5 leading-relaxed">{r.why}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── 今日照做面板 ── */}
      <section className="bg-white rounded-xl border border-[#EDEDF0] px-6 py-4">
        <div className="flex items-baseline justify-between flex-wrap gap-2 mb-3">
          <h2 className="text-sm font-semibold text-gray-900">今日照做 · 同一套纪律现在怎么看</h2>
          {basket?.as_of && <span className="text-[11px] text-gray-400 font-mono">数据截至 {basket.as_of} · 每日发布刷新</span>}
        </div>

        {!loaded ? (
          <p className="text-sm text-[#525461]">加载中…</p>
        ) : !basket ? (
          <p className="text-sm text-[#525461]">篮子读数还没随每日发布生成 —— 下次 09:00 ET publish 后这里会亮起来。</p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider text-gray-500 border-b border-[#EDEDF0]">
                    <th className="py-1.5 pr-3">标的</th>
                    <th className="py-1.5 pr-3">收盘</th>
                    <th className="py-1.5 pr-3">vs 50日线</th>
                    <th className="py-1.5 pr-3">近一周</th>
                    <th className="py-1.5 pr-3">20日动量</th>
                    <th className="py-1.5">合格</th>
                  </tr>
                </thead>
                <tbody>
                  {basket.etfs.map(e => {
                    const isPick = e.ticker === basket.pick;
                    return (
                      <tr key={e.ticker}
                          className={`border-b border-[#F4F4F6] last:border-0 ${isPick ? "bg-emerald-50/60" : ""}`}>
                        <td className="py-2 pr-3 font-mono font-semibold text-gray-900">
                          {e.ticker}{isPick && <span className="ml-1.5 text-[10px] text-emerald-600 font-sans font-medium">今日之选</span>}
                        </td>
                        {e.error ? (
                          <td colSpan={5} className="py-2 text-gray-400">{e.error}</td>
                        ) : (
                          <>
                            <td className="py-2 pr-3 font-mono text-gray-700">{money(e.close)}</td>
                            <td className={`py-2 pr-3 font-mono ${e.above_50dma ? "text-emerald-600" : "text-[#F03A3E]"}`}>
                              {e.above_50dma ? "✓ 上方" : "✗ 下方"}
                            </td>
                            <td className={`py-2 pr-3 font-mono ${(e.week_ret ?? 0) >= 0 ? "text-emerald-600" : "text-[#F03A3E]"}`}>
                              {pct(e.week_ret)}
                            </td>
                            <td className={`py-2 pr-3 font-mono ${(e.mom20 ?? 0) >= 0 ? "text-emerald-600" : "text-[#F03A3E]"}`}>
                              {pct(e.mom20)}
                            </td>
                            <td className="py-2">{e.uptrend ? "✅" : "—"}</td>
                          </>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {basket.pick && pickEtf ? (
              <div className="mt-3 rounded-md bg-emerald-50 border border-emerald-200 px-3 py-2.5 text-[13px] text-emerald-800">
                按第一期同款纪律,今天合格 {basket.n_qualified} 只,之选 <b>{basket.pick}</b>:
                进场参考 ≈ {money(pickEtf.close)},随单挂 TP <b>{money(pickEtf.tp)}</b>(+10%)
                / STOP <b>{money(pickEtf.stop)}</b>(−12%),权益 +$100 收手、−15% 停手。
              </div>
            ) : (
              <div className="mt-3 rounded-md bg-[#F6F6F8] border border-[#EDEDF0] px-3 py-2.5 text-[13px] text-[#525461]">
                今天<b>没有合格标的</b> —— 按纪律应该空仓等待。不硬凑单,这也是这套打法的一部分。
              </div>
            )}
            <p className="text-[11px] text-gray-400 mt-2">{basket.note}</p>
          </>
        )}
      </section>

      {/* ── 诚实的数学 ── */}
      <section className="bg-white rounded-xl border border-[#EDEDF0] px-6 py-4">
        <h2 className="text-sm font-semibold text-gray-900 mb-3">诚实的数学 · 这个游戏的期望值</h2>
        <div className="grid sm:grid-cols-2 gap-3 text-[13px]">
          <div className="rounded-lg border border-[#EDEDF0] px-4 py-3">
            <div className="font-semibold text-gray-900 mb-1">🧚 童话版(不会发生)</div>
            <p className="text-[#525461] leading-relaxed">
              每月稳赢 +10%,一年 $1,000 → <b>$3,138</b>。
              一次达标 ≠ 每次达标 —— 把 +10.7% 外推成年化,是最常见的自欺。
            </p>
          </div>
          <div className="rounded-lg border border-[#EDEDF0] px-4 py-3">
            <div className="font-semibold text-gray-900 mb-1">🧮 现实版(按 bot 自己的回测赔率)</div>
            <p className="text-[#525461] leading-relaxed">
              约 60% 概率月内触到 +10%(赢 +$100),输时平均约 −$120(止损/地板)。
              期望 ≈ <b>+$12/月(约 +1.2%)</b>,一年约 $1,150 上下,方差很大:
              连输 3 期的概率约 6.4%(≈ −$360)。
            </p>
          </div>
        </div>
        <p className="text-[13px] text-[#525461] mt-3 leading-relaxed">
          结论:这套打法的<b>数学优势很薄</b>。它真正值钱的是两样东西:
          ①亏损有上限的生存结构(地板 + bracket),②不靠盯盘和意志力的执行纪律。
          想让 edge 变厚,路径只有一条:<b>多做几期攒样本</b>,证实(或证伪)那个 60%,
          并且只在大盘顺风的月份开局 —— 而不是加大单期赌注。
        </p>
      </section>

      {/* ── 下一步 ── */}
      <section className="bg-white rounded-xl border border-[#EDEDF0] px-6 py-4">
        <h2 className="text-sm font-semibold text-gray-900 mb-2">下一步 · 如果想让它替你赚真钱</h2>
        <ol className="list-decimal list-inside space-y-1.5 text-[13px] text-[#525461] leading-relaxed">
          <li>先跑<b>挑战 #2、#3(纸面)</b>攒样本:n=2 → n≥10,才知道 60% 赔率是真是假。</li>
          <li>要上真钱:从 <b>$100–200</b> 起步,永远 ≤ 总资产 10%(军规⓪),
              规则<b>一字不改</b>照做 —— 改了规则,就是另一个没验证过的系统。</li>
          <li>每一期的结果自动记录(看板读 live 表)。<b>输的那期尤其值钱</b> —— 那是在花钱买数据。</li>
        </ol>
      </section>

      <div className="text-center text-[10px] text-gray-400">
        纸面模拟复盘 · 今日面板为机械读数,不构成投资建议
      </div>
    </main>
  );
}
