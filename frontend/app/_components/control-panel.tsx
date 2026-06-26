"use client";

/* Control panel — runs the dashboard's jobs from buttons. Two modes:

   • CLOUD  (NEXT_PUBLIC_PUBLISH_URL set, e.g. the deployed GitHub Pages site):
       "出今天的决策" POSTs to the AWS Lambda Function URL; live quotes run
       themselves on a schedule, so they're shown as a status, not a toggle.

   • LOCAL  (no NEXT_PUBLIC_PUBLISH_URL): talks to the local FastAPI backend —
       publish + a real start/stop toggle for the quote pusher. Hides itself
       entirely when that backend isn't reachable. */

import { useCallback, useEffect, useRef, useState } from "react";
import { API } from "../_lib/api";

const PUBLISH_URL = process.env.NEXT_PUBLIC_PUBLISH_URL;

export function ControlPanel({ onPublished }: { onPublished: () => void }) {
  return PUBLISH_URL
    ? <CloudPanel onPublished={onPublished} />
    : <LocalPanel onPublished={onPublished} />;
}

/* ── CLOUD: button → Lambda Function URL; quotes are auto ─────────────────── */
function CloudPanel({ onPublished }: { onPublished: () => void }) {
  const [busy, setBusy]     = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const run = async () => {
    setBusy(true);
    setResult(null);
    try {
      const r = await fetch(PUBLISH_URL!, { method: "POST" });
      const j = await r.json().catch(() => ({}));
      if (r.ok && j.ok !== false) {
        setResult({ ok: true, msg: j.decision ? `决策已更新 · ${j.decision}` : "决策已更新" });
        onPublished();
      } else {
        setResult({ ok: false, msg: j.error || `HTTP ${r.status}` });
      }
    } catch (e) {
      setResult({ ok: false, msg: e instanceof Error ? e.message : "请求失败" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Shell>
      <button
        onClick={run}
        disabled={busy}
        className="px-3.5 py-2 text-sm font-medium rounded-lg bg-[#006FFF] text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
      >
        {busy
          ? <><span className="inline-block w-2.5 h-2.5 rounded-full bg-white animate-pulse" />出决策中…（约 1–2 分钟）</>
          : <>🧠 出今天的决策</>}
      </button>

      <span className="px-3 py-2 text-sm rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-700 flex items-center gap-2">
        <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
        实时报价 · 云端自动运行（盘前盘后）
      </span>

      {result && (
        <span className={`text-xs ${result.ok ? "text-emerald-600" : "text-[#F03A3E]"}`}>
          {result.ok ? `✓ ${result.msg}` : `✗ ${result.msg}`}
        </span>
      )}

      <p className="basis-full mt-2 text-[11px] text-[#9A9CA5]">
        「出决策」在云端跑全套分析（Opus 4.8 ≈ $0.1）并更新本页 · 实时报价由云端每分钟自动推送，无需手动开关
      </p>
    </Shell>
  );
}

/* ── LOCAL: talks to the FastAPI backend; real publish + pusher toggle ────── */
interface PublishState {
  running: boolean;
  started_at: string | null;
  finished_at: string | null;
  ok: boolean | null;
  log: string;
}
interface ControlStatus {
  publish: PublishState;
  pusher: { running: boolean; pid: number | null };
}

function LocalPanel({ onPublished }: { onPublished: () => void }) {
  const [status, setStatus]       = useState<ControlStatus | null>(null);
  const [reachable, setReachable] = useState<boolean | null>(null);
  const [busy, setBusy]           = useState<string | null>(null);
  const [retroMsg, setRetroMsg]   = useState<string | null>(null);
  const wasRunning = useRef(false);

  const pollOnce = useCallback(async (): Promise<boolean> => {
    try {
      const r = await fetch(`${API}/control/status`, { cache: "no-store" });
      if (!r.ok) throw new Error();
      const s: ControlStatus = await r.json();
      setStatus(s);
      setReachable(true);
      if (wasRunning.current && !s.publish.running) onPublished();
      wasRunning.current = s.publish.running;
      return true;
    } catch {
      setReachable(false);
      return false;
    }
  }, [onPublished]);

  // 3s while the backend is up (live publish progress); 20s when down.
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const loop = async () => {
      const ok = await pollOnce();
      if (!alive) return;
      timer = setTimeout(loop, ok ? 3_000 : 20_000);
    };
    loop();
    return () => { alive = false; clearTimeout(timer); };
  }, [pollOnce]);

  if (!reachable || !status) return null;   // hidden when no local backend

  const pub      = status.publish;
  const pusherOn = status.pusher.running;

  const runPublish = async () => {
    setBusy("publish");
    try {
      await fetch(`${API}/control/publish`, { method: "POST" });
      await pollOnce();
    } finally {
      setBusy(null);
    }
  };
  const togglePusher = async () => {
    setBusy("pusher");
    try {
      await fetch(`${API}/control/pusher/${pusherOn ? "stop" : "start"}`, { method: "POST" });
      await pollOnce();
    } finally {
      setBusy(null);
    }
  };
  const runRetro = async () => {
    setBusy("retro");
    setRetroMsg(null);
    try {
      const r = await fetch(`${API}/control/retrospective`, { method: "POST" });
      const j = await r.json().catch(() => ({}));
      setRetroMsg(r.ok && j.report_md ? "✓ 复盘已生成（页面「月度复盘」可查看）" : `✗ ${j.error || `HTTP ${r.status}`}`);
    } catch (e) {
      setRetroMsg(`✗ ${e instanceof Error ? e.message : "请求失败"}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Shell>
      <button
        onClick={runPublish}
        disabled={pub.running || busy === "publish"}
        className="px-3.5 py-2 text-sm font-medium rounded-lg bg-[#006FFF] text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
      >
        {pub.running
          ? <><span className="inline-block w-2.5 h-2.5 rounded-full bg-white animate-pulse" />出决策中…</>
          : <>🧠 出今天的决策</>}
      </button>

      <button
        onClick={togglePusher}
        disabled={busy === "pusher"}
        className={`px-3.5 py-2 text-sm font-medium rounded-lg border flex items-center gap-2 disabled:opacity-50 ${
          pusherOn
            ? "border-emerald-300 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
            : "border-[#EDEDF0] bg-white text-[#525461] hover:bg-gray-50"
        }`}
      >
        <span className={`inline-block w-2 h-2 rounded-full ${pusherOn ? "bg-emerald-500 animate-pulse" : "bg-gray-300"}`} />
        {pusherOn ? "实时报价运行中 · 点击停止" : "▶ 开启实时报价"}
      </button>

      <button
        onClick={runRetro}
        disabled={busy === "retro"}
        className="px-3.5 py-2 text-sm font-medium rounded-lg border border-indigo-200 bg-indigo-50 text-indigo-700 hover:bg-indigo-100 disabled:opacity-50 flex items-center gap-2"
      >
        {busy === "retro"
          ? <><span className="inline-block w-2.5 h-2.5 rounded-full bg-indigo-400 animate-pulse" />生成复盘中…</>
          : <>🔮 生成复盘</>}
      </button>

      {!pub.running && pub.ok !== null && (
        <span className={`text-xs ${pub.ok ? "text-emerald-600" : "text-[#F03A3E]"}`}>
          {pub.ok ? `✓ 决策已更新 ${pub.finished_at ?? ""}` : "✗ 出决策失败（见下方日志）"}
        </span>
      )}

      {retroMsg && (
        <span className={`text-xs ${retroMsg.startsWith("✓") ? "text-emerald-600" : "text-[#F03A3E]"}`}>
          {retroMsg}
        </span>
      )}

      {!pub.running && pub.ok === false && pub.log && (
        <pre className="basis-full mt-3 text-[11px] font-mono text-[#525461] bg-red-50 border border-red-100 rounded-md px-3 py-2 max-h-40 overflow-auto whitespace-pre-wrap">{pub.log}</pre>
      )}

      <p className="basis-full mt-2 text-[11px] text-[#9A9CA5]">
        「出今天的决策」调用 Opus 4.8（约 $0.1/次）跑全套分析并更新本页 · 「实时报价」在盘前盘后每分钟推一次价格
      </p>
    </Shell>
  );
}

/* Shared chrome so both modes look identical. */
function Shell({ children }: { children: React.ReactNode }) {
  return (
    <section className="bg-white rounded-2xl border border-[#EDEDF0] shadow-sm px-5 py-4">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider mr-1">控制台</span>
        {children}
      </div>
    </section>
  );
}
