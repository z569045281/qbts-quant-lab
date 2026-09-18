"use client";

/* 🎯 QBTS $1000 纸面挑战(Claude 自营)。状态由 Lambda 每个交易日 15:52 ET 写入
   crypto_challenge id='qbts1000';这里只读。纸面盘,非真金。 */

import { useEffect, useState } from "react";
import { getQbtsChallenge, type QbtsChallenge } from "../_lib/data";

const money = (n: number | null | undefined, sign = false) =>
  typeof n === "number"
    ? `${sign && n > 0 ? "+" : ""}${n < 0 ? "−" : ""}$${Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 2 })}`
    : "—";
const tone = (n: number | null | undefined) =>
  typeof n !== "number" || n === 0 ? "text-gray-900" : n > 0 ? "text-emerald-600" : "text-down";

export function QbtsChallengeCard() {
  const [c, setC] = useState<QbtsChallenge | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    getQbtsChallenge().then(setC).catch(() => {}).finally(() => setLoaded(true));
  }, []);

  if (!loaded) return null;
  if (!c) {
    return (
      <section className="bg-surface rounded-inner border border-hairline px-6 py-5">
        <h2 className="text-card font-bold text-gray-900">🎯 QBTS $1000 · Claude 自营</h2>
        <p className="text-body text-ink-muted mt-1">
          还没开张 —— 下一个交易日 15:52 ET(墨尔本早上约 5:52)第一次调仓后这里会亮起来。
        </p>
      </section>
    );
  }

  const monthKey = Object.keys(c.months ?? {}).sort().pop();
  const month = monthKey ? c.months[monthKey] : null;
  const monthPnl = month?.pnl ?? month?.pnl_so_far ?? null;
  const monthRet = month && monthPnl != null ? monthPnl / month.start_equity : null;
  const bh = month?.bh_ret ?? month?.bh_so_far ?? null;
  const pct = (v: number | null) => v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
  const sig = c.last_signal;
  const trades = [...(c.trades ?? [])].reverse();
  const pastMonths = Object.entries(c.months ?? {})
    .filter(([, m]) => m.end_equity != null).sort(([a], [b]) => b.localeCompare(a));

  return (
    <section className="bg-surface rounded-inner border border-hairline px-6 py-5 space-y-4">
      <div className="flex items-start justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-section font-bold text-gray-900">🎯 QBTS $1000 · Claude 自营</h2>
          <p className="text-body text-ink-muted mt-0.5">
            纸面盘(Alpaca paper)· 只买卖 QBTS 正股 · 自 {c.started} 起 · 每个交易日 15:52 ET 调仓一次
          </p>
        </div>
        <span className="text-body px-2.5 py-1 rounded-full border font-medium bg-blue-50 text-brand border-blue-200">
          {c.status === "running" ? "进行中" : "已结束"}
        </span>
      </div>

      <div className="flex items-end gap-6 flex-wrap">
        <div>
          <div className="text-meta text-ink-faint">权益</div>
          <div className="text-display font-bold font-mono text-gray-900">{money(c.equity)}</div>
        </div>
        <div>
          <div className="text-meta text-ink-faint">累计盈亏</div>
          <div className={`text-price font-bold font-mono ${tone(c.pnl)}`}>
            {money(c.pnl, true)} ({c.pnl_pct >= 0 ? "+" : ""}{c.pnl_pct}%)
          </div>
        </div>
        <div>
          <div className="text-meta text-ink-faint">持仓</div>
          <div className="text-card font-mono text-gray-900">
            {c.shares > 0 ? `${c.shares} 股 @ 均价 $${c.avg_px?.toFixed(2)}` : "空仓"}
          </div>
          <div className="text-meta text-ink-faint">现金 {money(c.cash)}</div>
        </div>
      </div>

      {month && (
        <div className="text-body text-gray-700">
          <span className="font-semibold">{monthKey} 本月:</span>{" "}
          <span className={`font-mono ${tone(monthPnl)}`}>{money(monthPnl, true)}({pct(monthRet)})</span>
          <span className="text-ink-faint"> · 同月一直拿着 QBTS </span>
          <span className={`font-mono ${tone(bh)}`}>{pct(bh)}</span>
        </div>
      )}

      {sig && (
        <div className="text-body text-gray-700 bg-gray-50 rounded-inner px-3 py-2">
          <span className="font-semibold">{sig.date} 信号:</span>{" "}
          {sig.risk_on
            ? <>🟢 QQQ ${sig.qqq} 在 50 日线 ${sig.qqq_ma50} 上 → 目标仓位 {(sig.w * 100).toFixed(0)}%(波动率 {(sig.rv20 * 100).toFixed(0)}%)= {sig.target_shares} 股</>
            : <>🔴 QQQ ${sig.qqq} 在 50 日线 ${sig.qqq_ma50} 下 → 空仓</>}
        </div>
      )}

      <div>
        <div className="text-card font-semibold text-gray-800 mb-1.5">📒 买卖记录</div>
        {trades.length === 0 ? (
          <p className="text-body text-ink-faint">还没有成交。</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-body font-mono">
              <thead className="text-meta text-ink-faint text-left">
                <tr><th className="py-1 pr-3">日期</th><th className="pr-3">方向</th><th className="pr-3 text-right">股数</th>
                  <th className="pr-3 text-right">成交价</th><th className="pr-3 text-right">金额</th>
                  <th className="pr-3 text-right">已实现</th><th className="font-sans">原因</th></tr>
              </thead>
              <tbody>
                {trades.map((t, i) => (
                  <tr key={i} className="border-t border-hairline">
                    <td className="py-1 pr-3">{t.date}</td>
                    <td className={`pr-3 ${t.side === "buy" ? "text-emerald-600" : "text-down"}`}>{t.side === "buy" ? "买入" : "卖出"}</td>
                    <td className="pr-3 text-right">{t.qty}</td>
                    <td className="pr-3 text-right">${t.px.toFixed(2)}{t.approx_px ? "≈" : ""}</td>
                    <td className="pr-3 text-right">{money(t.value)}</td>
                    <td className={`pr-3 text-right ${tone(t.realized)}`}>{t.realized != null ? money(t.realized, true) : "—"}</td>
                    <td className="font-sans text-ink-muted">{t.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {pastMonths.length > 0 && (
        <div>
          <div className="text-card font-semibold text-gray-800 mb-1.5">📅 月度成绩(对照:一直拿着 QBTS)</div>
          <div className="space-y-1 text-body font-mono">
            {pastMonths.map(([k, m]) => (
              <div key={k} className="flex gap-3">
                <span>{k}</span>
                <span className={tone(m.pnl)}>{money(m.pnl, true)}({pct(m.ret ?? null)})</span>
                <span className="text-ink-faint">拿着 QBTS {pct(m.bh_ret ?? null)}</span>
                <span>{m.ret != null && m.bh_ret != null ? (m.ret > m.bh_ret ? "✅ 跑赢" : "❌ 跑输") : ""}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <details className="text-meta text-ink-muted">
        <summary className="cursor-pointer">规则与预期</summary>
        <p className="mt-1.5 leading-relaxed">{c.rule}</p>
        <p className="mt-1 leading-relaxed">
          上线时的回测预期:近 12 个月月均 −0.1%,一半月份亏钱,12 个月里只有 3 个月赚到 ≥10%。
          没有证据支持「每月稳定赚钱」—— 这是公开记账的实盘测试,对照是同期一直拿着 QBTS。纸面盘,非投资建议。
        </p>
      </details>
    </section>
  );
}
