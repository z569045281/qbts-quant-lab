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

**预注册修订 2026-07-30(用户拍板,依据 = docs/REVIEW-2026-07.md §5/§7)—— 两项:**

(A) **判决主体从「AI 方向单」改为「方向表态 bold_call」。** 依据是可达性算术,不是
    结果好看:方向单池 n=1、速率 0.02/天 → 到 n=30 要 **1247 天(2029-12-28)**;
    表态池每个交易日 +1。两者测的是同一件事(模型看对没看对),但表态不受
    "能不能下单"的闸门污染 —— 而那道闸门在 2026-06/07 把 14 次连续看空全变成了
    观望(死区上沿 p_up≥0.58 在 36 天里 0 次触发 + 空腿四轮判死)。方向单池
    **继续记录、继续展示**,只是不再是判决主体。**这项修订放宽了什么必须写明:
    它把判决门槛从"不可达"变成"可达",没有降低 n≥30 或 Wilson 任何一项。**

(B) **多视界并行评分(1/2/3/5 日)。** 用户 2026-07-30:"我基本上持仓只拿 2 天 3 天,
    系统也只需要测这 2 到 3 天"。原先模型预测 5 日、评分 5 日、edge regime 常数按
    P(5d up) 实测 —— 全系统在测一个没人交易的视界。**不改** prompt 字段与
    _GRADE_AFTER_BARS(改=清零本就不够的样本),改为同一份表态并行评在 4 个视界上,
    并对历史记录回填。**判决线在看到更多数据之前定死**(见 `_HORIZON_RULE`)。
    ⚠️ 2026-07-30 回填读数(每视界 n=9~14)**不得作为任何视界的晋升依据** ——
    当天一次性试了 5 个视界,挑最好的看着漂亮是 n=14 下的随机常态。

**2026-07-30 修的一个真 bug(不是口径变更)**:`daily_call` 池原本用
`res.correct if not None else res.shadow_correct` 合并 —— 但 2026-07-22 起 HOLD 记录
的 `correct` 变成了「漏判判读」而非方向表态,于是 29 条里 **28 条读的是漏判判读**,
那行"每日方向表态命中 48%"**根本没在测方向**,只是 HOLD 漏判率换了个标签。
journal.py 的 `_lean` 当时已按 action 分流修好,audit.py 这份读者被漏掉 ——
与 2026-07-22 校准混代记录同一个病根(改字段语义必须 grep 全部读者)。

只读不写(唯一例外:`backfill_horizons` 给老记录补新字段,幂等,不改任何已有值);
工具产出报告(stdout + cache/audit_report.json),权重改动仍走人工 code review
(edge.py 常量),证据在手再动刀。

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

# ── 多视界预注册判决线(2026-07-30 写死,在积累数据之前定;审判日不得改)──────
# 关键设计:**不跟 0.5 比,跟「常喊同一边」的基线比。** 2026-06/07 单边下跌里
# 83% 的 5 日窗口是跌的 —— 一个无脑常喊 down 的模型能拿 83% 命中率而技巧为零。
# 判活条件(三条全过):
#   ① n ≥ _N_MIN(30)
#   ② Wilson95% 下界 > 该视界的**同期基线命中率**(= 常喊多数边的命中率),不是 > 0.5
#   ③ 该视界的技巧值(命中 − 基线)在**四个视界里为正**且不是唯一为正的孤例
#      —— 单视界孤高 = 多重比较产物(4 个视界任选其一,n=30 下假阳性不低)
# 判死:Wilson95% 上界 < 基线 → 该视界表态无信息,报告明示。
# 视界间只做**展示排序**,不自动改任何权重/prompt;换 prompt 视界需用户单独拍板。
_HORIZON_RULE = ("判活须三条全过:n≥30 · Wilson下界>同期基线(非0.5) · "
                 "技巧值为正且非四视界中的孤例(防多重比较)")


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


