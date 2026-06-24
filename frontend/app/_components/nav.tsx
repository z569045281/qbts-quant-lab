"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { READONLY } from "../_lib/supabase";

const tabs = [
  { href: "/",        label: "🎯 决策仪表盘", desc: "Today's verdict" },
  { href: "/watch",   label: "🔭 自选扫描",   desc: "Watchlist scan"  },
  { href: "/dca",     label: "📥 定投专区",   desc: "DCA seasonality" },
  { href: "/factors", label: "🏆 因子排行榜", desc: "Mined factors"   },
  // The mining console only works against the local backend — hide it on the
  // read-only public deployment.
  ...(READONLY ? [] : [{ href: "/mine", label: "⛏️ 因子挖矿", desc: "AI factor lab" }]),
];

export function NavBar() {
  const path = usePathname();
  return (
    <header className="bg-gradient-to-r from-[#0F1B2E] via-[#1A2942] to-[#0F1B2E] border-b border-blue-900/40">
      <div className="max-w-[1600px] mx-auto px-6 py-3 flex items-center gap-6">
        <div className="font-bold text-white text-sm tracking-wide">
          QBTS <span className="text-[#3B82F6]">Quant Lab</span>
        </div>
        <nav className="flex gap-1">
          {tabs.map(t => {
            const active = path === t.href || (t.href !== "/" && path?.startsWith(t.href));
            return (
              <Link key={t.href} href={t.href}
                    className={`px-3.5 py-1.5 rounded-md text-sm font-medium transition-all
                      ${active
                        ? "bg-[#006FFF] text-white shadow-md shadow-blue-500/30"
                        : "text-blue-100 hover:bg-white/10"}`}>
                {t.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto text-xs text-blue-200/60 font-mono">QBTS · D-Wave Quantum Inc.</div>
      </div>
    </header>
  );
}
