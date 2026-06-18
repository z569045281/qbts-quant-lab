"""AWS Lambda entrypoints for the QBTS dashboard (Route A, serverless).

One container image, two handlers (template.yaml picks each via
ImageConfig.Command):

  publish_handler — recompute the dashboard snapshot + Opus 4.8 decision +
                    calibration and write ONE dashboard_state row to Supabase.
                    Triggered by the dashboard "出今天的决策" button (Function URL)
                    and a daily EventBridge schedule.

                    It deliberately does NOT touch the `factors` table. Factor
                    mining is a local activity; the in-memory leaderboard is
                    empty on a fresh Lambda, so running the full publish.py here
                    would DELETE every published factor. Factors stay as last
                    published locally — re-run `publish.py` locally after mining.

  quote_handler   — one live-quote push to Supabase (== quote_pusher --once).
                    Triggered by EventBridge every minute during US market hours.

Lambda's filesystem is read-only except /tmp; the Dockerfile symlinks the cache
dir there so the JSON/parquet/jsonl caches can be written. /tmp is ephemeral,
so the decision journal does NOT accumulate across cold starts in this setup —
see aws/README.md for the Supabase-backed-journal upgrade.
"""
import json
import os

# Lambda's only writable path is /tmp. The image symlinks backend/data/cache →
# /tmp/cache, but that target doesn't exist at cold start, and Path.mkdir(
# exist_ok=True) on a *dangling symlink* still raises FileExistsError (it follows
# the link, finds nothing, and re-raises). Create the target once, up front,
# before any backend module imports and runs its own mkdir.
os.makedirs("/tmp/cache", exist_ok=True)


def quote_handler(event, context):
    """One live-quote push to Supabase. Stateless — perfect for a 1-min schedule."""
    import quote_pusher
    sb = quote_pusher.get_supabase()
    payload = quote_pusher.push_once(sb)
    q = (payload.get("quotes") or {}).get("qbts") or {}
    return {"ok": True, "session": payload.get("session"), "qbts_price": q.get("price")}


def _publish_decision_only() -> dict:
    """Slim publish: snapshot + decision + calibration → one dashboard_state row.

    Mirrors publish.py steps 1–4 but SKIPS the factor table (steps 5–6), which
    would otherwise be wiped by the empty in-memory leaderboard on Lambda.
    """
    import asyncio
    from supabase import create_client
    from backend.api import (
        dashboard_snapshot, dashboard_calibration, refresh_decision, _Encoder,
    )

    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("missing SUPABASE_URL / SUPABASE_SECRET_KEY env vars")

    def clean(obj):
        # numpy/pandas-safe, then NaN/Infinity → null (valid JSON for PostgREST)
        return json.loads(json.dumps(obj, cls=_Encoder), parse_constant=lambda _c: None)

    sb = create_client(url, key)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        snap = loop.run_until_complete(dashboard_snapshot(force_refresh=True))

        summary = None
        try:
            res = loop.run_until_complete(refresh_decision())
            snap["decision"] = res["decision"]
            snap["decision_generated_at"] = res["generated_at"]
            if res.get("decision"):
                d = res["decision"]
                summary = f"{d['action']} · 信心 {d['conviction']}/10"
        except Exception as e:               # decision is important but not fatal
            print(f"! decision skipped: {e}")

        try:
            cal = loop.run_until_complete(dashboard_calibration())
        except Exception as e:
            print(f"! calibration skipped: {e}")
            cal = None

        sb.table("dashboard_state").insert(
            {"snapshot": clean(snap), "calibration": clean(cal)}
        ).execute()
    finally:
        loop.close()
    return {"ok": True, "decision": summary}


def publish_handler(event, context):
    """Function URL / scheduled entrypoint. Returns API-Gateway-v2 response shape."""
    try:
        result = _publish_decision_only()
        return {"statusCode": 200, "body": json.dumps(result)}
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"publish failed: {msg}")
        return {"statusCode": 500, "body": json.dumps({"ok": False, "error": msg})}