def _horizon_audit(recs: list[dict], df_d) -> dict:
    """方向表态 × 1/2/3/5 日视界(新判决主体)。基线 = 常喊多数边的命中率。"""
    from dashboard.journal import _HORIZONS

    out: dict = {"rule": _HORIZON_RULE, "by_horizon": {}}
    for h in _HORIZONS:
        key = f"{h}d"
        # 读记录**顶层** horizons(不是 result)—— 这样 2 日表态不必等 5 日评分闸门,
        # 短视界池比长视界池先长(journal.backfill_horizons 每次审判前补齐)。
        rows = [(r.get("bold_call_5d"), (r.get("horizons") or {}).get("fwd_ret", {}).get(key))
                for r in recs]
        rows = [(c, f) for c, f in rows if c in ("up", "down") and f is not None]
        # 基线:该视界所有可评日里,多数边的占比(= 无脑常喊那一边的命中率)。
        # 用**全部**有 fwd 的记录算,不只有表态的那些 —— 基线是市场属性,不是模型属性。
        allf = [f for r in recs
                for f in [(r.get("horizons") or {}).get("fwd_ret", {}).get(key)]
                if f is not None]
        if not rows or not allf:
            continue
        down_share = sum(1 for f in allf if f < 0) / len(allf)
        base = max(down_share, 1 - down_share)
        hits = sum(1 for c, f in rows if (c == "up") == (f > 0))
        v = _verdict(hits, len(rows), breakeven=base)
        v["baseline"] = round(base, 3)
        v["baseline_side"] = "down" if down_share >= 0.5 else "up"
        v["skill_pp"] = round((hits / len(rows) - base) * 100, 1)
        v["n_baseline_days"] = len(allf)
        v["mean_fwd_pct"] = round(sum(f for _, f in rows) / len(rows) * 100, 2)
        out["by_horizon"][key] = v
    # 孤例检查(判活条件③):技巧值为正的视界数
    pos = [k for k, v in out["by_horizon"].items() if (v.get("skill_pp") or 0) > 0]
    out["n_positive_skill"] = len(pos)
    out["positive_horizons"] = pos
    out["multiple_comparison_warn"] = len(pos) == 1
    return out


