"""
SpaceX 决策台账(2026-09-02,用户点单「1+2」)。

## 为什么有这个模块

用户问「隔壁那个 spacex,战绩如何?」—— **答不出来**。`spacex_state` 表从
2026-07-13 上线起就只有一行 `id='current'`,每天被整块覆盖;`spacex.py` 590 行
里没有任何写台账的代码;`decision_journal` 是 QBTS 专用的。跑了 50 天,
**零条历史记录**,连「它是不是天天都说 HOLD」都无法回答。

一台不记账的决策机器 = 一台永远无法被证伪的决策机器。QBTS 那边有台账 + 5 天
打分 + 8/15 审判,SpaceX 这边是纯输出。这个模块把缺的那半补上。

## 存哪儿(为什么不建新表)

复用 **`spacex_state` 表**,一条决策一行 `id='j:YYYY-MM-DD'`(表结构就是
`id text pk / data jsonb / updated_at`,装得下)。前端读 `id='current'`,
不受影响。**故意不建新表** —— 仓里已经有一个 `sql/spacex_migration.sql`
等着用户去跑(见 docs/SUPABASE.md),再加一个迁移就是再加一个「代码上线了
但库没建好」的哑火窗口。没有 Supabase 凭据时退回本地 JSONL,同 journal.py。

## 评分口径(与主台账 journal.py 对齐,不另立标准)

  BUY    : 目标先到=win / 止损先到=loss / 都没到看第 5 个交易日收益 >0=win
  REDUCE : 镜像(跌了算对)
  HOLD   : **不计入准确率**,只记 5 日收益;|收益| ≥ 3% 标记 miss(漏判),
           与 audit.py 2026-07-13 预注册的 `_HOLD_MISS_PCT` 同一条线。

## 预注册判决线(写在前面,免得事后挑口径)

  · 样本 < 20 条**已评分的方向性决策**(BUY/REDUCE)→ 一律报 UNPROVEN,不给结论。
  · 达到 20 条后:方向准确率 Wilson 95% 下界 > 50% 才算「有 edge」。
  · HOLD 漏判率单独报,不进准确率 —— 它衡量的是「该说话时闭嘴」,是另一回事。

**这是台账,不是信号。** 它不产生任何买卖建议,不碰四条铁律。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from dashboard.db import supabase as _supabase

logger = logging.getLogger(__name__)

_TABLE = "spacex_state"
_PREFIX = "j:"                     # id='j:YYYY-MM-DD',与 id='current' 井水不犯河水
_FILE = Path(__file__).parent.parent / "data" / "cache" / "spacex_journal.jsonl"
_FILE.parent.mkdir(parents=True, exist_ok=True)

_GRADE_AFTER_BARS = 5              # 同 journal.py
_HOLD_MISS_PCT = 0.03              # 同 audit.py 预注册线
_MIN_N = 20                        # 预注册:少于这个数不给结论


# ── 存取 ─────────────────────────────────────────────────────────────────────

def _load() -> list[dict]:
    sb = _supabase()
    if sb is not None:
        try:
            rows = (sb.table(_TABLE).select("id,data")
                    .like("id", f"{_PREFIX}%").execute().data)
            return sorted((r["data"] for r in rows if r.get("data")),
                          key=lambda r: r.get("date", ""))
        except Exception as e:
            logger.warning("spacex journal: Supabase load failed, using file — %s", e)
    if not _FILE.exists():
        return []
    out = []
    for line in _FILE.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return sorted(out, key=lambda r: r.get("date", ""))


def _save(records: list[dict]) -> None:
    sb = _supabase()
    if sb is not None:
        try:
            if records:
                sb.table(_TABLE).upsert(
                    [{"id": _PREFIX + r["date"], "data": r} for r in records]
                ).execute()
            return
        except Exception as e:
            logger.warning("spacex journal: Supabase save failed, using file — %s", e)
    tmp = _FILE.with_suffix(".tmp")
    tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n")
    tmp.replace(_FILE)


# ── 记录 ─────────────────────────────────────────────────────────────────────

def record(payload: dict) -> dict | None:
    """每次 publish 调一次。同日重复 publish → 覆盖当天那条(以最后一次为准)。

    决策为 None(无 key / DeepSeek 失败)时**不记** —— 记一条空决策会污染分母。
    """
    dec = (payload or {}).get("decision")
    data = (payload or {}).get("data") or {}
    if not dec or not dec.get("action"):
        return None
    day = data.get("as_of") or payload.get("generated_at", "")[:10]
    price = data.get("price")
    if not day or not isinstance(price, (int, float)):
        return None

    rec = {
        "date": str(day)[:10],
        "price": float(price),
        "action": str(dec.get("action")).upper(),
        "conviction": dec.get("conviction"),
        "entry": dec.get("entry"), "stop": dec.get("stop"), "target": dec.get("target"),
        "summary": dec.get("summary"), "model": dec.get("model"),
        # 记下当时喂进去的关键前瞻量,以后才能回答「IV 高的时候它是不是更准」
        "iv_near": ((payload.get("options") or {}).get("term") or [{}])[0].get("atm_iv"),
        "iv_degraded": (payload.get("options") or {}).get("iv_degraded"),
        "status": "pending", "result": None,
    }
    recs = [r for r in _load() if r.get("date") != rec["date"]] + [rec]
    _save(sorted(recs, key=lambda r: r["date"]))
    return rec


# ── 评分 ─────────────────────────────────────────────────────────────────────

def grade_pending(df_daily: pd.DataFrame) -> list[dict]:
    """走决策日之后的日线给 pending 打分。df_daily 需含 OHLC(大小写均可)。"""
    recs = _load()
    if not recs:
        return []
    try:
        d = df_daily.rename(columns=str.lower)
        closes, highs, lows = d["close"], d["high"], d["low"]
        idx = [str(pd.Timestamp(x).date()) for x in d.index]
    except Exception as e:
        logger.warning("spacex grade: bad frame — %s", e)
        return []

    graded = []
    for r in recs:
        if r.get("status") != "pending":
            continue
        try:
            i = idx.index(r["date"])
        except ValueError:
            continue                                   # 决策日还没有对应 bar
        after = slice(i + 1, i + 1 + _GRADE_AFTER_BARS)
        fwd_c, fwd_h, fwd_l = closes[after], highs[after], lows[after]
        if len(fwd_c) < _GRADE_AFTER_BARS:
            continue                                   # 还没走满 5 根,继续 pending
        p0 = r["price"]
        ret5 = float(fwd_c.iloc[-1]) / p0 - 1
        act = r["action"]

        if act == "HOLD":
            # 不进准确率:HOLD 没有方向,评它的对错只会把分母做大做假。
            r["result"] = {"outcome": "hold", "ret5": round(ret5, 4),
                           "miss": abs(ret5) >= _HOLD_MISS_PCT, "correct": None}
        else:
            tgt, stp = r.get("target"), r.get("stop")
            hit = None
            if isinstance(tgt, (int, float)) and isinstance(stp, (int, float)):
                for k in range(len(fwd_c)):
                    hi, lo = float(fwd_h.iloc[k]), float(fwd_l.iloc[k])
                    up = hi >= tgt if act == "BUY" else lo <= tgt
                    dn = lo <= stp if act == "BUY" else hi >= stp
                    # 同一根 bar 内两边都触及 → 判 loss。日线看不出先后,
                    # 假设有利的一边先到是回测里最经典的自欺。
                    if up and dn:
                        hit = False; break
                    if up:
                        hit = True; break
                    if dn:
                        hit = False; break
            if hit is None:
                hit = ret5 > 0 if act == "BUY" else ret5 < 0
            r["result"] = {"outcome": "win" if hit else "loss",
                           "ret5": round(ret5, 4), "correct": bool(hit)}
        r["status"] = "graded"
        graded.append(r)

    if graded:
        _save(recs)
    return graded


# ── 战绩 ─────────────────────────────────────────────────────────────────────

def _wilson_lo(k: int, n: int, z: float = 1.96) -> float | None:
    """Wilson 95% 下界。小样本下比裸胜率诚实得多。"""
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return round((c - m) / d, 4)


def scorecard(n_recent: int = 15) -> dict:
    """给 /spacex 页与推送用的战绩摘要。样本不够就诚实说 UNPROVEN。"""
    recs = _load()
    graded = [r for r in recs if r.get("status") == "graded" and r.get("result")]
    dirs = [r for r in graded if r["action"] in ("BUY", "REDUCE")]
    holds = [r for r in graded if r["action"] == "HOLD"]
    wins = sum(1 for r in dirs if r["result"].get("correct"))
    lo = _wilson_lo(wins, len(dirs))
    counts = {}
    for r in recs:
        counts[r["action"]] = counts.get(r["action"], 0) + 1

    return {
        "n_total": len(recs),
        "n_graded": len(graded),
        "n_pending": sum(1 for r in recs if r.get("status") == "pending"),
        "first_date": recs[0]["date"] if recs else None,
        "action_counts": counts,
        "n_directional": len(dirs),
        "wins": wins,
        "win_rate": round(wins / len(dirs), 4) if dirs else None,
        "wilson_lo": lo,
        "avg_ret5": (round(sum(r["result"]["ret5"] for r in dirs) / len(dirs), 4)
                     if dirs else None),
        "hold_n": len(holds),
        "hold_miss_rate": (round(sum(1 for r in holds if r["result"].get("miss")) / len(holds), 4)
                           if holds else None),
        # 预注册线:方向性样本 <20 一律 UNPROVEN,不给结论
        "verdict": ("UNPROVEN(方向性样本 %d/%d)" % (len(dirs), _MIN_N) if len(dirs) < _MIN_N
                    else ("有 edge(Wilson 下界 %.0f%% > 50%%)" % (lo * 100) if lo and lo > 0.5
                          else "无 edge(Wilson 下界 %.0f%% ≤ 50%%)" % ((lo or 0) * 100))),
        "recent": [{"date": r["date"], "action": r["action"], "price": r["price"],
                    "status": r.get("status"),
                    "ret5": (r.get("result") or {}).get("ret5"),
                    "correct": (r.get("result") or {}).get("correct")}
                   for r in recs[-n_recent:]][::-1],
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import warnings, sys
    warnings.filterwarnings("ignore")
    sys.path.insert(0, str(Path(__file__).parent.parent))

    # ── 自测:用假数据走一遍全流程,不碰线上库 ──────────────────────────
    import numpy as np
    _MEM: list[dict] = []
    _load_real, _save_real = _load, _save
    globals()["_load"] = lambda: sorted(_MEM, key=lambda r: r["date"])
    globals()["_save"] = lambda rs: (_MEM.clear(), _MEM.extend(rs))

    days = pd.bdate_range("2026-08-03", periods=12)
    px = pd.Series(np.linspace(100, 118, 12), index=days)
    df = pd.DataFrame({"close": px, "high": px * 1.03, "low": px * 0.97})
    d0 = str(days[0].date())

    record({"data": {"as_of": d0, "price": 100.0},
            "decision": {"action": "BUY", "conviction": 6, "target": 130, "stop": 90,
                         "summary": "t"}, "options": {"term": [{"atm_iv": 0.5}]}})
    g = grade_pending(df)
    assert len(g) == 1 and g[0]["result"]["outcome"] == "win", g   # 5日 +7.4%,目标未触及
    assert g[0]["result"]["correct"] is True
    assert not grade_pending(df), "已评分的不该被重复评分"

    # HOLD 不进准确率,但 |5日收益| ≥3% 记 miss
    record({"data": {"as_of": str(days[1].date()), "price": float(px.iloc[1])},
            "decision": {"action": "HOLD", "summary": "t"}})
    grade_pending(df)
    h = [r for r in _MEM if r["action"] == "HOLD"][0]
    assert h["result"]["correct"] is None and h["result"]["miss"] is True, h

    # 同日重复 publish 只留最后一条
    n0 = len(_MEM)
    record({"data": {"as_of": d0, "price": 100.0},
            "decision": {"action": "REDUCE", "summary": "t2"}})
    assert len(_MEM) == n0 and [r for r in _MEM if r["date"] == d0][0]["action"] == "REDUCE"

    # 决策为 None 不记账(否则污染分母)
    assert record({"data": {"as_of": "2026-08-25", "price": 1.0}, "decision": None}) is None

    sc = scorecard()
    assert sc["n_directional"] < _MIN_N and sc["verdict"].startswith("UNPROVEN"), sc
    print("✅ 自测通过")
    print(json.dumps(sc, ensure_ascii=False, indent=1))

    globals()["_load"], globals()["_save"] = _load_real, _save_real
