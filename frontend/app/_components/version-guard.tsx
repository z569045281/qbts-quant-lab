"use client";

import { useEffect, useState } from "react";
import versionData from "../../public/version.json";

/* 版本守卫:静态站部署后,已打开的旧标签页不会自动更新(浏览器缓存了旧 JS)。
   打包时 import 的 version 就是这份旧标签页里的值;运行时 fetch 同一个 version.json
   拿到的是最新部署的值——两者不一致 = 站点已更新、当前页是旧的 → 提示刷新。
   单一来源:public/version.json(改它即可,页脚版本号也读它)。 */
const BUILT_VERSION = (versionData as { version: string }).version;
const BASE = process.env.NEXT_PUBLIC_BASE_PATH || "";

export function VersionGuard() {
  const [stale, setStale] = useState(false);

  useEffect(() => {
    let stop = false;
    const check = async () => {
      try {
        // query-bust + no-store 双保险,绕过浏览器/CDN 缓存
        const r = await fetch(`${BASE}/version.json?t=${Date.now()}`, { cache: "no-store" });
        if (!r.ok) return;
        const j = await r.json();
        if (!stop && j?.version && j.version !== BUILT_VERSION) setStale(true);
      } catch { /* 离线/失败 → 忽略,不打扰 */ }
    };
    check();
    const id = setInterval(check, 5 * 60_000);       // 每 5 分钟查一次
    const onFocus = () => check();                    // 切回标签页时也查
    window.addEventListener("focus", onFocus);
    return () => { stop = true; clearInterval(id); window.removeEventListener("focus", onFocus); };
  }, []);

  if (!stale) return null;
  return (
    <button
      onClick={() => location.reload()}
      className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[60] px-4 py-2 rounded-full
                 bg-[#006FFF] text-white text-sm font-semibold shadow-lg shadow-blue-500/30
                 hover:bg-[#0060DB] transition-colors flex items-center gap-2 animate-pulse"
    >
      🔄 有新版本 · 点击刷新
    </button>
  );
}
