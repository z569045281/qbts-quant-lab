"""⚖️ 8/15 审判工具 — 把「拍脑袋先验」换成「实测命中率」的一键报告。

CLAUDE.md 的常设提醒:edge.py 的所有权重都是硬编码先验,等各源已评判样本
≥30 时必须用真实命中率表重定权重、决定去留。本模块就是那场审判的执行器:
汇总 校准台账(逐源命中) + 决策台账(AI 决策本身) + 各纸面马/自选扫描账本,
按下面**预注册规则**(2026-07-09 写死,审判日不得看着数字改标准)给每源判决:

  n < 30                     → 样本不足·继续测量(权重不动)
  n ≥ 30 且 Wilson95%下界>0.5 → 转正·按命中率定权(mult = 0.5+(hit−0.5)×2)
  n ≥ 30 且 Wilson95%上界<0.5 → 剔除(建议 mult=0,信号静音)
  其余                        → 中性·维持自学习 mult

**预注册修订 2026-07-24(用户拍板"按修正版落地")— 判决线 p* 分池:**
原规则一刀切 p*=0.5,与各交易池自己代码里写死的开仓 RR 闸门自相矛盾
(45%胜率×1.5R 每笔期望 +0.125R 是赚钱的,却会被"胜率须>50%"枪毙)。
修订:判决线改为各池**自己代码承诺的保本胜率 p* = 1/(1+RR_design)** ——
该数由设计常数推出,任何人重算同值,无看结果调参空间:
  · 方向表态类(edge逐源/daily_call/三影子/HOLD判读):无止损/目标,p*=0.5 不变
  · 自选扫描 v2(scan.py 1.5R 门):p*=0.40;v1 老仓无 RR 门,p*=0.5
  · 游击战(guerrilla.py _RR_MIN=2.5):p*=1/3.5≈0.286
  · AI 方向单:按各单记录的 stop/target 现算平均计划 RR → p*=1/(1+RR̄)
统计机器不变(仍 Wilson 二项,小样本功效最高);期望R(胜率×平均盈R/平均
亏R)**只做展示列,不做判决依据**(肥尾下均值 CI 需 n≈60-170,8/15 前判不
动,换成它=废掉剔除权)。凡 p*≠0.5 的池,报告**新旧两线并排**打出,判决
分歧一目了然。修订依据=设计常数与判决标准矛盾,非对已见结果不满意;
2026-07-24 写死,审判日仍不得看着数字改标准。

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


def _judge(lo: float, hi: float, n: int, breakeven: float) -> str:
    """Wilson CI vs 判决线 p* → 判决文本(预注册修订 2026-07-24:p* 分池)。"""
    if n < _N_MIN:
        return "样本不足·继续测量"
    if lo > breakeven:
        return "✅ 转正"
    if hi < breakeven:
        return "❌ 剔除(静音)"
    return "中性·维持自学习"


def _verdict(hits: int, n: int, breakeven: float = 0.5) -> dict:
    """breakeven = 该池代码承诺的保本胜率 p*=1/(1+RR_design);方向表态类保持 0.5。
    p*≠0.5 时输出 legacy_at_50(旧一刀切线的判决)并排留证。"""
    lo, hi = _wilson(hits, n)
    hit = hits / n if n else breakeven
    v = _judge(lo, hi, n, breakeven)
    mult = None
    if v.startswith("✅"):
        if breakeven == 0.5:
            v = "✅ 转正·按命中率定权"
            mult = round(max(0.0, min(2.0, 0.5 + (hit - 0.5) * 2)), 2)
    elif v.startswith("❌"):
        mult = 0.0
    out = {"n": n, "hits": hits, "hit_rate": round(hit, 3),
           "ci95": [round(lo, 3), round(hi, 3)], "verdict": v,
           "recommended_mult": mult}
    if breakeven != 0.5:
        out["breakeven"] = round(breakeven, 3)
        out["legacy_at_50"] = _judge(lo, hi, n, 0.5)
    return out


def _expectancy_r(rs: list[float]) -> dict | None:
    """展示用期望 R(每笔风险倍数)。只报数,不参与判决(见模块 docstring)。"""
    rs = [float(r) for r in rs if r is not None and math.isfinite(float(r))]
    if not rs:
        return None
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    return {"n_r": len(rs),
            "exp_r": round(sum(rs) / len(rs), 3),
            "avg_win_r": round(sum(wins) / len(wins), 3) if wins else None,
            "avg_loss_r": round(sum(losses) / len(losses), 3) if losses else None}


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
    # 2026-07-22 AI 自检抓到:grade_predictions 从不读 model 标签,v1(已于
    # 07-17 停用)的陈年记录混进"当前"校准,把 v1 的 21% 拖成"25条23%"顶替
    # v2 汇报——v2 才 3 条记录、仅 1 条够格评分(部分窗口),远不到能下结论的
    # 量。现在默认只算 v2(见 calibration.py），v1 的历史成绩单独留档对照,
    # 不再混进当前判决。
    cal = grade_predictions(df_d)                    # v2-only(新默认)
    cal_v1_legacy = grade_predictions(df_d, model="v1")
    sources = {}
    for src, d in (cal.get("by_source") or {}).items():
        sources[src] = _verdict(d.get("hits", 0), d.get("n", 0))
        sources[src]["current_learned_mult"] = d.get("weight_mult")
    report["sections"]["edge_sources"] = {
        "n_graded_days": cal.get("n_graded"),
        "overall_hit_rate": cal.get("overall_hit_rate"),
        "sources": sources,
        "v1_legacy_frozen": {                          # 仅供对照,不参与判决
            "n_graded": cal_v1_legacy.get("n_graded"),
            "overall_hit_rate": cal_v1_legacy.get("overall_hit_rate"),
        },
    }

    # ── ② AI 决策台账(决策本身当一个"源"审)────────────────────────────
    try:
        j = jr.load_recent(500)
        recs = j.get("records") or []
        graded = [r for r in recs if (r.get("result") or {}).get("ret_pct") is not None
                  and r.get("action") in ("LONG_QBTX", "SHORT_QBTZ")]
        wins = sum(1 for r in graded if r["result"]["ret_pct"] > 0)
        # 保本线(预注册修订 2026-07-24):按各单记录的 stop/target 现算计划 RR
        # (基准价 = 评分口径同款 p0),p* = 1/(1+RR̄);无可算记录退回 0.5。
        # 期望R = ret_pct / 单笔风险距,展示用。
        rrs, r_mults = [], []
        for r in graded:
            try:
                p0 = float(r.get("price") or 0)
                stop = r.get("stop")
                if not p0 or stop is None:
                    continue
                risk = abs(p0 - float(stop)) / p0
                if risk <= 0:
                    continue
                tgt = r.get("target")
                if tgt is not None:
                    rrs.append(abs(float(tgt) - p0) / (p0 * risk))
                r_mults.append(float(r["result"]["ret_pct"]) / risk)
            except (TypeError, ValueError):
                continue
        be_dir = 1 / (1 + sum(rrs) / len(rrs)) if rrs else 0.5
        report["sections"]["decision_journal"] = {
            **_verdict(wins, len(graded), breakeven=be_dir),
            "planned_rr_mean": round(sum(rrs) / len(rrs), 2) if rrs else None,
            "expectancy": _expectancy_r(r_mults),
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
        # 影子考场:Fable vs DeepSeek vs v1反向影子(2026-07-21,用户拍板) 的
        # bold_call 按统一 fwd5 口径同框
        for fld, key in (("bold_correct", "bold_fable"), ("ds_bold_correct", "bold_deepseek"),
                         ("v1inv_bold_correct", "bold_v1inv")):
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

    # ── ④ 自选扫描纸面账本(按 epoch 分池 — CLAUDE.md 07-13 承诺的"审判按
    #     epoch 分开统计"此前从未落地,又一例"没人读的标签只是装饰")──────
    #     v2 有 scan.py 1.5R 开仓门 → 保本线 p*=1/(1+1.5)=0.40(预注册修订
    #     2026-07-24);v1 老仓无 RR 门 → 维持 0.5。期望R = pnl_pct/stop_pct
    #     (stop_pct 2026-07-24 起才随平仓记录落账,老记录缺→不进R统计)。
    try:
        from dashboard.scan_store import _load_paper
        p = _load_paper() or {}
        closed = p.get("closed") or []
        pools = {}
        for epoch, be in (("v1", 0.5), ("v2", 1 / 2.5)):
            trades = [t for t in closed if t.get("epoch", "v1") == epoch]
            wins = sum(1 for t in trades if (t.get("pnl") or 0) > 0)
            rs = [t["pnl_pct"] / t["stop_pct"] for t in trades
                  if t.get("stop_pct") and t.get("pnl_pct") is not None]
            pools[epoch] = {
                **_verdict(wins, len(trades), breakeven=be),
                "expectancy": _expectancy_r(rs),
                "realized_usd": round(sum(t.get("pnl") or 0 for t in trades), 2),
            }
        report["sections"]["scan_paper"] = {
            "by_epoch": pools,
            "realized_usd": round(sum(t.get("pnl") or 0 for t in closed), 2),
            "n_total": len(closed),
        }
    except Exception as e:
        report["sections"]["scan_paper"] = {"error": str(e)[:120]}

    # ── ⑤ 游击战账本(2026-07-24 接入 — 此前根本不在审判范围)────────────
    #     开仓门 _RR_MIN=2.5 → 保本线 p*=1/3.5≈0.286。表缺/无记录 → 静默跳过。
    try:
        from dashboard.guerrilla import _sb, _get, _RR_MIN
        sb = _sb()
        led = (_get(sb, "ledger") or {}) if sb else {}
        trades = led.get("trades") or []
        if trades:
            wins = sum(1 for t in trades if (t.get("pnl") or 0) > 0)
            rs = []
            for t in trades:
                try:
                    entry, stop = float(t["entry"]), float(t["stop"])
                    risk = (entry - stop) / entry
                    if risk > 0 and t.get("ret_pct") is not None:
                        rs.append(float(t["ret_pct"]) / risk)
                except (KeyError, TypeError, ValueError, ZeroDivisionError):
                    continue
            report["sections"]["guerrilla"] = {
                **_verdict(wins, len(trades), breakeven=1 / (1 + _RR_MIN)),
                "expectancy": _expectancy_r(rs),
                "realized_usd": led.get("realized"),
            }
    except Exception as e:
        report["sections"]["guerrilla"] = {"error": str(e)[:120]}

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _fmt_be(d: dict) -> str:
    """判决行通用尾巴:p*≠0.5 时打出新旧两线并排 + 期望R展示列。"""
    s = ""
    if d.get("breakeven") is not None:
        s += f" 判决线{d['breakeven']*100:.0f}%"
        legacy = d.get("legacy_at_50")
        if legacy and legacy != d["verdict"].replace("·按命中率定权", ""):
            s += f"(旧线50%判:{legacy})"
    e = d.get("expectancy")
    if e:
        w = f"{e['avg_win_r']:+.2f}" if e.get("avg_win_r") is not None else "—"
        l = f"{e['avg_loss_r']:+.2f}" if e.get("avg_loss_r") is not None else "—"
        s += f" · 期望{e['exp_r']:+.2f}R(盈{w}/亏{l},n_R={e['n_r']})"
    return s


def format_report(report: dict) -> str:
    L = ["⚖️ 审判报告 " + report["as_of"][:16].replace("T", " ") + " UTC",
         f"(判决门槛 n≥{report['n_min']};规则预注册于 audit.py,不得临场更改;"
         f"2026-07-24 修订:交易池判决线=各池保本胜率 1/(1+RR_design),期望R仅展示)", ""]
    es = report["sections"].get("edge_sources", {})
    L.append(f"① edge 逐源校准(v2,2026-07-17起)— 已评判 {es.get('n_graded_days')} 天,"
             f"整体方向命中 {(es.get('overall_hit_rate') or 0)*100:.0f}%"
             f"{' ⚠️n太小,远不到能下结论的量' if (es.get('n_graded_days') or 0) < _N_MIN else ''}")
    v1l = es.get("v1_legacy_frozen") or {}
    if v1l.get("n_graded"):
        L.append(f"   （v1 历史存档,已停用,不参与本次判决:n={v1l['n_graded']} "
                 f"命中{(v1l.get('overall_hit_rate') or 0)*100:.0f}%）")
    rows = sorted((es.get("sources") or {}).items(), key=lambda x: -x[1]["n"])
    for src, d in rows:
        mult = f" → 建议mult {d['recommended_mult']}" if d["recommended_mult"] is not None else ""
        L.append(f"   {src:<22s} n={d['n']:<3d} 命中{d['hit_rate']*100:3.0f}% "
                 f"CI[{d['ci95'][0]*100:.0f},{d['ci95'][1]*100:.0f}] {d['verdict']}{mult}"
                 f"(现自学习mult {d.get('current_learned_mult')})")
    dj = report["sections"].get("decision_journal", {})
    if "n" in dj:
        pp = dj.get("paper") or {}
        rr = f"(计划RR均值 {dj['planned_rr_mean']})" if dj.get("planned_rr_mean") else ""
        L.append(f"\n② AI 决策台账 — 方向单 n={dj['n']} 命中{dj['hit_rate']*100:.0f}% "
                 f"CI[{dj['ci95'][0]*100:.0f},{dj['ci95'][1]*100:.0f}] {dj['verdict']}"
                 f"{_fmt_be(dj)}{rr}"
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
                           ("bold_deepseek", "🥊 表态vs5日 DeepSeek影子"),
                           ("bold_v1inv", "🥊 表态vs5日 v1反向影子")):
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
    if sp.get("by_epoch"):
        L.append(f"\n④ 自选扫描纸面(按 epoch 分池)— 合计 n={sp.get('n_total')} "
                 f"已实现 ${sp.get('realized_usd')}")
        for ep, d in sp["by_epoch"].items():
            if not d.get("n"):
                continue
            L.append(f"   {ep:<4s} n={d['n']:<3d} 胜率{d['hit_rate']*100:3.0f}% "
                     f"CI[{d['ci95'][0]*100:.0f},{d['ci95'][1]*100:.0f}] {d['verdict']}"
                     f"{_fmt_be(d)} 已实现 ${d.get('realized_usd')}")
    gu = report["sections"].get("guerrilla", {})
    if "n" in gu:
        L.append(f"\n⑤ 游击战纸面 — n={gu['n']} 胜率{gu['hit_rate']*100:.0f}% "
                 f"CI[{gu['ci95'][0]*100:.0f},{gu['ci95'][1]*100:.0f}] {gu['verdict']}"
                 f"{_fmt_be(gu)} 已实现 ${gu.get('realized_usd')}")
    L.append("\n结论应用:仅『✅ 转正』与『❌ 剔除』触发 edge.py 权重改动(人工 review);"
             "其余一律继续测量。")
    return "\n".join(L)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    print(format_report(run_audit()))
