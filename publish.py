#!/usr/bin/env python3
"""
Publish locally-mined QBTS results to Supabase for the read-only deployed dashboard.

Run this after you've mined / refreshed locally:

    .venv/bin/python publish.py

It recomputes the dashboard snapshot, a fresh AI brief, the calibration table,
and every factor's chart — then writes them to Supabase. The deployed Next.js
site reads straight from Supabase (no backend). See supabase_schema.sql.

Requires in .env:
    SUPABASE_URL          (https://<project>.supabase.co)
    SUPABASE_SERVICE_KEY  (service_role key — bypasses RLS; keep secret, local only)
"""
import asyncio
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _require_env() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    # New consoles call it "secret key" (sb_secret_…), legacy "service_role".
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SECRET_KEY")
    if not url or not key:
        sys.exit(
            "✗ .env 缺少 Supabase 写入凭证\n"
            "  需要: SUPABASE_SECRET_KEY=sb_secret_…\n"
            "  获取: Supabase 控制台 → Project Settings → API Keys → 'secret' key\n"
            "  （注意: publishable key 只能读，发布需要 secret key）"
        )
    if key.startswith("sb_publishable"):
        sys.exit(
            "✗ SUPABASE_SECRET_KEY 填成了 publishable key（只读）\n"
            "  发布需要 sb_secret_… 开头的 secret key —\n"
            "  Supabase 控制台 → Project Settings → API Keys → 'secret'"
        )
    return url, key


def main() -> None:
    url, key = _require_env()

    # Heavy imports happen only after env is validated, so a misconfig fails fast.
    from supabase import create_client

    # api.py inserts backend/ onto sys.path and re-exports these in its namespace.
    from backend.api import (  # noqa: E402
        dashboard_snapshot,
        dashboard_calibration,
        refresh_decision,
        get_leaderboard,
        get_factor_chart,
        leaderboard,
        journal_recent,
        _Encoder,
    )

    def clean(obj):
        """Make a payload JSON/Postgres-jsonb safe.

        Round-trips through the backend's numpy/pandas encoder, then turns
        NaN/Infinity (valid Python, invalid JSON for PostgREST) into null.
        """
        return json.loads(
            json.dumps(obj, cls=_Encoder),
            parse_constant=lambda _c: None,
        )

    sb = create_client(url, key)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # 1. Dashboard snapshot (force a fresh compute) ----------------------
        print("→ computing dashboard snapshot…")
        snap = loop.run_until_complete(dashboard_snapshot(force_refresh=True))

        # 2. Fresh AI trade decision — the user-facing verdict (≈$0.05) -------
        try:
            print("→ generating AI decision (≈$0.05)…")
            res = loop.run_until_complete(refresh_decision())
            snap["decision"] = res["decision"]
            snap["decision_generated_at"] = res["generated_at"]
            if res["decision"]:
                d = res["decision"]
                print(f"  ✓ {d['action']} · 信心 {d['conviction']}/10 · {d['summary'][:60]}…")
        except Exception as e:  # decision is critical but not fatal to publish
            print(f"  ! decision skipped: {e}")

        # refresh_decision() records today's call after the snapshot captured the
        # journal — re-read so today's decision shows in the published track record.
        try:
            snap["journal"] = journal_recent(12)
        except Exception:
            pass

        # 3. Calibration -----------------------------------------------------
        try:
            print("→ computing calibration…")
            cal = loop.run_until_complete(dashboard_calibration())
        except Exception as e:
            print(f"  ! calibration skipped: {e}")
            cal = None

        # 4. Write the dashboard_state row -----------------------------------
        print("→ writing dashboard_state…")
        sb.table("dashboard_state").insert(
            {"snapshot": clean(snap), "calibration": clean(cal)}
        ).execute()

        # 5. Factors: metrics + code + chart ---------------------------------
        lb = get_leaderboard()                       # code/signal stripped, favorited added
        code_by_id = {e["id"]: e.get("code") for e in leaderboard}
        print(f"→ publishing {len(lb)} factors (ML charts re-run WFO, may be slow)…")
        rows = []
        for f in lb:
            fid = f["id"]
            chart = None
            try:
                chart = loop.run_until_complete(get_factor_chart(fid))
            except Exception as e:
                print(f"  ! chart failed for {f.get('name')!r}: {e}")
            rows.append({
                "id": fid,
                "score": f.get("score"),
                "data": clean(f),
                "code": code_by_id.get(fid),
                "chart": clean(chart),
            })

        # 6. Replace the factors table wholesale -----------------------------
        print("→ writing factors…")
        sb.table("factors").delete().neq("id", "").execute()   # clear stale rows
        if rows:
            sb.table("factors").upsert(rows).execute()

        print(f"✓ published: 1 dashboard_state row, {len(rows)} factors")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
