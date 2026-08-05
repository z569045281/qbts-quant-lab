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

    # Previous live data (SMC rising-edge dedup + btc_weekend push dedup + carry-forward).
    prev_data = {}
    try:
        r = sb.table("live_quote").select("data").eq("id", 1).single().execute()
        prev_data = ((r.data or {}).get("data") or {})
    except Exception:
        prev_data = {}
    prev_smc = prev_data.get("smc")

    now_et = datetime.now(ZoneInfo("America/New_York"))

    # 周一开盘·周末BTC 信号(mining.md 核心事实 #9):仅周一有值,算一次随
    # live_quote carry,08:00 ET 起 ntfy 一次(pushed 标记读回去重)。
    try:
        from dashboard.btc_weekend import maybe_btc_weekend
        bw = maybe_btc_weekend(prev_data.get("btc_weekend"), now_et)
        if bw:
            payload["btc_weekend"] = bw
    except Exception as e:
        print(f"! btc_weekend skipped: {type(e).__name__}: {e}")

    # 特调双腿(收盘后 16:05 起每日一算,触发→ntfy;date 标记去重)。
    try:
        from dashboard.tiaojiu import maybe_tiaojiu_push
        tj = maybe_tiaojiu_push(prev_data.get("tiaojiu"), now_et)
        if tj:
            payload["tiaojiu"] = tj
    except Exception as e:
        print(f"! tiaojiu skipped: {type(e).__name__}: {e}")

    # 🌍 地缘政治雷达(伊朗/川普/量子政策):minute%30==8 刷新(RSS 免费,Haiku
    # 只在头条变了才跑),新高影响条目/风险级别翻转 → ntfy;off-tick carry-forward。
    try:
        from dashboard.geopolitics import maybe_geo_refresh
        geo = maybe_geo_refresh(prev_data.get("geo"), now_et)
        if geo:
            payload["geo"] = geo
    except Exception as e:
        print(f"! geo radar skipped: {type(e).__name__}: {e}")
        if prev_data.get("geo"):
            payload["geo"] = prev_data["geo"]

    # 📣 公司催化剂雷达(D-Wave 自身消息 + 板块同行):minute%10==3 刷新。
    # 07-27 那波 +20.4% 是 AT&T 签约驱动的,机械信号全盲、news.py 一天只跑一次,
    # 等决策看见时跳空已经走完 —— 这条就是补那段。RSS 免费,Haiku 只在头条真的
    # 变了才跑;推送有故事级去重 + 45min 冷却,一条 PR 的多家转载只响一次。
    try:
        from dashboard.catalyst_radar import maybe_catalyst_refresh
        cat = maybe_catalyst_refresh(prev_data.get("catalyst"), now_et)
        if cat:
            payload["catalyst"] = cat
    except Exception as e:
        print(f"! catalyst radar skipped: {type(e).__name__}: {e}")
        if prev_data.get("catalyst"):
            payload["catalyst"] = prev_data["catalyst"]

    # ⚠️ 事件日熔断(第二十八轮):极端跳空(≥±8%)或 breaking 催化剂 → 盘前就推一条,
    # 告诉用户"今天技术面没有发言权"。**纯本地计算**(吃上面已经算好的 change_pct,
    # 不拉任何行情),所以不挑分钟、每分钟都判,靠 push_key 每日去重。
    # 起因:07-27 开盘跳空 +10.2%,而用户手上那份决策的技术面结论是"别追"。
    # ⚠️ `live_quote.data` 是**整块覆写**的(push_payload 直接 upsert 整个 payload)。
    # 所以凡是把"今天推没推过"存在这个 blob 里的模块,只要有**一分钟**没往 payload
    # 里写回自己的状态,去重键就永久消失,下一跳会当成第一次再推一遍。
    # 各模块的约定:非工作跳一律 `return prev`(carry-forward),不许返回 None。
    # 2026-07-31 事故:event_day 违反了这条(判不出事件日就返回 None)→ 用户一早
    # 收到两条一模一样的「⚠️ 事件日」。已在 event_day.py 里把**键与状态分离**。
    try:
        from dashboard.event_day import maybe_event_day_push
        ev = maybe_event_day_push(prev_data.get("event_day"), now_et,
                                  payload.get("quotes"), payload.get("catalyst"))
        if ev:
            payload["event_day"] = ev
    except Exception as e:
        print(f"! event_day skipped: {type(e).__name__}: {e}")
        if prev_data.get("event_day"):
            payload["event_day"] = prev_data["event_day"]

    # 🚨 财报落地即时推送(2026-08-05,用户点单)。QBTS 财报盘前 08:00 ET 发,
    # 而决策卡 09:00 才跑 —— 中间那一小时价格跳最凶却没人通知。三个探针:
    # EDGAR 8-K item 2.02(权威)/ 盘前跳 ≥5% / 新闻关键词。每个财报日只响一次。
    try:
        from dashboard.earnings_alert import maybe_earnings_alert
        ea = maybe_earnings_alert(prev_data.get("earnings_alert"), now_et,
                                  payload.get("quotes"), payload.get("catalyst"))
        if ea:
            payload["earnings_alert"] = ea
    except Exception as e:
        print(f"! earnings_alert skipped: {type(e).__name__}: {e}")
        if prev_data.get("earnings_alert"):
            payload["earnings_alert"] = prev_data["earnings_alert"]

    # 🔔 决策卡触发线(2026-08-04):收盘后判一次,越线就响。补的是 08-03 那个洞 ——
    # 决策卡当天写了「收盘站上 $18.88 就买 QBTX」,当晚真触发了却没人通知用户
    # (收盘 = 墨尔本早上 6 点)。非收盘窗口一律 carry-forward,别把已推记录冲掉。
    try:
        from dashboard.decision_trigger import maybe_trigger_push
        dt = maybe_trigger_push(prev_data.get("dec_trigger"), now_et, payload.get("quotes"))
        if dt:
            payload["dec_trigger"] = dt
    except Exception as e:
        print(f"! decision_trigger skipped: {type(e).__name__}: {e}")
        if prev_data.get("dec_trigger"):
            payload["dec_trigger"] = prev_data["dec_trigger"]

    # 千元挑战第二期($5000 云端全自动,Alpaca paper)。模块自己挑
    # minute%15==2 的盘中分钟干活(错开 %5 的 SMC 分钟防超时),其余分钟秒退;
    # 状态直接写 crypto_challenge 表,不走 live_quote。
    challenge_summary = None
    try:
        from dashboard.challenge2 import maybe_challenge_tick
        challenge_summary = maybe_challenge_tick(now_et)
    except Exception as e:
        print(f"! challenge2 skipped: {type(e).__name__}: {e}")

    # 🎯 游击战(服务端自算,无 webhook):收盘后 16:05–20:00 ET 每日算一次信号,
    # 命中 → ntfy + 开纸面仓;分钟 tick(minute%5==4)盯 stop/target 出场。两者都
    # 只在窗口/有仓位时才拉数据,平时秒退。
    try:
        from dashboard.guerrilla import check_exits, maybe_guerrilla_signal
        gsig = maybe_guerrilla_signal(now_et)
        if gsig:
            print(f"guerrilla signal: {gsig}")
        ger = check_exits(now_et)
        if ger:
            print(f"guerrilla exits: {ger}")
    except Exception as e:
        print(f"! guerrilla skipped: {type(e).__name__}: {e}")
    # 🌙 夜盘采样(2026-08-05):20:00–04:00 ET 没有任何 15m bar 源(yfinance /
    # Alpaca iex 都停在 15:45;Alpaca 的 overnight feed 只有 latest,没有历史)——
    # 所以把我们每分钟本来就在拉的 NBBO 中间价存下来,自己聚合成 15m。
    # 只在夜盘存:日盘有带成交量的真 bar,合成 bar 不配跟它抢。
    if payload.get("session") == "overnight":
        try:
            from dashboard.overnight_bars import record_tick, prune
            q = (payload.get("quotes") or {}).get("qbts") or {}
            record_tick("QBTS", q.get("price"), q.get("ov_bid"), q.get("ov_ask"))
            if now_et.hour == 3 and now_et.minute == 7:      # 每晚清一次,错开忙碌分钟
                prune()
        except Exception as e:
            print(f"! overnight tick skipped: {type(e).__name__}: {e}")

    # 夜盘也重算 SMC —— 有了合成 bar 之后,15m 扳机在夜盘不再是死的。
    # (读数会带 synthetic_15m>0,推送层据此不开枪,见 intraday_smc。)
    recompute = (payload.get("session") in ("pre", "regular", "post", "overnight")
                 and now_et.minute % 5 == 0)
    if recompute:
        try:
            from dashboard.intraday_smc import compute_smc, maybe_notify_trigger
            qpx = ((payload.get("quotes") or {}).get("qbts") or {}).get("price")
            fresh = compute_smc(qpx)
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

    # 🔔 推送通道健康(2026-07-31)。放在**所有推送调用之后** —— 起因是事件日推送
    # 从 07-29 起因标题编码每分钟静默失败,日志里刷了两天没人看见,07-30 夜盘
    # +10.2% 又漏推一次。日志不是监控:把最后一次成败带进 payload 让前端能报警。
    try:
        from dashboard.notify import health as ntfy_health
        payload["ntfy_health"] = ntfy_health()
    except Exception as e:
        print(f"! ntfy_health skipped: {type(e).__name__}: {e}")

    quote_pusher.push_payload(sb, payload)
    q = (payload.get("quotes") or {}).get("qbts") or {}
    return {"ok": True, "session": payload.get("session"), "qbts_price": q.get("price"),
            "smc_state": ((payload.get("smc") or {}).get("playbook") or {}).get("state"),
            "challenge": challenge_summary}


