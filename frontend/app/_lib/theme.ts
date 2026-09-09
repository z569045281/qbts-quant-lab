"use client";

import { useEffect, useState } from "react";

/* 主题只有一个真相源:<html> 上有没有 .dark。globals.css 靠它换整套调色板变量,
   Tailwind 的类因此自动跟着变 —— 但 canvas 图表(lightweight-charts)不吃 CSS,
   得把颜色当参数喂进去,所以这里把「现在是不是深色」暴露成 React 状态。

   2026-09-09 之前深色模式是整页 filter: invert(1),图表跟着被反相,红绿涨跌
   只能算「近似保留」;换成真配色之后,图表必须自己读色,否则会是个白盒子。 */
export function useDarkMode(): boolean {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const root = document.documentElement;
    const read = () => setDark(root.classList.contains("dark"));
    read();
    const mo = new MutationObserver(read);
    mo.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => mo.disconnect();
  }, []);

  return dark;
}

/** 读一个 CSS 变量的当前值(已按当前主题解析)。给 canvas 图表用。 */
export function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/** 图表配色 —— 浅深两套都从设计 token 里取,不再各写一份字面 hex。 */
export function chartTheme() {
  return {
    bg:       cssVar("--color-surface", "#FFFFFF"),
    text:     cssVar("--color-ink-muted", "#525461"),
    grid:     cssVar("--color-hairline", "#EDEDF0"),
    border:   cssVar("--color-hairline", "#EDEDF0"),
    up:       cssVar("--color-emerald-500", "#22C55E"),
    down:     cssVar("--color-down", "#F03A3E"),
  };
}
