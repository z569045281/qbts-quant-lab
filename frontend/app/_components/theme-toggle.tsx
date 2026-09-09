"use client";

import { useEffect, useState } from "react";

/** 夜间模式开关:切 <html class="dark"> 并存 localStorage。变暗由 globals.css
 *  重定义整套 Tailwind 调色板变量完成 —— 2026-09-09 换掉了原来的整页 invert
 *  滤镜,那个会把 K 线图和涨跌色一起反相。canvas 图表另走 _lib/theme.ts。 */
export function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const next = !document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", next);
    try { localStorage.theme = next ? "dark" : "light"; } catch {}
    setDark(next);
  }

  return (
    <button
      onClick={toggle}
      aria-label="切换夜间模式"
      title={dark ? "切到白天" : "切到夜晚"}
      className="shrink-0 w-8 h-8 flex items-center justify-center rounded-inner
                 text-on-navy hover:bg-white/10 transition-colors text-section leading-none"
    >
      {dark ? "☀️" : "🌙"}
    </button>
  );
}
