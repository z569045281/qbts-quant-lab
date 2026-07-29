"""
Intraday SMC playbook refresh + TRIGGER push notification.

The daily publish (09:00 ET) computes the full snapshot once — but the SMC
playbook's TRIGGER state (15m CHoCH + VMC dot) is fleeting and intraday, so a
once-a-day compute can never catch it. This module recomputes JUST the cheap,
deterministic SMC playbook (no LLM call) every few minutes inside the per-minute
QuoteFunction, writes it into the `live_quote` row, and fires an ntfy.sh push
the moment the state rises into TRIGGER.

Cost: pure pandas/numpy + one 15m yfinance fetch → ~$0 on top of the existing
per-minute quote job. Daily/1h bars come from cache (the lock + relay zones move
slowly intraday); only the 15m trigger TF is force-refreshed.
"""

from __future__ import annotations

import os
import urllib.request
from datetime import datetime, timezone


def compute_smc(live_price: float | None = None) -> dict | None:
    """Cheap full SMC recompute (cached daily+1h, fresh 15m).

    Returns the FULL `analyze_smc` read (structure/zones/sweeps + playbook) with
    an `asof` stamp, so the dashboard renders the WHOLE SMC card from one live
    source — otherwise the live playbook (e.g. 50%) and the daily snapshot's
    badges (e.g. 33%) disagree once price moves intraday. None if no playbook;
    raises on a real failure so the caller can surface the reason."""
    from data.fetcher import load_or_fetch, load_15m
    from dashboard.smc import analyze_smc
    df_h, df_d = load_or_fetch()              # cached: lock/zones change slowly
    df_15m = load_15m(force_refresh=True)     # fresh: the trigger timeframe
    smc = analyze_smc(df_d, live_price, df_h, df_15m)
    if not smc.get("playbook"):
        return None
    smc["asof"] = datetime.now(timezone.utc).isoformat()
    return smc


def _ntfy(title: str, body: str, tags: str = "rotating_light", priority: str = "high") -> bool:
    """POST to ntfy.sh (no auth needed). Title stays ASCII (HTTP header is
    latin-1); the Chinese detail goes in the UTF-8 body. No-op if unconfigured."""
    topic = os.getenv("NTFY_TOPIC")
    if not topic:
        return False
    base = os.getenv("NTFY_URL", "https://ntfy.sh").rstrip("/")
    req = urllib.request.Request(
        f"{base}/{topic}", data=body.encode("utf-8"), method="POST",
        headers={"Title": title, "Tags": tags, "Priority": priority,
                 "Content-Type": "text/plain; charset=utf-8"})
    try:
        urllib.request.urlopen(req, timeout=8)
        return True
    except Exception as e:
        print(f"! ntfy push failed: {type(e).__name__}: {e}")
        return False


def maybe_notify_trigger(prev_state: str | None, smc_payload: dict) -> bool:
    """Fire a push only on the RISING EDGE into TRIGGER — dedup across the
    re-computes while it persists. Returns True if a push was sent."""
    pb = (smc_payload or {}).get("playbook") or {}
    state = pb.get("state")
    if state != "TRIGGER" or prev_state == "TRIGGER":
        return False

    # ⛔ 空头腿不响铃(2026-07-29)。铁律:判死的策略不复活 —— 做空 QBTS 的**全部
    # 已知路径**都已判死(第十三轮空头家族终审、第二十三轮 bear lock、本轮又新判死
    # 暴涨次日日内空/暴涨日收盘买),档案原文写明 QBTZ 唯一残留用途 = 未来若出现
    # 新的、独立验证的看空信号,而那个信号目前不存在。
    #
    # 为什么现在才需要这道闸:日线摆动 k 由 2 改 8 后,空头 playbook 的 RR 从 1.79
    # 变成 5.84 —— 以前是被 RR<2 熔断顺手挡住的,现在它能过闸了。**靠另一道闸的
    # 副作用来维持铁律,等于没有维持。** bear lock 仍然照常进卡片和决策 prompt
    # 当方向过滤器/风控背景,只是不推"去做空"这个动作。
    if (pb.get("lock") == "bear") or (pb.get("side_cn") == "做空"):
        print("! SMC 空头扳机不推送(做空路径已判死,bear lock 只作过滤器)")
        return False
    ez = pb.get("entry_zone") or {}
    tp1 = (pb.get("tp1") or {}).get("price")
    lines = [
        f"QBTS SMC 扣扳机 · {pb.get('side_cn', '?')}",
        f"入场 ${ez.get('low', '?')}–${ez.get('high', '?')}",
        f"止损 ${pb.get('stop')}　TP1 ${tp1}　RR {pb.get('rr')}",
        pb.get("lock_reason", ""),
        "（15m CHoCH + VMC 点已收盘确认 · 验证期，软参考）",
    ]
    return _ntfy("QBTS SMC TRIGGER", "\n".join(str(x) for x in lines if x))


if __name__ == "__main__":
    import sys, json
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    out = compute_smc()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str) if out else "compute failed")
