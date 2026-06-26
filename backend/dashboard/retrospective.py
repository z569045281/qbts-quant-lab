"""
Monthly retrospective — the model reads the accumulated prediction/decision
track record and writes a plain-Chinese review: what's calibrated, which signal
sources show edge, whether there's any directional edge yet, and what to tune.

One Opus call (~$0.1). Run monthly (manually `python retrospective.py`, from the
local control panel, or a scheduled job). The result is persisted to Supabase
`retrospective` (id="current") so the deployed static site can display it without
re-spending on Opus — the frontend button just reads the latest row.

Why a separate monthly job (not part of daily publish): the daily Opus call is
the trade decision; a review is only meaningful once a month of data has piled up,
and re-running it every day would burn money for a report nobody reads daily.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from datetime import datetime, timezone

import pandas as pd

logger = logging.getLogger(__name__)

_TABLE = "retrospective"
_MODEL = "claude-opus-4-8"      # same brain as the decision; this is a once-a-month review
_SB = None
_SB_INIT = False


def _supabase():
    """Cached Supabase client (secret key — write-capable), or None."""
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
            logger.warning(f"retrospective: Supabase init failed — {e}")
            _SB = None
    return _SB


def _gather(df_daily: pd.DataFrame) -> dict:
    """Pull the graded track record into a compact stats dict for the prompt."""
    from dashboard.calibration import grade_predictions
    from dashboard.journal import _load as load_journal

    cal = grade_predictions(df_daily)   # n_total/n_graded/overall_hit_rate/calibration[]/by_source{}

    recs = load_journal()
    actions = Counter(r.get("action") for r in recs)
    graded = [r for r in recs if r.get("status") == "graded" and r.get("result")]

    # Real directional trades: $1000 per call, P&L from the graded ret_pct
    # (already profit-perspective — negated for shorts). Same convention as journal.py.
    dir_graded = [r for r in graded
                  if r.get("action") in ("LONG_QBTX", "SHORT_QBTZ")
                  and r["result"].get("ret_pct") is not None]
    dir_pnl = round(sum(1000.0 * r["result"]["ret_pct"] for r in dir_graded), 2)
    dir_win = sum(1 for r in dir_graded if r["result"]["ret_pct"] > 0)

    # Shadow lean: directional correctness across BOTH trades and HOLDs.
    def _lean(r: dict):
        res = r.get("result") or {}
        return res["correct"] if res.get("correct") is not None else res.get("shadow_correct")
    shadow = [r for r in graded if _lean(r) is not None]
    shadow_correct = sum(1 for r in shadow if _lean(r))

    dates = sorted(r.get("date", "") for r in recs if r.get("date"))
    return {
        "period_start":   dates[0] if dates else None,
        "period_end":     dates[-1] if dates else None,
        "n_decisions":    len(recs),
        "action_dist":    dict(actions),
        "calibration":    cal,
        "dir_trades":     len(dir_graded),
        "dir_win":        dir_win,
        "dir_pnl_usd":    dir_pnl,
        "shadow_n":       len(shadow),
        "shadow_correct": shadow_correct,
    }


def _summarize(stats: dict) -> str:
    """Render the stats into compact human-readable text for the model."""
    cal = stats.get("calibration") or {}
    L = [
        f"统计区间: {stats['period_start']} → {stats['period_end']}",
        f"决策条数: {stats['n_decisions']}，动作分布: {stats['action_dist']}",
        "",
        f"【机械 edge 校准】预测总数 {cal.get('n_total', 0)}，已评判 {cal.get('n_graded', 0)}，"
        f"整体方向命中率 {cal.get('overall_hit_rate', 0.5)}",
    ]
    buckets = cal.get("calibration") or []
    if buckets:
        L.append("校准曲线 (模型说涨的概率 → 实际涨的比例):")
        for b in buckets:
            L.append(f"  预测P(up)≈{b['predicted_p_up']:.0%} → 实际涨 {b['realized_hit_rate']:.0%} (n={b['n']})")
    by_src = cal.get("by_source") or {}
    if by_src:
        L.append("各信号源命中率 (命中率 / 样本n / 学习到的权重系数):")
        for src, info in sorted(by_src.items(), key=lambda kv: -kv[1]["n"]):
            L.append(f"  {src}: 命中{info['hit_rate']:.0%} n={info['n']} 权重×{info['weight_mult']}")
    L += [
        "",
        f"【方向单(实际下注)】{stats['dir_trades']} 笔，胜 {stats['dir_win']}，"
        f"模拟盈亏 ${stats['dir_pnl_usd']}（每笔 $1000 本金，按标的算，未含 2× 杠杆/衰减）",
        f"【方向倾向影子评判(含观望日)】{stats['shadow_n']} 笔，对 {stats['shadow_correct']}",
    ]
    return "\n".join(L)


_SYSTEM = """你是一名严谨、反对自我欺骗的量化投资复盘官。给你一个个人交易仪表盘累计的预测/决策战绩,
写一份冷静、证据导向的中文复盘。硬规则:
- 样本少就直说"统计上不可信、还不能下结论",绝不从噪声里编故事或给虚假信心。
- 校准:模型说"40%涨"的事是否真有约 40% 涨?偏差往哪偏(过度自信还是过度保守)。
- 信号源:哪些命中率显著 >50% 且样本够、值得加权;哪些 ≈50% 或更差、该砍或观望。
- 方向 edge:这套系统到目前为止,有没有可证伪的赚钱迹象?还是和抛硬币无异?明确说。
- 给 ≤3 条具体、可执行的下一步(改权重/继续攒样本/调纪律/别加仓),不要空话。
- 面向一个股票小白用户,用大白话;必须用的术语一句话解释。
输出 markdown,中文,300-500 字,用 ## 小标题分段。"""


def run_retrospective(df_daily: pd.DataFrame, sb=None) -> dict:
    """Generate the retrospective (one Opus call) and persist it to Supabase."""
    import anthropic
    from dotenv import load_dotenv
    load_dotenv()

    stats = _gather(df_daily)
    summary = _summarize(stats)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=_MODEL,
        max_tokens=2000,
        system=_SYSTEM,
        messages=[{"role": "user", "content": f"以下是累计战绩数据:\n\n{summary}\n\n请写复盘。"}],
    )
    report = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "").strip()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "period_start": stats["period_start"],
        "period_end":   stats["period_end"],
        "stats":        stats,
        "report_md":    report,
    }

    sb = sb or _supabase()
    if sb is not None:
        try:
            sb.table(_TABLE).upsert({"id": "current", "data": payload}).execute()
        except Exception as e:
            logger.warning(f"retrospective: Supabase write failed — {e}")
    return payload


def load_retrospective() -> dict | None:
    """Read the latest persisted retrospective (for the dashboard / local display)."""
    sb = _supabase()
    if sb is None:
        return None
    try:
        rows = sb.table(_TABLE).select("data").eq("id", "current").execute().data
        return rows[0]["data"] if rows and rows[0].get("data") else None
    except Exception as e:
        logger.warning(f"retrospective: Supabase load failed — {e}")
        return None
