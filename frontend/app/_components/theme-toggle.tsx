"use client";

import { useEffect, useState } from "react";

/** 夜间模式开关:切 <html class="dark"> 并存 localStorage。实际变暗由
 *  globals.css 的整页 invert 滤镜完成(零改色类)。 */
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
      className="shrink-0 w-8 h-8 flex items-center justify-center rounded-md
                 text-blue-100 hover:bg-white/10 transition-colors text-base leading-none"
    >
      {dark ? "☀️" : "🌙"}
    </button>
  );
}
