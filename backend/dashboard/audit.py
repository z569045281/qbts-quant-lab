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

2026-07-13 报告口径补充(判决规则本身未动,以下均为新增可见度):
  · HOLD 判读(预注册):AI 决策 HOLD 也可评判 —— 决策覆盖的那个交易日
    |QBTS 涨跌| < 3% = 判对(货架上有 QBTX/QBTZ 双向工具,错过任一方向
    ≥3% 的行情都算漏判)。与方向单分开统计,不并入 n≥30 判决。
  · 纸面马净值行补同窗「买入持有」对照(数据一直在 start_date/bh_nav 里,
    此前报告不显示,导致七马看似全输、实则多数跑赢暴跌中的持有)。

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
        # HOLD 判读(2026-07-13 预注册补充,见模块 docstring;展示用,不触发权重)。
        # 决策是 09:00 ET 盘前发布 → 覆盖的是 record 日期起的第一个交易日;
        # 当日实盘未收盘(该 bar 是最后一根且就是今天)则跳过不评。
        closes = df_d["close"]
        rets = closes.pct_change()
        today_utc = datetime.now(timezone.utc).date()
        h_n = h_hit = 0
        for r in recs:
            if r.get("action") != "HOLD":
                continue
            dt = str(r.get("date") or "")[:10]
            if not dt:
                continue
            idx = rets.index[rets.index >= dt]
            if len(idx) == 0 or idx[0].date() >= today_utc:
                continue
            rv = rets.loc[idx[0]]
            if rv != rv:            # NaN(首根 bar)
                continue
            h_n += 1
            h_hit += abs(float(rv)) < 0.03
        report["sections"]["decision_journal"]["hold_read"] = {
            **_verdict(h_hit, h_n),
            "rule": "|决策日QBTS涨跌|<3% 判对(双向工具在架,错过≥3%行情=漏判)",
        }
        # 每日方向表态(2026-07-13 加,用户要求"大胆预测可测量"):方向单的 correct
        # 与 HOLD 影子分(bold_call_5d 强制二选一;旧记录回退 p_up≷0.5)合并成
        # 一条日频方向台账 —— 观望月也能攒方向样本。附 p_up 骑墙率作病征指标
        # (07-13 体检:21 天 95% 挤在 [0.45,0.55],方向能力整月不可测)。
        lean = []
        for r in recs:
            res = r.get("result") or {}
            v = res.get("correct") if res.get("correct") is not None else res.get("shadow_correct")
            if v is not None:
                lean.append(bool(v))
        p_all = [float(r["p_up_5d"]) for r in recs if r.get("p_up_5d") is not None]
        fence = sum(1 for p in p_all if 0.45 <= p <= 0.55)
        report["sections"]["decision_journal"]["daily_call"] = {
            **_verdict(sum(lean), len(lean)),
            "p_up_fence_pct": round(fence / len(p_all), 3) if p_all else None,
        }
        # 影子考场:Fable vs DeepSeek 的 bold_call 按统一 fwd5 口径同框
        for fld, key in (("bold_correct", "bold_fable"), ("ds_bold_correct", "bold_deepseek")):
            vals = [bool((r.get("result") or {}).get(fld))
                    for r in recs if (r.get("result") or {}).get(fld) is not None]
            if vals:
                report["sections"]["decision_journal"][key] = _verdict(sum(vals), len(vals))
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
                h = {"nav": blk["nav"],
                     "ret_pct": round(blk["nav"] / 1000 - 1, 4),
                     "verdict": "净值陪跑·8/15 判决"}
                # 同窗买入持有对照(口径补充,判决仍在 8/15):优先用马自己
                # 记的 bh_ret_pct,没有就按 start_date 从日线现算
                bh = blk.get("bh_ret_pct")
                if bh is None and blk.get("start_date"):
                    try:
                        s = df_d["close"][df_d.index >= str(blk["start_date"])[:10]]
                        if len(s) > 1:
                            bh = round(float(s.iloc[-1] / s.iloc[0]) - 1, 4)
                    except Exception:
                        bh = None
                if bh is not None:
                    h["bh_ret_pct"] = bh
                    h["vs_bh_pp"] = round((h["ret_pct"] - bh) * 100, 1)
                horses[key] = h
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
        hr = dj.get("hold_read")
        if hr and hr.get("n"):
            L.append(f"   HOLD 判读(|当日|<3%=对) n={hr['n']} 命中{hr['hit_rate']*100:.0f}% "
                     f"CI[{hr['ci95'][0]*100:.0f},{hr['ci95'][1]*100:.0f}] {hr['verdict']}")
        dc = dj.get("daily_call")
        if dc and dc.get("n"):
            fence = dc.get("p_up_fence_pct")
            L.append(f"   每日方向表态(方向单+HOLD影子) n={dc['n']} 命中{dc['hit_rate']*100:.0f}% "
                     f"CI[{dc['ci95'][0]*100:.0f},{dc['ci95'][1]*100:.0f}] {dc['verdict']}"
                     + (f" · p_up骑墙率 {fence*100:.0f}%(目标应随 bold_call 上线归零)"
                        if fence is not None else ""))
        for key, label in (("bold_fable", "🥊 表态vs5日 Fable"),
                           ("bold_deepseek", "🥊 表态vs5日 DeepSeek影子")):
            b = dj.get(key)
            if b and b.get("n"):
                L.append(f"   {label} n={b['n']} 命中{b['hit_rate']*100:.0f}% "
                         f"CI[{b['ci95'][0]*100:.0f},{b['ci95'][1]*100:.0f}] {b['verdict']}")
    hs = report["sections"].get("paper_horses", {})
    if hs and "error" not in hs:
        L.append("\n③ 纸面马竞速:")
        for k, d in hs.items():
            if "n" in d:
                L.append(f"   {k:<14s} n={d['n']:<3d} 命中{d['hit_rate']*100:3.0f}% "
                         f"{d['verdict']} 落袋${d.get('realized')}")
            elif "nav" in d:
                bh = d.get("bh_ret_pct")
                extra = ""
                if bh is not None:
                    vs = d.get("vs_bh_pp") or 0
                    extra = (f" | 买入持有{bh*100:+.1f}% → "
                             f"{'跑赢' if vs >= 0 else '跑输'}{abs(vs):.1f}pp")
                L.append(f"   {k:<14s} 净值${d['nav']:.0f} ({d['ret_pct']*100:+.1f}%)"
                         f"{extra} {d['verdict']}")
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
