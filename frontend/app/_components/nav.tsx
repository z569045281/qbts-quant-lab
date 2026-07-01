"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { READONLY } from "../_lib/supabase";
import { ThemeToggle } from "./theme-toggle";

/* ── SF-Symbol-ish line icons for the mobile bottom tab bar.
   Monochrome, inheriting color via `currentColor` so selection is shown by
   tint alone (active = brand blue, idle = gray) — the iOS way, no filled pill. */
const ico = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

function IconDecision() {  // 🎯 target / today's verdict
  return (
    <svg width="25" height="25" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" {...ico} />
      <circle cx="12" cy="12" r="4.3" {...ico} />
      <circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" />
    </svg>
  );
}
function IconScan() {  // 🔭 magnifier / watchlist scan
  return (
    <svg width="25" height="25" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="11" cy="11" r="7" {...ico} />
      <line x1="16.2" y1="16.2" x2="20.5" y2="20.5" {...ico} />
    </svg>
  );
}
function IconDca() {  // 📥 download-into-tray / recurring buy-in
  return (
    <svg width="25" height="25" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 4v9" {...ico} />
      <path d="M8 9.5l4 4 4-4" {...ico} />
      <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" {...ico} />
    </svg>
  );
}
function IconFactors() {  // 🏆 ranked bars / leaderboard
  return (
    <svg width="25" height="25" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="4"    y="12" width="3.6" height="8"  rx="1.2" {...ico} />
      <rect x="10.2" y="7"  width="3.6" height="13" rx="1.2" {...ico} />
      <rect x="16.4" y="10" width="3.6" height="10" rx="1.2" {...ico} />
    </svg>
  );
}
function IconChallenge() {  // 🎰 target-hit / $1000→+$100 challenge
  return (
    <svg width="25" height="25" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 20V9M9 20V4M14 20v-7M19 20v-4" {...ico} />
      <path d="M3.5 20.5h17" {...ico} />
    </svg>
  );
}
function IconMine() {  // ⛏️ sparkles / AI factor lab (local only)
  return (
    <svg width="25" height="25" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3l1.4 7.6L21 12l-7.6 1.4L12 21l-1.4-7.6L3 12l7.6-1.4z" {...ico} />
      <path d="M18.6 3.7l.45 1.85 1.85.45-1.85.45-.45 1.85-.45-1.85-1.85-.45 1.85-.45z" {...ico} />
    </svg>
  );
}

const tabs = [
  { href: "/",        label: "🎯 决策仪表盘", short: "决策", Icon: IconDecision },
  { href: "/watch",   label: "🔭 自选扫描",   short: "扫描", Icon: IconScan     },
  { href: "/dca",     label: "📥 定投专区",   short: "定投", Icon: IconDca      },
  { href: "/factors", label: "🏆 因子排行榜", short: "因子", Icon: IconFactors  },
  { href: "/challenge", label: "🎰 千元挑战",  short: "挑战", Icon: IconChallenge },
  // The mining console only works against the local backend — hide it on the
  // read-only public deployment.
  ...(READONLY ? [] : [{ href: "/mine", label: "⛏️ 因子挖矿", short: "挖矿", Icon: IconMine }]),
];

function isActive(path: string | null, href: string) {
  return path === href || (href !== "/" && !!path?.startsWith(href));
}

export function NavBar() {
  const path = usePathname();
  return (
    <>
      {/* ── Top brand bar. On a phone it carries only the brand (tabs live in
            the bottom bar); on md+ the full tab row shows here. ── */}
      <header className="bg-gradient-to-r from-[#0F1B2E] via-[#1A2942] to-[#0F1B2E] border-b border-blue-900/40">
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-2.5 sm:py-3 flex items-center gap-3 sm:gap-6">
          <div className="font-bold text-white text-sm tracking-wide shrink-0 whitespace-nowrap">
            QBTS <span className="text-[#3B82F6]">Quant Lab</span>
          </div>
          <nav className="hidden md:flex flex-wrap gap-1">
            {tabs.map(t => {
              const active = isActive(path, t.href);
              return (
                <Link key={t.href} href={t.href}
                      className={`whitespace-nowrap px-3.5 py-1.5 rounded-md text-sm font-medium transition-all
                        ${active
                          ? "bg-[#006FFF] text-white shadow-md shadow-blue-500/30"
                          : "text-blue-100 hover:bg-white/10"}`}>
                  {t.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <span className="hidden lg:block text-xs text-blue-200/60 font-mono shrink-0">QBTS · D-Wave Quantum Inc.</span>
            <ThemeToggle />
          </div>
        </div>
      </header>

      {/* ── Mobile bottom tab bar — iOS style: translucent blurred material,
            hairline top separator, equal-width items, tint-only selection,
            and home-indicator safe-area padding. ── */}
      <nav
        className="md:hidden fixed bottom-0 inset-x-0 z-40 border-t border-black/[0.07]
                   bg-white/75 backdrop-blur-xl backdrop-saturate-150"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <div className="flex h-[50px]">
          {tabs.map(t => {
            const active = isActive(path, t.href);
            return (
              <Link key={t.href} href={t.href}
                    aria-current={active ? "page" : undefined}
                    className={`flex-1 flex flex-col items-center justify-center gap-0.5 transition-colors active:opacity-50
                      ${active ? "text-[#006FFF]" : "text-[#8A8A8E]"}`}>
                <t.Icon />
                <span className="text-[10px] font-medium leading-none tracking-wide">{t.short}</span>
              </Link>
            );
          })}
        </div>
      </nav>
    </>
  );
}
