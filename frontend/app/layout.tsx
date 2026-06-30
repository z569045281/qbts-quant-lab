import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { NavBar } from "./_components/nav";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "QBTS Quant Lab",
  description: "QBTS factor mining + decision dashboard",
};

// viewport-fit=cover lets the bottom tab bar pad for the iPhone home indicator
// (env(safe-area-inset-bottom)); themeColor tints the mobile browser chrome to
// match the dark brand bar.
export const viewport: Viewport = {
  viewportFit: "cover",
  themeColor: "#0F1B2E",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-[#F6F6F8]">
        {/* 在 body 渲染前同步设定夜间模式,避免切换时闪烁。默认跟随系统偏好,
            用户手动选过则用 localStorage 记忆。 */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.theme;if(t==='dark'||(!t&&matchMedia('(prefers-color-scheme:dark)').matches))document.documentElement.classList.add('dark')}catch(e){}`,
          }}
        />
        <NavBar />
        {/* Pad past the fixed mobile tab bar (50px + home-indicator inset);
            desktop has no bottom bar so the padding collapses. */}
        <div className="flex-1 pb-[calc(50px_+_env(safe-area-inset-bottom))] md:pb-0">{children}</div>
      </body>
    </html>
  );
}
