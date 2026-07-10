"use client";

/* 🏇 策略战绩 — 2026-07-08 起替代因子排行榜(因子挖矿已归档,mining.md 是档案)。
 * 七套验证过的模型在全部历史(~2年)上的规则复算:买卖点位、整体收益、当前状态。
 * 数据由后端 dashboard/replay.py 在每日发布时算好,随 snapshot 下发。 */

import { useEffect, useState } from "react";
import { getSnapshot, type StrategyReplay, type ReplayStrategy } from "../_lib/data";

const pct = (v: number | null | undefined, digits = 0) =>
  typeof v === "number" && !isNaN(v) ? `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%` : "—";
const retColor = (v: number) => (v >= 0 ? "text-emerald-600" : "text-red-600");

function StrategyCard({ s }: { s: ReplayStrategy }) {
  const [showAll, setShowAll] = useState(false);
  const trades = showAll ? s.trades : s.trades.slice(0, 5);
  const st = s.stats, cur = s.current;
  return (
    <section className="bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] p-5">
      {/* 名称 + 当前状态 */}
      <div className="flex items-center justify-between gap-2 flex-wrap mb-1.5">
        <span className="text-sm font-bold text-[#1C1C1E]">{s.emoji} {s.name}</span>
        <span className={`text-[11px] font-bold px-2.5 py-1 rounded-full ${
          cur.in_market ? "bg-emerald-100 text-emerald-700" : "bg-[#F2F2F7] text-gray-500"}`}>
          {cur.in_market
            ? `在场 ${(cur.exposure * 100).toFixed(0)}%${cur.sym ? ` · ${cur.sym}` : ""}${cur.since ? ` · ${cur.since} 入 $${cur.entry_px?.toFixed(2)} · 浮 ${pct(cur.unreal, 1)}` : ""}`
            : cur.triggered_today ? "今日触发 · 日内单" : "空仓等待"}
        </span>
      </div>
      <p className="text-[12px] text-gray-400 leading-relaxed mb-3">{s.rule}</p>

      {/* 整体收益 */}
      <div className="grid grid-cols-5 gap-1.5 text-center mb-3">
        {([
          ["全期(2年)", pct(st.ret_full), retColor(st.ret_full)],
          ["近1年", pct(st.ret_1y), retColor(st.ret_1y)],
          ["最大回撤", pct(st.max_dd), "text-amber-600"],
          ["交易段", `${st.n_trades}`, "text-[#525461]"],
          ["段胜率", st.win_rate != null ? `${(st.win_rate * 100).toFixed(0)}%` : "—",
           st.win_rate != null && st.win_rate >= 0.5 ? "text-emerald-600" : "text-red-500"],
        ] as [string, string, string][]).map(([label, val, color]) => (
          <div key={label} className="bg-[#F6F6F8] rounded-xl px-1 py-2">
            <div className="text-[10px] text-gray-400">{label}</div>
            <div className={`text-[13px] font-bold font-mono ${color}`}>{val}</div>
          </div>
        ))}
      </div>

      {/* 历史买卖点位 */}
      {s.trades.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-[10px] text-gray-400 text-left">
                <th className="py-1 font-normal">买入</th>
                <th className="py-1 font-normal">卖出</th>
                <th className="py-1 font-normal text-right">天数</th>
                <th className="py-1 font-normal text-right">段收益</th>
              </tr>
            </thead>
            <tbody>
              {trades.map(t => (
                <tr key={`${t.buy_date}-${t.sym ?? ""}`} className={`border-t border-[#F2F2F7] ${t.open ? "bg-emerald-50/60" : ""}`}>
                  <td className="py-1.5 font-mono whitespace-nowrap">
                    {t.sym && <span className="mr-1 text-[10px] font-bold text-[#007AFF] bg-blue-50 rounded px-1 py-0.5">{t.sym}</span>}
                    {t.buy_date} <span className="text-gray-400">@</span> ${t.buy_px.toFixed(2)}</td>
                  <td className="py-1.5 font-mono whitespace-nowrap">
                    {t.open
                      ? <span className="text-emerald-700 font-semibold">持仓中</span>
                      : <>{t.sell_date} <span className="text-gray-400">@</span> ${t.sell_px?.toFixed(2)}</>}
                  </td>
                  <td className="py-1.5 text-right font-mono text-gray-500">{t.days}</td>
                  <td className={`py-1.5 text-right font-mono font-semibold ${retColor(t.ret)}`}>{pct(t.ret, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {s.trades.length > 5 && (
            <button onClick={() => setShowAll(!showAll)}
              className="mt-1.5 text-[11px] text-[#007AFF] font-semibold">
              {showAll ? "收起" : `展开最近 ${s.trades.length} 段(全历史共 ${s.n_trades_total} 段)`}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

export default function StrategyRecordPage() {
  const [replay, setReplay] = useState<StrategyReplay | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getSnapshot()
      .then(s => {
        if (s.strategy_replay) setReplay(s.strategy_replay);
        else setErr("战绩数据还没生成 — 跑一次「生成今日决策」(publish)后就有了。");
      })
      .catch(e => setErr(e instanceof Error ? e.message : "加载失败"));
  }, []);

  return (
    <main className="max-w-3xl mx-auto px-4 py-6 space-y-4">
      <div>
        <h1 className="text-xl font-bold text-[#1C1C1E]">🏇 策略战绩</h1>
        <p className="text-[12px] text-gray-400 mt-1">
          七套验证模型的全历史规则复算 —— 过去每一次买卖点位、整体收益、当前状态。
          {replay && <> 数据截至 <b>{replay.as_of}</b> · 窗口 {replay.window_start} 起 · 死拿对照:全期 {pct(replay.bh.ret_full)} / 近1年 {pct(replay.bh.ret_1y)} / 回撤 {pct(replay.bh.max_dd)}</>}
        </p>
      </div>

      {/* 诚实声明 */}
      <div className="bg-amber-50 rounded-2xl px-4 py-3 text-[12px] leading-relaxed text-amber-900">
        ⚠️ <b>这是回测复算,不是实盘记录。</b>点位按各策略规则在历史数据上重放(0.2%/边成本,收盘成交),
        每天随新 K 线滚动更新,数字会与 mining.md 档案的冻结值有出入;首页「策略马厩」才是 7/2 起的实盘模拟台账,
        两者起始条件不同、当前状态可能不同。全部策略统计上仍属<b>验证期</b>(冻结至 8/15,凭台账定去留)。
        因子挖矿已归档,本页替代原因子排行榜。
      </div>

      {err && <div className="bg-white rounded-2xl px-4 py-6 text-center text-sm text-gray-400">{err}</div>}
      {!err && !replay && <div className="bg-white rounded-2xl px-4 py-6 text-center text-sm text-gray-400">加载中…</div>}
      {replay?.strategies.filter(s => s.tier !== "watch").map(s => <StrategyCard key={s.key} s={s} />)}

      {/* 👀 观察组:观察名单候选的前向战绩(未晋升,8/15 凭记录+判活标准复查) */}
      {replay?.strategies.some(s => s.tier === "watch") && (
        <>
          <div className="pt-3">
            <h2 className="text-sm font-bold text-[#525461]">👀 观察组 · 未晋升</h2>
            <p className="text-[11px] text-gray-400 mt-0.5 leading-relaxed">
              挖矿观察名单的候选(各轮判活差一口气的信号)——同框记战绩,但<b>不进决策、不算在册马</b>;
              8/15 审判时凭记录 + 预注册判活标准复查,过线才升马。卡片规则里写明了各自出身轮次与没晋升的原因。
            </p>
          </div>
          {replay.strategies.filter(s => s.tier === "watch").map(s => <StrategyCard key={s.key} s={s} />)}
        </>
      )}

      <div className="text-center text-[10px] text-gray-400">
        规则与回测口径见 mining.md · 仅供研究参考,非投资建议
      </div>
    </main>
  );
}
