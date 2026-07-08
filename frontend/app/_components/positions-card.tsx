"use client";

/* 💼 当前持仓 — 用户真金仓位记录 + 每日决策的逐笔 AI 操作建议。
 * 持仓存 Supabase(scan_paper 行 user_positions),编辑走 postPositionAction
 * (云 Lambda / 本地 FastAPI,与自选编辑同通道)。AI 建议来自 decision.position_advice,
 * 随「生成今日决策」更新 —— 新添的持仓要等下一次决策才有建议。 */

import { useState } from "react";
import {
  postPositionAction, WATCH_EDITABLE,
  type UserPosition, type PositionAdvice,
} from "../_lib/data";

const TICKERS = ["QBTS", "QBTX", "QBTZ"] as const;

const ADVICE_STYLE: Record<string, string> = {
  持有: "bg-[#F6F6F8] text-[#525461]",
  加仓: "bg-emerald-100 text-emerald-700",
  减仓: "bg-amber-100 text-amber-800",
  清仓: "bg-red-100 text-red-700",
};

export default function PositionsCard({ initial, prices, advice, adviceAsOf }: {
  initial: UserPosition[];
  prices: Partial<Record<string, number | null>>;   // ticker → 现价(live 优先)
  advice?: PositionAdvice[];
  adviceAsOf?: string;                               // 决策生成时间(建议的新鲜度)
}) {
  const [edited, setEdited] = useState<UserPosition[] | null>(null);
  const [form, setForm] = useState({ ticker: "QBTS" as string, qty: "", cost: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const list = edited ?? initial;

  async function save() {
    const qty = parseFloat(form.qty), cost = parseFloat(form.cost);
    if (!(qty > 0) || !(cost > 0)) { setErr("数量和成本都要填正数"); return; }
    setBusy(true); setErr(null);
    const r = await postPositionAction("pos_add", { ticker: form.ticker, qty, cost });
    setBusy(false);
    if (r.ok && r.positions) { setEdited(r.positions); setForm({ ...form, qty: "", cost: "" }); setOpen(false); }
    else setErr(r.error || "保存失败");
  }

  async function remove(ticker: string) {
    setBusy(true); setErr(null);
    const r = await postPositionAction("pos_remove", { ticker });
    setBusy(false);
    if (r.ok && r.positions) setEdited(r.positions);
    else setErr(r.error || "删除失败");
  }

  return (
    <section className="bg-white rounded-3xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_20px_rgba(0,0,0,0.05)] p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
          💼 当前持仓(真金)· AI 每日给操作建议
        </span>
        {WATCH_EDITABLE && (
          <button
            onClick={() => { setOpen(!open); setErr(null); }}
            className="text-[12px] font-semibold rounded-full px-3 py-1.5 bg-[#007AFF] text-white shadow-[0_1px_3px_rgba(0,122,255,0.4)] active:opacity-70">
            {open ? "收起" : "＋ 记一笔"}
          </button>
        )}
      </div>

      {/* 持仓行 */}
      {list.length === 0 ? (
        <div className="text-[13px] text-gray-400 bg-[#F6F6F8] rounded-xl px-4 py-3">
          还没有记录持仓。买入后点「＋ 记一笔」——之后每天生成决策时,AI 会对每笔持仓给出
          持有 / 加仓 / 减仓 / 清仓的建议(并核对执行军规,比如 QBTZ 不许过周末)。
        </div>
      ) : (
        <div className="space-y-2">
          {list.map(p => {
            const px = prices[p.ticker];
            const pnl = px && p.cost ? px / p.cost - 1 : null;
            const a = advice?.find(x => x.ticker === p.ticker);
            return (
              <div key={p.ticker} className="bg-[#F6F6F8] rounded-xl px-3.5 py-2.5 text-[13px] leading-relaxed">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <span>
                    <b>{p.ticker}</b>
                    <span className="text-gray-500"> {p.qty}股 @ ${p.cost.toFixed(2)}</span>
                    {p.date && <span className="text-[11px] text-gray-400"> · {p.date} 买入</span>}
                  </span>
                  <span className="flex items-center gap-2">
                    {px != null && pnl != null && (
                      <span className={`font-mono font-semibold ${pnl >= 0 ? "text-emerald-600" : "text-red-600"}`}>
                        ${px.toFixed(2)} · {pnl >= 0 ? "+" : ""}{(pnl * 100).toFixed(1)}%
                        (${((px - p.cost) * p.qty) >= 0 ? "+" : ""}{((px - p.cost) * p.qty).toFixed(0)})
                      </span>
                    )}
                    {WATCH_EDITABLE && (
                      <button onClick={() => remove(p.ticker)} disabled={busy}
                        className="text-gray-300 hover:text-red-500 text-sm px-1" title="删除这笔记录">✕</button>
                    )}
                  </span>
                </div>
                {a ? (
                  <div className="mt-1.5 flex items-start gap-2">
                    <span className={`shrink-0 text-[11px] font-bold px-2 py-0.5 rounded-full ${ADVICE_STYLE[a.advice] ?? ADVICE_STYLE["持有"]}`}>
                      {a.advice}
                    </span>
                    <span className="text-[12px] text-gray-500">{a.reason}</span>
                  </div>
                ) : (
                  <div className="mt-1.5 text-[11px] text-gray-400">
                    ⏳ 本笔还没有 AI 建议 —— 下次「生成今日决策」时会带上
                  </div>
                )}
              </div>
            );
          })}
          {adviceAsOf && advice && advice.length > 0 && (
            <div className="text-[11px] text-gray-400 px-1">建议生成于 {adviceAsOf} · 随每日决策更新,不是实时盯盘</div>
          )}
        </div>
      )}

      {/* 记一笔表单 */}
      {open && WATCH_EDITABLE && (
        <div className="mt-3 bg-[#F6F6F8] rounded-xl px-3.5 py-3 flex items-end gap-2 flex-wrap text-[13px]">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] text-gray-400">代码</span>
            <select value={form.ticker} onChange={e => setForm({ ...form, ticker: e.target.value })}
              className="rounded-lg border border-gray-200 bg-white px-2 py-1.5">
              {TICKERS.map(t => <option key={t}>{t}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] text-gray-400">数量(股)</span>
            <input inputMode="decimal" value={form.qty} onChange={e => setForm({ ...form, qty: e.target.value })}
              placeholder="如 42" className="w-24 rounded-lg border border-gray-200 bg-white px-2 py-1.5" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] text-gray-400">成本价($)</span>
            <input inputMode="decimal" value={form.cost} onChange={e => setForm({ ...form, cost: e.target.value })}
              placeholder="如 4.74" className="w-24 rounded-lg border border-gray-200 bg-white px-2 py-1.5" />
          </label>
          <button onClick={save} disabled={busy}
            className="rounded-full bg-[#007AFF] text-white font-semibold px-4 py-1.5 disabled:opacity-50 active:opacity-70">
            {busy ? "保存中…" : "保存"}
          </button>
          <span className="text-[11px] text-gray-400 basis-full">
            只支持 QBTS / QBTX / QBTZ(决策系统只认识它们);同代码再记 = 覆盖更新。
          </span>
          {err && <span className="text-[12px] text-red-600 basis-full">{err}</span>}
        </div>
      )}
    </section>
  );
}
