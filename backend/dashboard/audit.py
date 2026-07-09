"""⚖️ 8/15 审判工具 — 把「拍脑袋先验」换成「实测命中率」的一键报告。

CLAUDE.md 的常设提醒:edge.py 的所有权重都是硬编码先验,等各源已评判样本
≥30 时必须用真实命中率表重定权重、决定去留。本模块就是那场审判的执行器:
汇总 校准台账(逐源命中) + 决策台账(AI 决策本身) + 各纸面马/自选扫描账本,
按下面**预注册规则**(2026-07-09 写死,审判日不得看着数字改标准)给每源判决:

  n < 30                     → 样本不足·继续测量(权重不动)
  n ≥ 30 且 Wilson95%下界>0.5 → 转正·按命中率定权(mult = 0.5+(hit−0.5)×2)
  n ≥ 30 且 Wilson95%上界<0.5 → 剔除(建议 mult=0,信号静音)
  其余                        → 中性·维持自学习 mult

只读不写:工具产出报告(stdout + cache/audit_report.json),权重改动仍走
人工 code review(edge.py 常量),证据在手再动刀。

用法: python audit.py   (repo 根;或 python -m dashboard.audit 于 backend/)
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# journal/calibration/scan_store 都按「有 Supabase 环境变量则读云端,否则静默
# 回退本地文件」工作 — 独立脚本不加载 .env 会拿到一份陈旧的本地影子账本,
# 审判就成了审假账。必须在导入它们之前把环境变量备好。
load_dotenv()

_OUT = Path(__file__).parent.parent / "data" / "cache" / "audit_report.json"

_N_MIN = 30           # 判决门槛(预注册)
_Z = 1.96             # Wilson 95%


def _wilson(hits: int, n: int) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = hits / n
    denom = 1 + _Z**2 / n
    centre = (p + _Z**2 / (2 * n)) / denom
    half = _Z * math.sqrt(p * (1 - p) / n + _Z**2 / (4 * n**2)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _verdict(hits: int, n: int) -> dict:
    lo, hi = _wilson(hits, n)
    hit = hits / n if n else 0.5
    if n < _N_MIN:
        v, mult = "样本不足·继续测量", None
    elif lo > 0.5:
        v, mult = "✅ 转正·按命中率定权", round(max(0.0, min(2.0, 0.5 + (hit - 0.5) * 2)), 2)
    elif hi < 0.5:
        v, mult = "❌ 剔除(静音)", 0.0
    else:
        v, mult = "中性·维持自学习", None
    return {"n": n, "hits": hits, "hit_rate": round(hit, 3),
            "ci95": [round(lo, 3), round(hi, 3)], "verdict": v,
            "recommended_mult": mult}


def run_audit() -> dict:
    from data.fetcher import load_or_fetch
    from dashboard.calibration import grade_predictions
    from dashboard import journal as jr
    from dashboard.qbts_paper import analyze_champs

    # 强刷:审判按最新收盘算,别让 24h 缓存少评一天
    _, df_d = load_or_fetch(force_refresh=True)
    report: dict = {"as_of": datetime.now(timezone.utc).isoformat(),
                    "n_min": _N_MIN, "sections": {}}

    # ── ① edge 逐源校准(核心审判对象:edge.py 的权重先验)────────────────
    cal = grade_predictions(df_d)
    sources = {}
    for src, d in (cal.get("by_source") or {}).items():
        sources[src] = _verdict(d.get("hits", 0), d.get("n", 0))
        sources[src]["current_learned_mult"] = d.get("weight_mult")
    report["sections"]["edge_sources"] = {
        "n_graded_days": cal.get("n_graded"),
        "overall_hit_rate": cal.get("overall_hit_rate"),
        "sources": sources,
    }

    # ── ② AI 决策台账(决策本身当一个"源"审)────────────────────────────
    try:
        j = jr.load_recent(500)
        recs = j.get("records") or []
        graded = [r for r in recs if (r.get("result") or {}).get("ret_pct") is not None
                  and r.get("action") in ("LONG_QBTX", "SHORT_QBTZ")]
        wins = sum(1 for r in graded if r["result"]["ret_pct"] > 0)
        report["sections"]["decision_journal"] = {
            **_verdict(wins, len(graded)),
            "paper": j.get("paper"),
        }
    except Exception as e:
        report["sections"]["decision_journal"] = {"error": str(e)[:120]}

    # ── ③ 纸面马竞速(冠军陪跑/特调/BTC 等,mining.md 的活体样本)─────────
    try:
        champs = analyze_champs(df_d) or {}
        horses = {}
        for key, blk in champs.items():
            if not isinstance(blk, dict):
                continue
            if blk.get("n_closed") is not None:          # 交易型马(特调/swing)
                horses[key] = {**_verdict(blk.get("n_win") or 0, blk["n_closed"]),
                               "realized": blk.get("realized")}
            elif blk.get("nav") is not None:             # 净值型马($1000 起跑)
                horses[key] = {"nav": blk["nav"],
                               "ret_pct": round(blk["nav"] / 1000 - 1, 4),
                               "verdict": "净值陪跑·8/15 与买入持有对比"}
        report["sections"]["paper_horses"] = horses
    except Exception as e:
        report["sections"]["paper_horses"] = {"error": str(e)[:120]}

    # ── ④ 自选扫描纸面账本 ─────────────────────────────────────────────
    try:
        from dashboard.scan_store import _load_paper
        p = _load_paper() or {}
        closed = p.get("closed") or []
        wins = sum(1 for t in closed if (t.get("pnl") or 0) > 0)
        report["sections"]["scan_paper"] = {
            **_verdict(wins, len(closed)),
            "realized_usd": round(sum(t.get("pnl") or 0 for t in closed), 2),
        }
    except Exception as e:
        report["sections"]["scan_paper"] = {"error": str(e)[:120]}

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def format_report(report: dict) -> str:
    L = ["⚖️ 审判报告 " + report["as_of"][:16].replace("T", " ") + " UTC",
         f"(判决门槛 n≥{report['n_min']};规则预注册于 audit.py,不得临场更改)", ""]
    es = report["sections"].get("edge_sources", {})
    L.append(f"① edge 逐源校准 — 已评判 {es.get('n_graded_days')} 天,整体方向命中 "
             f"{(es.get('overall_hit_rate') or 0)*100:.0f}%")
    rows = sorted((es.get("sources") or {}).items(), key=lambda x: -x[1]["n"])
    for src, d in rows:
        mult = f" → 建议mult {d['recommended_mult']}" if d["recommended_mult"] is not None else ""
        L.append(f"   {src:<22s} n={d['n']:<3d} 命中{d['hit_rate']*100:3.0f}% "
                 f"CI[{d['ci95'][0]*100:.0f},{d['ci95'][1]*100:.0f}] {d['verdict']}{mult}"
                 f"(现自学习mult {d.get('current_learned_mult')})")
    dj = report["sections"].get("decision_journal", {})
    if "n" in dj:
        pp = dj.get("paper") or {}
        L.append(f"\n② AI 决策台账 — 方向单 n={dj['n']} 命中{dj['hit_rate']*100:.0f}% "
                 f"CI[{dj['ci95'][0]*100:.0f},{dj['ci95'][1]*100:.0f}] {dj['verdict']}"
                 f" · 模拟持仓已实现 ${pp.get('realized')}")
    hs = report["sections"].get("paper_horses", {})
    if hs and "error" not in hs:
        L.append("\n③ 纸面马竞速:")
        for k, d in hs.items():
            if "n" in d:
                L.append(f"   {k:<14s} n={d['n']:<3d} 命中{d['hit_rate']*100:3.0f}% "
                         f"{d['verdict']} 落袋${d.get('realized')}")
            elif "nav" in d:
                L.append(f"   {k:<14s} 净值${d['nav']:.0f} ({d['ret_pct']*100:+.1f}%) {d['verdict']}")
    sp = report["sections"].get("scan_paper", {})
    if "n" in sp:
        L.append(f"\n④ 自选扫描纸面 — n={sp['n']} 胜率{sp['hit_rate']*100:.0f}% "
                 f"{sp['verdict']} 已实现 ${sp.get('realized_usd')}")
    L.append("\n结论应用:仅『✅ 转正』与『❌ 剔除』触发 edge.py 权重改动(人工 review);"
             "其余一律继续测量。")
    return "\n".join(L)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    print(format_report(run_audit()))