# ── 分段计时(2026-08-05)───────────────────────────────────────────────
# 起因:08-04 11:39 那次 `Status: timeout`(300s),而 CloudWatch **只捕获
# WARNING 以上** —— `logger.info` 在云端根本不存在,于是 START 到 END 之间
# 246 秒是一整块黑箱,只能靠 Supabase 里各表的 generated_at 反推。
# 用 print(stdout 一定进 CloudWatch)打每段耗时,下次超时能直接读出是谁吃的。
def _phase(t0, name: str) -> float:
    import time
    t = time.time()
    print(f"⏱  {name}: {t - t0:.1f}s")
    return t


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
        # 财报日历同款持久化(2026-07-21:Lambda /tmp 冷启动清空导致云端"数据源失败")
        try:
            from data.altdata import sync_earnings_dates
            sync_earnings_dates(sb)
        except Exception as e:
            print(f"! earnings sync skipped: {e}")

        import time as _t; _t0 = _t.time()
        snap = loop.run_until_complete(dashboard_snapshot(force_refresh=True))
        _t0 = _phase(_t0, "snapshot")

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


        # 🏆 策略冠军推送(2026-08-05):上升沿才响,状态从上一份 dashboard_state 读回。
        # 放在 snapshot 之后、写库之前 —— 此时"最后一行"还是上一次,正好当去重基准。
        try:
            from dashboard.champions import push_if_new
            if push_if_new(snap.get("champions") or {}):
                print("  ✓ champions ntfy pushed")
        except Exception as e:
            print(f"! champions push skipped: {e}")

        _t0 = _phase(_t0, "decision(含第二考场)")

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

        ins = sb.table("dashboard_state").insert(
            {"snapshot": clean(snap), "calibration": clean(cal)}
        ).execute()
        state_row_id = (ins.data or [{}])[0].get("id")

        # Watchlist scan (diversified buy-setup scan → 🔭 自选扫描 tab). Best-effort:
        # a scan failure must never block the daily decision publish.
        _t0 = _phase(_t0, "写 dashboard_state")
        scan_payload = dca_payload = sx_payload = None
        try:
            from dashboard import scan_store
            scan_payload = scan_store.publish_scan()
        except Exception as e:
            print(f"! watchlist scan skipped: {e}")
        _t0 = _phase(_t0, "自选扫描")
        try:
            from dashboard import dca
            dca_payload = dca.publish_dca()
        except Exception as e:
            print(f"! DCA skipped: {e}")
        # 🚀 SpaceX (SPCX · DeepSeek-only) — best-effort, never blocks the QBTS publish
        _t0 = _phase(_t0, "DCA")
        try:
            from dashboard import spacex
            sx_payload = spacex.publish_spacex()
        except Exception as e:
            print(f"! SpaceX skipped: {e}")
        # 🔬 全站 AI 系统自检(规则层+Haiku,~$0.01)→ 回写 snapshot['site_check'],
        # 各页渲染自己的切片。best-effort,绝不挡 publish。
        _t0 = _phase(_t0, "SpaceX")
        try:
            from dashboard.selfcheck import build_site_check
            chall = None
            try:
                rows = (sb.table("crypto_challenge").select("data")
                          .eq("id", "current").execute().data)
                chall = rows[0]["data"] if rows else None
            except Exception:
                pass
            check = build_site_check(snap, scan=scan_payload, dca=dca_payload,
                                     challenge=chall, spacex=sx_payload)
            snap["site_check"] = check
            if state_row_id is not None:
                sb.table("dashboard_state").update(
                    {"snapshot": clean(snap)}).eq("id", state_row_id).execute()
                print(f"✓ site check: {check['n_issues']} issue(s)")
            else:
                print("! site check computed but NOT persisted (insert returned no id)")
        except Exception as e:
            print(f"! site check skipped: {e}")
    finally:
        loop.close()
    return {"ok": True, "decision": summary}


