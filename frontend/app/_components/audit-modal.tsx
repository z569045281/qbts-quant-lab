"use client";

/* 👀 隐藏点击审计查看窗 — 页面右下角版本号连点 3 次打开。
   数据:publish_audit(Lambda 每次真人点击写入:IP/UA/设备提示;cron 不记)。
   诚实边界:浏览器拿不到"计算机名",这里给的是 IP+系统/浏览器+时区+语言+屏幕
   的组合指纹 — 区分熟人足够。 */

import { useEffect, useState } from "react";
import { getPublishAudit, type PublishAuditRow } from "../_lib/data";

const ACTION_CN: Record<string, string> = {
  publish:      "🧠 出今天的决策",
  watch_add:    "➕ 加自选",
  watch_remove: "➖ 删自选",
  rescan:       "🔄 重扫自选",
  pos_add:      "💼 记持仓",
  pos_remove:   "💼 删持仓",
};

/** 从原始 UA 提炼「设备一句话」:系统 + 浏览器。 */
function device(ua: string | null, client: PublishAuditRow["client"]): string {
  const u = ua ?? "";
  const os =
    /iPhone/.test(u) ? "iPhone" :
    /iPad/.test(u) ? "iPad" :
    /Android/.test(u) ? "Android" :
    /Windows/.test(u) ? "Windows" :
    /Mac OS X|Macintosh/.test(u) ? "Mac" :
    /Linux/.test(u) ? "Linux" : (client?.platform || "未知系统");
  const br =
    /Edg\//.test(u) ? "Edge" :
    /SamsungBrowser/.test(u) ? "三星浏览器" :
    /Chrome\//.test(u) ? "Chrome" :
    /Firefox\//.test(u) ? "Firefox" :
    /Safari\//.test(u) ? "Safari" : "未知浏览器";
  return `${os} · ${br}`;
}

function fmtLocal(ts: string): string {
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function AuditModal({ onClose }: { onClose: () => void }) {
  const [rows, setRows]   = useState<PublishAuditRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPublishAudit(100).then(({ rows, error }) => {
      setRows(rows);
      setError(error ?? null);
    });
  }, []);

  // 按「IP + 设备」聚合的访客小结
  const visitors = new Map<string, { n: number; last: string; tz?: string }>();
  for (const r of rows ?? []) {
    const key = `${r.ip ?? "?"} · ${device(r.ua, r.client)}`;
    const v = visitors.get(key) ?? { n: 0, last: r.ts, tz: r.client?.tz };
    v.n += 1;
    if (r.ts > v.last) v.last = r.ts;
    visitors.set(key, v);
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
         onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full max-h-[80vh] overflow-hidden flex flex-col"
           onClick={e => e.stopPropagation()}>
        <div className="px-5 py-3.5 border-b border-[#EDEDF0] flex items-center">
          <span className="text-sm font-semibold text-gray-800">👀 谁点了按钮</span>
          <span className="ml-2 text-[10px] text-gray-400">Lambda 记录 · 定时任务不计入</span>
          <button onClick={onClose}
                  className="ml-auto text-gray-400 hover:text-gray-600 text-lg leading-none px-1">✕</button>
        </div>

        <div className="overflow-y-auto px-5 py-4 space-y-4 text-sm">
          {error && (
            <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              读取失败:{error}
              {/not exist|relation|schema/i.test(error) &&
                " — 需先在 Supabase SQL Editor 跑 sql/publish_audit_migration.sql 建表"}
            </div>
          )}
          {rows === null && !error && <div className="text-xs text-gray-400 py-6">加载中…</div>}
          {rows !== null && rows.length === 0 && !error && (
            <div className="text-xs text-gray-400 py-6">还没有点击记录(部署后第一次真人点击才会出现)</div>
          )}

          {visitors.size > 0 && (
            <div>
              <div className="text-[10px] font-semibold text-[#525461] uppercase tracking-wider mb-1.5">
                访客小结(按 IP+设备)
              </div>
              <div className="space-y-1">
                {[...visitors.entries()].map(([k, v]) => (
                  <div key={k} className="flex items-baseline gap-2 text-xs">
                    <span className="font-mono text-gray-800">{k}</span>
                    <span className="text-gray-400">{v.tz ? `时区 ${v.tz} · ` : ""}共 {v.n} 次 · 最近 {fmtLocal(v.last)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {(rows ?? []).length > 0 && (
            <div>
              <div className="text-[10px] font-semibold text-[#525461] uppercase tracking-wider mb-1.5">
                逐条记录(近 100 条 · 本地时间)
              </div>
              <div className="space-y-1.5">
                {(rows ?? []).map(r => (
                  <div key={r.id} className="flex items-baseline gap-2 text-xs flex-wrap">
                    <span className="font-mono text-gray-500 shrink-0">{fmtLocal(r.ts)}</span>
                    <span className="text-gray-800 shrink-0">{ACTION_CN[r.action] ?? r.action}</span>
                    <span className="font-mono text-gray-600">{r.ip}</span>
                    <span className="text-gray-500">{device(r.ua, r.client)}</span>
                    {r.client?.tz && <span className="text-gray-400">{r.client.tz}</span>}
                    {r.client?.screen && <span className="text-gray-300">{r.client.screen}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="text-[10px] text-gray-300 pt-1">
            采集口径:IP + User-Agent + 时区/语言/平台/屏幕(浏览器无法提供计算机名)· 表本身对站点读者可见
          </div>
        </div>
      </div>
    </div>
  );
}
