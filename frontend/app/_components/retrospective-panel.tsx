"use client";

/* 月度复盘 — a model-written review of the accumulated track record.
   The button is LOCKED until RETRO_UNLOCK (a month out) because a review is
   meaningless until ~a month of predictions has piled up. Once unlocked it
   reads the latest persisted retrospective from Supabase (generation happens
   server-side via `retrospective.py` / the local 控制台). */

import { Fragment, useState } from "react";
import { getRetrospective, type Retrospective } from "../_lib/data";

/** Unlock date — a month after the feature shipped (2026-06-26). */
const RETRO_UNLOCK = "2026-07-26";

function daysUntil(dateStr: string): number {
  const now = new Date();
  const target = new Date(`${dateStr}T00:00:00`);
  return Math.ceil((target.getTime() - now.getTime()) / 86_400_000);
}

/* Tiny markdown-lite renderer — enough for the model's ## headers / - lists /
   **bold**. Avoids pulling in a markdown dependency for one panel. */
function renderMd(md: string) {
  return md.split("\n").map((line, i) => {
    if (/^#{1,6}\s/.test(line)) {
      return (
        <h4 key={i} className="mt-3 mb-1 text-sm font-bold text-gray-800">
          {inline(line.replace(/^#{1,6}\s/, ""))}
        </h4>
      );
    }
    if (/^\s*[-*]\s/.test(line)) {
      return (
        <div key={i} className="flex gap-1.5 pl-1 text-xs leading-relaxed text-gray-700">
          <span className="text-gray-400">•</span>
          <span>{inline(line.replace(/^\s*[-*]\s/, ""))}</span>
        </div>
      );
    }
    if (!line.trim()) return <div key={i} className="h-1.5" />;
    return (
      <p key={i} className="text-xs leading-relaxed text-gray-700">
        {inline(line)}
      </p>
    );
  });
}

function inline(text: string) {
  // Split on **bold** and alternate plain / strong.
  return text.split(/\*\*(.+?)\*\*/g).map((part, i) =>
    i % 2 === 1 ? <strong key={i} className="font-semibold text-gray-900">{part}</strong>
                : <Fragment key={i}>{part}</Fragment>,
  );
}

export function RetrospectivePanel() {
  const left = daysUntil(RETRO_UNLOCK);
  const locked = left > 0;
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [retro, setRetro] = useState<Retrospective | null>(null);
  const [loaded, setLoaded] = useState(false);

  const onClick = async () => {
    if (open) { setOpen(false); return; }
    setOpen(true);
    if (!loaded) {
      setLoading(true);
      setRetro(await getRetrospective());
      setLoaded(true);
      setLoading(false);
    }
  };

  return (
    <div className="mt-4 border-t border-[#F0F0F2] pt-3">
      <button
        onClick={onClick}
        disabled={locked}
        className={`w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium rounded-lg border transition ${
          locked
            ? "border-[#EDEDF0] bg-[#F6F6F8] text-gray-400 cursor-not-allowed"
            : "border-indigo-200 bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
        }`}
      >
        {locked
          ? <>🔒 月度复盘 · 还需 {left} 天解锁（攒够一个月数据）</>
          : <>🔮 月度复盘 {open ? "· 点击收起" : "· 让模型复盘这一个月"}</>}
      </button>

      {locked && (
        <p className="mt-1.5 text-[10px] text-gray-400 text-center">
          {RETRO_UNLOCK} 解锁 · 到时点开,模型会读完累计战绩,写一份「校准如何 / 哪个信号有用 / 有没有真 edge / 下一步」的复盘
        </p>
      )}

      {open && !locked && (
        <div className="mt-2 rounded-lg bg-[#FAFAFB] border border-[#EDEDF0] px-3.5 py-3">
          {loading ? (
            <div className="text-xs text-gray-400 py-4 text-center">读取中…</div>
          ) : retro ? (
            <>
              <div className="text-[10px] text-gray-400 mb-1.5">
                复盘区间 {retro.period_start ?? "—"} → {retro.period_end ?? "—"}
              </div>
              {renderMd(retro.report_md || "（复盘内容为空）")}
            </>
          ) : (
            <div className="text-xs text-gray-500 py-3 leading-relaxed">
              还没有生成过复盘。在<b>本地控制台</b>点「🔮 生成复盘」(或运行
              <code className="mx-1 px-1 bg-gray-100 rounded">python retrospective.py</code>),
              生成后这里就会显示。
            </div>
          )}
        </div>
      )}
    </div>
  );
}