def _audit_click(event, body: dict) -> None:
    """👀 谁点了按钮 — 把每次 Function URL 调用(出决策/自选编辑等)的来源记进
    Supabase `publish_audit`:IP、User-Agent、前端附带的设备提示(时区/语言/
    平台/屏幕)。定时调度(EventBridge)没有 sourceIp → 不记,只记真人点击。
    纯 best-effort:审计失败绝不能挡住动作本身;表未建时静默跳过
    (需先跑 sql/publish_audit_migration.sql)。"""
    try:
        ip = (((event or {}).get("requestContext") or {}).get("http") or {}).get("sourceIp")
        if not ip:
            return                                  # cron/内部调用,不记
        headers = {k.lower(): v for k, v in ((event or {}).get("headers") or {}).items()}
        from supabase import create_client
        url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
        key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
        if not url or not key:
            return
        create_client(url, key).table("publish_audit").insert({
            "action": body.get("action") or "publish",
            "ip":     ip,
            "ua":     (headers.get("user-agent") or "")[:300],
            "client": body.get("client") or None,
        }).execute()
    except Exception as e:
        print(f"! audit skipped: {type(e).__name__}: {e}")


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
      pos_add       → 💼 upsert a real position {ticker, qty, cost, date?}
      pos_remove    → 💼 remove a real position {ticker}
    Returns API-Gateway-v2 response shape."""
    body = _parse_body(event)
    action = body.get("action")
    _audit_click(event, body)      # 👀 记录点击者(IP/UA/设备提示;cron 不记)
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

        if action == "spacex":
            # 🚀 单独重跑 SpaceX 生成(DeepSeek-only)→ 写 spacex_state。~30-60s。
            from dashboard import spacex
            sx = spacex.publish_spacex()
            dec = sx.get("decision")
            return {"statusCode": 200, "body": json.dumps(
                {"ok": True, "decision": (
                    {"action": dec["action"], "conviction": dec["conviction"]} if dec else None)})}

        if action in ("pos_add", "pos_remove"):
            # 💼 实盘持仓编辑(AI 建议在下次生成决策时更新)
            from dashboard import positions as upos
            try:
                ticker = (body.get("ticker") or "").strip().upper()
                plist = (upos.upsert_position(ticker, body.get("qty"),
                                              body.get("cost"), body.get("date"))
                         if action == "pos_add" else upos.remove_position(ticker))
                return {"statusCode": 200, "body": json.dumps(
                    {"ok": True, "positions": plist})}
            except (ValueError, TypeError) as e:
                return {"statusCode": 400, "body": json.dumps(
                    {"ok": False, "error": str(e)})}

        result = _publish_decision_only()
        return {"statusCode": 200, "body": json.dumps(result)}
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"publish failed: {msg}")
        return {"statusCode": 500, "body": json.dumps({"ok": False, "error": msg})}
