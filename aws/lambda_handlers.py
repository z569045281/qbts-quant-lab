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
import sys

# Lambda's only writable path is /tmp. The image symlinks backend/data/cache →
# /tmp/cache, but that target doesn't exist at cold start, and Path.mkdir(
# exist_ok=True) on a *dangling symlink* still raises FileExistsError (it follows
# the link, finds nothing, and re-raises). Create the target once, up front,
# before any backend module imports and runs its own mkdir.
os.makedirs("/tmp/cache", exist_ok=True)

# Put backend/ on sys.path so `from dashboard...` / `from data...` resolve in BOTH
# handlers. publish_handler gets this for free (importing backend.api runs api.py,
# which does its own sys.path.insert), but quote_handler imports dashboard.* without
# ever touching api.py — hence "No module named 'dashboard'" until we add it here.
sys.path.insert(0, os.path.join(os.environ.get("LAMBDA_TASK_ROOT", os.path.dirname(__file__)), "backend"))


def quote_handler(event, context):
    """One live-quote push to Supabase. Stateless — perfect for a 1-min schedule.

    Also refreshes the cheap SMC playbook ~every 5 min during market hours and
    fires an ntfy push when the state rises into TRIGGER — so the fleeting 15m
    trigger can actually be caught, not just at the 09:00 daily publish.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import quote_pusher

    sb = quote_pusher.get_supabase()
    payload = quote_pusher.build_payload()

    # Previous SMC block (for rising-edge dedup + carry-forward between recomputes).
    prev_smc = None
    try:
        r = sb.table("live_quote").select("data").eq("id", 1).single().execute()
        prev_smc = ((r.data or {}).get("data") or {}).get("smc")
    except Exception:
        prev_smc = None

    now_et = datetime.now(ZoneInfo("America/New_York"))
    recompute = payload.get("session") in ("pre", "regular", "post") and now_et.minute % 5 == 0
    if recompute:
        try:
            from dashboard.intraday_smc import compute_playbook, maybe_notify_trigger
            qpx = ((payload.get("quotes") or {}).get("qbts") or {}).get("price")
            fresh = compute_playbook(qpx)
            if fresh:
                payload["smc"] = fresh
                prev_state = ((prev_smc or {}).get("playbook") or {}).get("state")
                maybe_notify_trigger(prev_state, fresh)
            elif prev_smc:
                payload["smc"] = prev_smc          # keep last good if recompute failed
        except Exception as e:
            import traceback
            payload["smc_err"] = f"{type(e).__name__}: {e}"   # surfaced for observability
            print("! intraday SMC skipped:\n" + traceback.format_exc())
            if prev_smc:
                payload["smc"] = prev_smc
    elif prev_smc:
        payload["smc"] = prev_smc                  # carry forward on off-minutes

    quote_pusher.push_payload(sb, payload)
    q = (payload.get("quotes") or {}).get("qbts") or {}
    return {"ok": True, "session": payload.get("session"), "qbts_price": q.get("price"),
            "smc_state": ((payload.get("smc") or {}).get("playbook") or {}).get("state")}


def _publish_decision_only() -> dict:
    """Slim publish: snapshot + decision + calibration → one dashboard_state row.

    Mirrors publish.py steps 1–4 but SKIPS the factor table (steps 5–6), which
    would otherwise be wiped by the empty in-memory leaderboard on Lambda.
    """
    import asyncio
    from supabase import create_client
    from backend.api import (
        dashboard_snapshot, dashboard_calibration, refresh_decision, _Encoder,
        journal_recent,
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
        # Refresh FINRA short cache (Supabase-backed, survives cold starts) BEFORE
        # the snapshot, so the squeeze's short component has data on cloud runs.
        try:
            from data.altdata import sync_short_volume
            sync_short_volume(sb)
        except Exception as e:
            print(f"! FINRA short sync skipped: {e}")

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

        # refresh_decision() recorded today's call AFTER dashboard_snapshot
        # captured the journal — re-read so today's decision shows immediately.
        try:
            snap["journal"] = journal_recent(12)
        except Exception:
            pass

        try:
            cal = loop.run_until_complete(dashboard_calibration())
        except Exception as e:
            print(f"! calibration skipped: {e}")
            cal = None

        sb.table("dashboard_state").insert(
            {"snapshot": clean(snap), "calibration": clean(cal)}
        ).execute()

        # Watchlist scan (diversified buy-setup scan → 🔭 自选扫描 tab). Best-effort:
        # a scan failure must never block the daily decision publish.
        try:
            from dashboard import scan_store
            scan_store.publish_scan()
        except Exception as e:
            print(f"! watchlist scan skipped: {e}")
        try:
            from dashboard import dca
            dca.publish_dca()
        except Exception as e:
            print(f"! DCA skipped: {e}")
    finally:
        loop.close()
    return {"ok": True, "decision": summary}


def _parse_body(event) -> dict:
    """Parse the Function URL POST body (may be base64-encoded) into a dict."""
    import base64
    body = event.get("body") if isinstance(event, dict) else None
    if not body:
        return {}
    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body).decode()
        except Exception:
            return {}
    try:
        return json.loads(body)
    except Exception:
        return {}


def publish_handler(event, context):
    """Function URL / scheduled entrypoint. Routes by POST body `action`:
      (none)        → full daily decision publish (button / schedule)
      watch_add     → add a ticker to the watchlist, then re-scan
      watch_remove  → remove a ticker, then re-scan
      rescan        → just re-run the watchlist scan
    Returns API-Gateway-v2 response shape."""
    body = _parse_body(event)
    action = body.get("action")
    try:
        if action in ("watch_add", "watch_remove"):
            from dashboard.scan import WATCHLIST
            from dashboard import scan_store
            ticker = (body.get("ticker") or "").strip().upper()
            if not ticker:
                return {"statusCode": 400, "body": json.dumps({"ok": False, "error": "missing ticker"})}
            wl = (scan_store.add_ticker(ticker, WATCHLIST) if action == "watch_add"
                  else scan_store.remove_ticker(ticker, WATCHLIST))
            scan = scan_store.publish_scan()       # re-scan with the new list
            return {"statusCode": 200, "body": json.dumps(
                {"ok": True, "watchlist": wl, "n": len(scan.get("results", []))})}

        if action == "rescan":
            from dashboard import scan_store
            scan = scan_store.publish_scan()
            return {"statusCode": 200, "body": json.dumps(
                {"ok": True, "n": len(scan.get("results", []))})}

        result = _publish_decision_only()
        return {"statusCode": 200, "body": json.dumps(result)}
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"publish failed: {msg}")
        return {"statusCode": 500, "body": json.dumps({"ok": False, "error": msg})}
