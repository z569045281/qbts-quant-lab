"""
Decision Journal — every model decision is recorded, graded, and reflected on.

Lifecycle:
  record()        on each fresh decision: append to JSONL with price-at-decision
  grade_pending() on each publish: walk daily bars after the decision date —
                    LONG : target touched first → win | stop touched first → loss
                           else after 5 bars: 5d return > 0 → win
                    SHORT: mirror
                    HOLD : graded informational only (excluded from accuracy)
  reflect         wrong calls get a one-sentence lesson from Haiku (cheap),
                    and the last lessons are fed back into the NEXT decision
                    prompt — the system literally learns from its mistakes.

Storage: backend/data/cache/decision_journal.jsonl (append-only; grading
rewrites the file with updated records).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_JOURNAL = Path(__file__).parent.parent / "data" / "cache" / "decision_journal.jsonl"
_JOURNAL.parent.mkdir(parents=True, exist_ok=True)

_GRADE_AFTER_BARS = 5     # final grade horizon (trading days)

# Storage: a Supabase `decision_journal` table when credentials are present
# (so the journal persists across stateless cloud runs — Lambda's /tmp is wiped
# on every cold start), otherwise the local JSONL file. Each record is one row:
# {id, data: <full record dict>}. record()/grade_pending()/load_recent() are
# unchanged — they operate on the list returned by _load() and persist via _save().
_TABLE = "decision_journal"
_SB = None
_SB_INIT = False


def _supabase():
    """Cached Supabase client, or None to fall back to the local file."""
    global _SB, _SB_INIT
    if _SB_INIT:
        return _SB
    _SB_INIT = True
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if url and key:
        try:
            from supabase import create_client
            _SB = create_client(url, key)
        except Exception as e:
            logger.warning(f"journal: Supabase init failed, using file — {e}")
            _SB = None
    return _SB


def _load() -> list[dict]:
    sb = _supabase()
    if sb is not None:
        try:
            rows = sb.table(_TABLE).select("data").execute().data
            return [r["data"] for r in rows if r.get("data")]
        except Exception as e:
            logger.warning(f"journal: Supabase load failed, using file — {e}")
    if not _JOURNAL.exists():
        return []
    out = []
    with _JOURNAL.open() as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _save(records: list[dict]) -> None:
    sb = _supabase()
    if sb is not None:
        try:
            if records:
                sb.table(_TABLE).upsert(
                    [{"id": r["id"], "data": r} for r in records]
                ).execute()
            # Drop rows no longer in the desired set (e.g. a same-day pending
            # record that record() replaced). Usually 0–1 rows.
            keep = {r["id"] for r in records}
            for row in sb.table(_TABLE).select("id").execute().data:
                if row["id"] not in keep:
                    sb.table(_TABLE).delete().eq("id", row["id"]).execute()
            return
        except Exception as e:
            logger.warning(f"journal: Supabase save failed, using file — {e}")
    tmp = _JOURNAL.with_suffix(".tmp")
    with tmp.open("w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(_JOURNAL)


def record(decision: dict, price_at_decision: float, as_of: str) -> None:
    """Append a fresh decision (idempotent: one per calendar date).

    Also runs the **intraday consistency guard**: the running list of actions
    generated *today* is stored on the day's record. Because this table is
    Supabase-backed, a phone tap on the deployed site, a local run, and a cloud
    Lambda all share the SAME list — so flip-flopping ("做空→观望→做空" from
    tapping 生成决策 repeatedly) is caught no matter where it happens. If the
    action changes within a day the edge isn't real; we flag `intraday_unstable`
    and mutate `decision` so the published snapshot carries it for the UI banner.
    """
    records = _load()
    today = datetime.now().strftime("%Y-%m-%d")

    # Accumulate today's actions from the existing same-day record (if any).
    prior_actions: list[str] = []
    for r in records:
        if r.get("date") == today:
            prior_actions = [a for a in (r.get("intraday_actions") or []) if a]
            if not prior_actions and r.get("action"):
                prior_actions = [r["action"]]
            break
    new_action = decision.get("action")
    actions = prior_actions + ([new_action] if new_action else [])
    unstable = len({a for a in actions if a}) > 1
    decision["intraday_actions"] = actions      # mutate → flows to the published snapshot
    decision["intraday_unstable"] = unstable

    # Same-day regeneration (e.g. post-CPI refresh) REPLACES the pending
    # same-day record — the final decision of the day is what gets graded.
    records = [r for r in records
               if not (r["date"] == today and r.get("status") == "pending")]
    tp = decision.get("trade_plan") or {}
    records.append({
        "id":         str(uuid.uuid4())[:8],
        "date":       today,
        "as_of":      as_of,
        "action":     decision.get("action"),
        "conviction": decision.get("conviction"),
        "p_up_5d":    decision.get("p_up_5d"),
        "price":      round(float(price_at_decision), 2),
        "entry":      tp.get("qbts_entry"),
        "stop":       tp.get("qbts_stop"),
        "target":     tp.get("qbts_target"),
        "summary":    (decision.get("summary") or "")[:160],
        "status":     "pending",
        "result":     None,
        "intraday_actions":  actions,
        "intraday_unstable": unstable,
    })
    _save(records)


def grade_pending(df_daily: pd.DataFrame) -> list[dict]:
    """Grade all pending records old enough to judge. Returns newly graded."""
    records = _load()
    closes = df_daily["close"]
    highs  = df_daily["high"]
    lows   = df_daily["low"]
    dates  = pd.DatetimeIndex(df_daily.index).normalize()

    newly_graded: list[dict] = []
    for r in records:
        if r.get("status") != "pending":
            continue
        try:
            d0 = pd.Timestamp(r["date"]).normalize()
        except Exception:
            continue
        after = dates[dates > d0]
        if len(after) == 0:
            continue

        action = r.get("action")
        p0 = float(r["price"])
        stop, target = r.get("stop"), r.get("target")

        outcome, correct, ret_pct, exit_day = None, None, None, None
        # Path-dependent: did stop or target get touched first?
        for n_day, day in enumerate(after[:_GRADE_AFTER_BARS], 1):
            hi, lo = float(highs.loc[day]), float(lows.loc[day])
            if action == "LONG_QBTX" and stop and target:
                if lo <= float(stop):
                    outcome, correct = "stop_hit", False
                    ret_pct = (float(stop) - p0) / p0
                    exit_day = n_day; break
                if hi >= float(target):
                    outcome, correct = "target_hit", True
                    ret_pct = (float(target) - p0) / p0
                    exit_day = n_day; break
            elif action == "SHORT_QBTZ" and stop and target:
                if hi >= float(stop):
                    outcome, correct = "stop_hit", False
                    ret_pct = (p0 - float(stop)) / p0
                    exit_day = n_day; break
                if lo <= float(target):
                    outcome, correct = "target_hit", True
                    ret_pct = (p0 - float(target)) / p0
                    exit_day = n_day; break

        if outcome is None:
            # No touch — need the full horizon elapsed for a drift grade
            if len(after) < _GRADE_AFTER_BARS:
                continue
            day_n = after[_GRADE_AFTER_BARS - 1]
            ret = (float(closes.loc[day_n]) - p0) / p0
            ret_pct = ret
            exit_day = _GRADE_AFTER_BARS
            if action == "LONG_QBTX":
                outcome, correct = "drift", ret > 0
            elif action == "SHORT_QBTZ":
                outcome, correct = "drift", ret < 0
                ret_pct = -ret    # P&L perspective for a short
            else:  # HOLD — informational
                outcome, correct = "hold", None

        # Shadow grade for HOLD: even when we sat out, was the model's lean
        # (p_up_5d ≷ 0.5) directionally right? Builds a falsifiable record while
        # the system is HOLD-heavy, WITHOUT polluting real-trade accuracy.
        shadow_dir = shadow_correct = None
        if action == "HOLD" and ret_pct is not None:
            p_up = r.get("p_up_5d")
            if p_up is not None:
                shadow_dir = 1 if p_up >= 0.5 else -1
                shadow_correct = (shadow_dir > 0) == (ret_pct > 0)

        r["status"] = "graded"
        r["result"] = {
            "graded_at": datetime.now().strftime("%Y-%m-%d"),
            "outcome":   outcome,
            "correct":   correct,
            "ret_pct":   round(ret_pct, 4) if ret_pct is not None else None,
            "exit_day":  exit_day,
            "reflection": None,
            "shadow_dir":     shadow_dir,
            "shadow_correct": shadow_correct,
        }
        newly_graded.append(r)

    if newly_graded:
        # Reflections for wrong calls — one cheap Haiku call per miss
        for r in newly_graded:
            res = r["result"]
            if res["correct"] is False:
                res["reflection"] = _reflect(r)
        _save(records)
    return newly_graded


def _reflect(r: dict) -> str | None:
    """One-sentence lesson for a wrong call (Haiku, ~$0.001)."""
    try:
        import anthropic
        from dotenv import load_dotenv
        load_dotenv()
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        res = r["result"]
        msg = (f"{r['date']} 系统决策 {r['action']}（信心{r['conviction']}/10，价格${r['price']}），"
               f"理由：{r['summary']}\n"
               f"结果：{res['outcome']}，第{res['exit_day']}天，收益 {res['ret_pct']*100:+.1f}%（判断错误）。\n"
               f"用一句话（≤60字）总结这次错在哪、下次同类情形该注意什么。只输出这句话。")
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=150,
            messages=[{"role": "user", "content": msg}],
        )
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
        return text.strip()[:120] or None
    except Exception as e:
        logger.warning(f"reflection failed: {e}")
        return None


_PAPER_USD = 1000.0   # 模拟持仓:每个方向单跟随的假钱本金


def load_recent(n: int = 12) -> dict:
    """Journal payload for dashboard + decision prompt."""
    allr = sorted(_load(), key=lambda r: r["date"], reverse=True)
    records = allr[:n]
    graded = [r for r in records if r.get("status") == "graded"
              and r["result"] and r["result"]["correct"] is not None]
    n_correct = sum(1 for r in graded if r["result"]["correct"])

    # Shadow accuracy = directional lean correct across BOTH real trades and
    # HOLDs (uses correct for trades, shadow_correct for HOLDs). A falsifiable
    # signal of edge even when the system mostly sits out.
    def _lean(r: dict):
        res = r.get("result") or {}
        if res.get("correct") is not None:
            return res["correct"]
        return res.get("shadow_correct")
    shadow = [r for r in records if r.get("status") == "graded" and _lean(r) is not None]
    n_shadow_correct = sum(1 for r in shadow if _lean(r))

    # 模拟持仓 — 全量(非只展示的 n 条):每个已评判方向单当 $1000 假钱,按计划
    # 止损/目标结算的 ret_pct 计盈亏;HOLD 不开仓。衡量"照决策做能不能赚到钱"。
    # ret_pct 已是盈利视角(做空时取负),正=赚。按标的算,未含 2× ETF 杠杆/衰减。
    _dir_graded = [r for r in allr
                   if r.get("status") == "graded"
                   and r.get("action") in ("LONG_QBTX", "SHORT_QBTZ")
                   and (r.get("result") or {}).get("ret_pct") is not None]
    _realized = sum(_PAPER_USD * r["result"]["ret_pct"] for r in _dir_graded)
    _pwin = sum(1 for r in _dir_graded if r["result"]["ret_pct"] > 0)
    _pend_dir = [r for r in allr if r.get("status") == "pending"
                 and r.get("action") in ("LONG_QBTX", "SHORT_QBTZ")]
    _op = max(_pend_dir, key=lambda r: r.get("date", "")) if _pend_dir else None
    paper = {
        "trade_usd": _PAPER_USD,
        "realized":  round(_realized, 2),
        "n_trades":  len(_dir_graded),
        "n_win":     _pwin,
        "win_rate":  round(_pwin / len(_dir_graded), 3) if _dir_graded else None,
        "open": ({"action": _op["action"], "entry": _op.get("price"),
                  "date": _op.get("date"), "stop": _op.get("stop"),
                  "target": _op.get("target")} if _op else None),
    }

    return {
        "records":   records,
        "paper":     paper,
        "n_graded":  len(graded),
        "n_correct": n_correct,
        "accuracy":  round(n_correct / len(graded), 3) if graded else None,
        "n_shadow":         len(shadow),
        "n_shadow_correct": n_shadow_correct,
        "shadow_accuracy":  round(n_shadow_correct / len(shadow), 3) if shadow else None,
        "lessons":   [r["result"]["reflection"] for r in records
                      if r.get("result") and r["result"].get("reflection")][:5],
    }