def _p_up_diagnostic(recs: list[dict]) -> dict:
    """p_up 反预测立案(用户 2026-07-30 拍板,REVIEW-2026-07 §7 P1)。

    **预注册判决线(在数据攒够之前定死)**:当 n ≥ 30 时,若 corr(p_up, fwd5) 的
    95% 置信区间**整段位于 0 以下**(即显著为负)→ 建议把 `p_up` 从决策 prompt
    **摘除**,不是调权重。理由:v1(24 条命中 24%、崩盘段 12/13 天喊 BUY)与 v2
    (2026-07-30 实测 corr −0.406,n=29)**两代同向**;第三次调参没有先验支持。
    corr 的 CI 用 Fisher z 变换(小样本下比 bootstrap 稳,且可手算复现)。
    """
    pairs = [(float(r["p_up_5d"]), float(r["result"]["fwd5_ret"]))
             for r in recs
             if r.get("p_up_5d") is not None
             and (r.get("result") or {}).get("fwd5_ret") is not None]
    if len(pairs) < 4:
        return {"n": len(pairs), "verdict": "样本不足·继续测量"}
    xs = [a for a, _ in pairs]; ys = [b for _, b in pairs]
    n = len(pairs)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    sy = math.sqrt(sum((b - my) ** 2 for b in ys))
    r_ = sum((a - mx) * (b - my) for a, b in pairs) / (sx * sy) if sx and sy else 0.0
    r_ = max(-0.999999, min(0.999999, r_))
    z = 0.5 * math.log((1 + r_) / (1 - r_))
    se = 1 / math.sqrt(n - 3) if n > 3 else float("inf")
    lo, hi = (math.tanh(z - _Z * se), math.tanh(z + _Z * se))
    if n < _N_MIN:
        verdict = "样本不足·继续测量(线已预注册)"
    elif hi < 0:
        verdict = "❌ 显著反预测 → 建议把 p_up 从决策 prompt 摘除(非调权重)"
    elif lo > 0:
        verdict = "✅ 正相关·保留"
    else:
        verdict = "中性·继续测量"
    return {"n": n, "corr": round(r_, 3), "ci95": [round(lo, 3), round(hi, 3)],
            "verdict": verdict,
            "rule": "n≥30 且 corr 的 95%CI 整段 <0 → 摘除 p_up(v1/v2 两代同向,不再调参)"}


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
        # 老记录补多视界字段(2026-07-30 新增;幂等,不改任何已有值)—— 必须在
        # load_recent 之前,否则本次报告读到的还是没有 fwd_ret_by_h 的旧快照。
        try:
            n_bf = jr.backfill_horizons(df_d)
            if n_bf:
                report["backfilled_horizon_records"] = n_bf
        except Exception as e:
            report["backfill_error"] = str(e)[:120]
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
            "paper_avoided": j.get("avoided"),
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
        # ⚠️ 2026-07-30 修 bug:原实现 `correct if not None else shadow_correct`,
        # 而 07-22 起 HOLD 的 correct = 漏判判读(不是方向表态)→ 29 条里 28 条
        # 读的是漏判率,这一行根本没在测方向。改为**按 action 分流**,与
        # journal.py `_lean`(07-22 已修好的那份)逐字同口径。
        lean = []
        for r in recs:
            res = r.get("result") or {}
            if r.get("action") in ("LONG_QBTX", "SHORT_QBTZ"):
                v = res.get("correct")
            else:                                    # HOLD:方向只看影子表态
                v = res.get("shadow_correct")
            if v is not None:
                lean.append(bool(v))
        p_all = [float(r["p_up_5d"]) for r in recs if r.get("p_up_5d") is not None]
        fence = sum(1 for p in p_all if 0.45 <= p <= 0.55)
        report["sections"]["decision_journal"]["daily_call"] = {
            **_verdict(sum(lean), len(lean)),
            "p_up_fence_pct": round(fence / len(p_all), 3) if p_all else None,
            "basis": "方向单用 correct,HOLD 用 shadow_correct(漏判判读不冒充方向分)",
        }
        # ── 判决主体:方向表态 × 多视界(预注册修订 2026-07-30 A+B)────────────
        report["sections"]["decision_journal"]["horizons"] = _horizon_audit(recs, df_d)
        report["sections"]["decision_journal"]["p_up_diagnostic"] = _p_up_diagnostic(recs)
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
        # ── ②★ 新判决主体:方向表态 × 多视界(预注册修订 2026-07-30)────────
        hz = dj.get("horizons") or {}
        by = hz.get("by_horizon") or {}
        if by:
            L.append(f"\n②★ 【判决主体】方向表态 × 视界 — {hz.get('rule','')}")
            L.append(f"   {'视界':<6}{'n':>4}  {'命中':>6} {'Wilson95%':<12}"
                     f"{'基线':>6}{'技巧':>8}  判决")
            for k, d in by.items():
                star = " ←你的持有期" if k in ("2d", "3d") else ""
                L.append(f"   {k:<6}{d['n']:>4}  {d['hit_rate']*100:>5.0f}% "
                         f"[{d['ci95'][0]*100:>3.0f},{d['ci95'][1]*100:>3.0f}]  "
                         f"{d['baseline']*100:>5.0f}%{d['skill_pp']:>+7.1f}pp  "
                         f"{d['verdict']}{star}")
            L.append(f"   基线 = 该视界无脑常喊「{next(iter(by.values())).get('baseline_side','?')}」"
                     f"的命中率;技巧 = 命中 − 基线。**跟基线比,不跟 50% 比。**")
            if hz.get("multiple_comparison_warn"):
                L.append(f"   ⚠️ 只有 {hz.get('positive_horizons')} 一个视界技巧为正 = "
                         f"多重比较高危,按预注册条件③**不得晋升**")
        pu = dj.get("p_up_diagnostic") or {}
        if pu.get("corr") is not None:
            L.append(f"\n②☠ p_up 反预测立案 — corr(p_up, fwd5)={pu['corr']:+.3f} "
                     f"CI[{pu['ci95'][0]:+.2f},{pu['ci95'][1]:+.2f}] n={pu['n']} → {pu['verdict']}")
            L.append(f"   线(预注册): {pu.get('rule','')}")
        av = (dj.get("paper_avoided") or {})
        if av.get("n_hold_days"):
            L.append(f"\n②$ 规避回撤(观望 {av['n_hold_days']} 天的 2× 反事实)— "
                     f"若那些天满仓 QBTX: {av['long_2x_pct']:+.1f}%"
                     f"  (对照 2× 空 {av['short_2x_pct']:+.1f}%,空腿四轮判死,不构成建议)")
            L.append(f"   口径: {av.get('basis','')}")
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
