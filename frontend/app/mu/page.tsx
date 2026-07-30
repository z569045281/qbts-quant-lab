"use client";

import { useEffect, useState } from "react";
import { getSnapshot, type SecondTickerBoards } from "../_lib/data";
import { Board } from "../_components/second-board";

/* ─────────────────────────────────────────────────────────────────────────
   🔬 第二考场 — 第二只票(当前 MU)的「涨/跌表态」测量轨。

   为什么有这一页(2026-07-30 用户点单):判决主体(方向表态)每个交易日只 +1
   个样本,9 月初才够 n=30 出第一次真判决 —— 而**一个考场的结论永远可能是运气**。
   加一只与 QBTS 低相关的票 = 样本速度翻倍 + 变成两场独立考试。

   这一页刻意**长得不像交易页**:没有入场价、没有止损、没有仓位、没有按钮。
   它是个成绩单,不是个下单界面。看到 down 表态也不要去买 QBTZ 的同类
   —— 没有任何东西会去执行这些表态,这是它能诚实的前提。
   ───────────────────────────────────────────────────────────────────────── */

export default function MuPage() {
  const [data, setData] = useState<SecondTickerBoards | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getSnapshot()
      .then(s => setData(s.second_ticker ?? null))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  const tickers = data?.tickers?.filter(t => data.boards[t]) ?? [];

  return (
    <main className="max-w-3xl mx-auto px-4 sm:px-6 py-4 space-y-4">
      <header className="space-y-1">
        <h1 className="text-lg font-bold text-gray-900">🔬 第二考场</h1>
        <p className="text-[12px] text-[#525461] leading-relaxed">
          第二只票的<b>涨/跌表态</b>测量轨。存在的理由:QBTS 那边每个交易日只攒 1 个样本,
          9 月初才够第一次真判决 —— 而<b>一个考场的结论永远可能是运气</b>。
          加一只与 QBTS 低相关的票,样本速度翻倍,而且变成两场独立考试:
          两边都显不出本事,那就是真没本事;只有一边行,那大概是噪声。
        </p>
        <p className="text-[12px] text-[#B45309] leading-relaxed">
          这一页没有入场价、没有止损、没有仓位、没有按钮 —— 它是成绩单,不是下单界面。
          看到「看跌」也不要去买反向 ETF:<b>没有任何东西会执行这些表态,这是它能诚实的前提。</b>
        </p>
      </header>

      {loading ? (
        <div className="text-sm text-[#525461] flex items-center gap-2 px-1">
          <span className="inline-block w-2.5 h-2.5 rounded-full bg-[#006FFF] animate-pulse" /> 读取台账…
        </div>
      ) : tickers.length === 0 ? (
        <div className="bg-white rounded-2xl border border-[#EDEDF0] p-8 text-center space-y-2">
          <p className="text-sm text-gray-500">测量轨还没有数据。</p>
          <p className="text-[12px] text-gray-400 leading-relaxed">
            需要先在 Supabase 跑一次{" "}
            <code className="font-mono bg-gray-100 px-1 rounded">sql/second_journal_migration.sql</code>
            ,然后等下一次发布(或本地跑一次决策)写入第一条表态。
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {tickers.map(t => <Board key={t} b={data!.boards[t]} />)}
        </div>
      )}

      <footer className="text-center text-[10px] text-gray-400 pb-4 leading-relaxed">
        🔬 第二考场 · 纯测量轨,<b>零决策权</b> · 不进 QBTS 的决策提示词(两个考场互相看答案就不独立了)
        · 与 QBTS 台账分池存放、分池判决 · 非投资建议
      </footer>
    </main>
  );
}
