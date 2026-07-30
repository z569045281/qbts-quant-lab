"""
🌡️ 超买 / 超卖状态板 —— 把散落各处的振荡器读数,收成一句人话。

**为什么以前没有这张卡**(2026-07-30 用户问"为什么不显示当前的超买还是超卖"):
读数一直都在算,但从来没有一个地方回答那句话本身 ——

    日线 WaveTrend   `wavetrend.py` 算了,但只有 **15m** 那一份进了 UI,
                     还埋在 SMC playbook 清单第 ⑤ 项里
    特调 快/慢%R     `tiaojiu.py` 算了,进了「今天在等什么」——但框架是
                     "距触发多远",不是"现在什么状态"
    RSI2             同上
    RSI14            `strategies.py` 里给 VIX contrarian 用,决策页从不打印
    NW 包络位置       `nadaraya_watson.py` 算了,只画成 60 日小图上的带子,无文字读数

设计上当初只保留了**扳机**、省掉了**状态**,是有档案依据的([mining.md](../../mining.md)):
「全部经典指标当独立系统」9 套在场胜率 47–54%(硬币)全部判死;活下来的只有**具体的
深度超卖扳机**(RSI2<10 且站上 200 日线 n=40 后5天 +9.2%/胜率 60%;特调 %R +17.4%)。
所以不给通用超买超卖表,是为了不诱发"RSI 30 = 该买了"那种已判死的推理。

但代价就是用户现在的感受:**没人回答"现在贵还是便宜"**。这张卡补的是那一句 ——

┌ 三条铁律,别让它长成信号 ────────────────────────────────────────────┐
│ ① **零决策权**:不进 `edge`、不进 `score`、不驱动 playbook、不发 ntfy。 │
│    与 POC / Intrabar 同待遇 —— 「地图非信号」。                        │
│ ② **不发明复合分数**。只并排陈列各振荡器**自己的**读数与**自己的**阈值; │
│    一个合成的 0–100「超卖分」看起来就是信号,而它没有任何前向验证。     │
│ ③ **单一数据源**。RSI2 / NW / 区间位置都从快照里已算好的字段读回来,     │
│    绝不自己再算一遍 —— 同一个数在两张卡上显示成两个值是本仓库的老病    │
│    (见 docs/LESSONS.md cross-source 那条)。                          │
└──────────────────────────────────────────────────────────────────────┘

轴向统一:每行的 `pos` ∈ [0,1] 都是「便宜 → 贵」,0 = 该指标量程里最超卖那一端。
各行的原生数字与原生阈值照原样给出,不做归一化篡改。
"""

from __future__ import annotations

import pandas as pd

try:
    from dashboard.wavetrend import analyze_wavetrend
    from dashboard.waiting_for import _rsi          # 复用同一个 RSI 实现
    from dashboard.tiaojiu import compute_signals
except ImportError:  # allow running as a loose module
    from wavetrend import analyze_wavetrend
    from waiting_for import _rsi
    from tiaojiu import compute_signals


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _row(key, name, value_cn, pos, band, band_cn, own_threshold, source,
         marks=None, fired=None) -> dict:
    return {"key": key, "name": name, "value_cn": value_cn,
            "pos": round(_clamp01(pos), 4), "band": band, "band_cn": band_cn,
            "threshold_cn": own_threshold, "source": source,
            "marks": marks or [], "fired": fired}


# band 一律用「该指标自己的」阈值判,不用统一的 pos 分档 —— 各振荡器的量程语义不同,
# 拿一把尺子量所有人反而是在编造精度。
def _band_pctr(v: float) -> tuple[str, str]:
    """特调用的 %R(−100..0),水位 −80 / −50 / −20 是原指标自己的三条线。"""
    if v < -80:  return "os", "超卖"
    if v < -50:  return "cool", "偏冷"
    if v < -20:  return "warm", "偏热"
    return "ob", "超买"


def _band_wt(v: float) -> tuple[str, str]:
    """LazyBear WaveTrend,超买/超卖线 ±53(wavetrend.py 的默认参数)。"""
    if v <= -53: return "os", "超卖"
    if v >= 53:  return "ob", "超买"
    if v <= -25: return "cool", "偏冷"
    if v >= 25:  return "warm", "偏热"
    return "mid", "中性"


def _band_rsi(v: float, lo: float, hi: float) -> tuple[str, str]:
    if v < lo:        return "os", "超卖"
    if v > hi:        return "ob", "超买"
    if v < 45:        return "cool", "偏冷"
    if v > 55:        return "warm", "偏热"
    return "mid", "中性"


def build_oscillator_board(df_d: pd.DataFrame, snapshot: dict) -> dict | None:
    """并排陈列各振荡器读数。纯函数,任何一行取不到就跳过那一行,失败返回 None。"""
    try:
        d = df_d.rename(columns=str.lower)
        rows: list[dict] = []

        # ① 特调 快%R / 慢%R —— 十轮最强的那条腿的原料
        tj = ((snapshot.get("champs") or {}).get("today") or {}).get("tj_sig")
        if not tj:                                  # 快照里没有(本地单跑)→ 现算
            tj = compute_signals(d) or {}
        fast, slow = tj.get("fast"), tj.get("slow")
        if fast is not None:
            b, bcn = _band_pctr(float(fast))
            px = tj.get("buy_trigger_px")
            rows.append(_row(
                "tj_fast", "特调 快%R(22)", f"{fast:.1f}",
                (float(fast) + 100) / 100, b, bcn,
                "< −80 进狙击区,再上穿 −80 才算触发(第二十五轮:必须收盘确认)",
                "tiaojiu.py", marks=[{"at": 0.20, "label": "−80"}],
                fired=bool(tj.get("buy_base"))))
            if slow is not None:
                b2, bcn2 = _band_pctr(float(slow))
                rows.append(_row(
                    "tj_slow", "特调 慢%R(112)", f"{slow:.1f}",
                    (float(slow) + 100) / 100, b2, bcn2,
                    "抄底腿要求 < −50 作确认", "tiaojiu.py",
                    marks=[{"at": 0.50, "label": "−50"}]))
            if px and fast is not None and float(fast) < -80:
                rows[-1 if slow is None else -2]["hint_cn"] = f"收盘 ≥ ${px:.2f} 即上穿触发"

        # ② 日线 WaveTrend —— 以前只有 15m 那份露过面
        wt = analyze_wavetrend(d)
        if wt:
            b, bcn = _band_wt(wt["wt2"])
            rows.append(_row(
                "wt_daily", "WaveTrend(日线)", f"wt1 {wt['wt1']} / wt2 {wt['wt2']}",
                (wt["wt2"] + 100) / 200, b, bcn,
                "超卖 ≤ −53 / 超买 ≥ +53;绿点 = 在超卖带里 wt1 上穿 wt2",
                "wavetrend.py",
                marks=[{"at": 0.235, "label": "−53"}, {"at": 0.765, "label": "+53"}],
                fired=bool(wt.get("green_dot"))))

        # ③ RSI2 —— 唯一在册的经典指标腿(其余全判死)
        rsi2 = _rsi(d["close"].astype(float), 2)
        if rsi2 is not None:
            b, bcn = _band_rsi(rsi2, 10, 90)
            rows.append(_row(
                "rsi2", "RSI(2)", f"{rsi2:.1f}", rsi2 / 100, b, bcn,
                "扳机 < 10 且 站上 200 日线(n=40 后5天 +9.2%/胜率60%)",
                "waiting_for.py 同一实现", marks=[{"at": 0.10, "label": "10"}]))

        # ④ RSI14 —— 只作背景刻度,单独用已判死
        rsi14 = _rsi(d["close"].astype(float), 14)
        if rsi14 is not None:
            b, bcn = _band_rsi(rsi14, 30, 70)
            rows.append(_row(
                "rsi14", "RSI(14)", f"{rsi14:.1f}", rsi14 / 100, b, bcn,
                "教科书 30/70;单独用已判死(9 套经典指标在场胜率 47–54%)",
                "本卡现算", marks=[{"at": 0.30, "label": "30"}, {"at": 0.70, "label": "70"}]))

        # ⑤ NW 包络位置 —— 从快照读回,不重算(同一个数不许两处不一样)
        nw = snapshot.get("nw_envelope") or {}
        if nw.get("active") and nw.get("position") is not None:
            p = float(nw["position"])
            b, bcn = (("os", "超卖") if p <= 0.10 else ("cool", "偏冷") if p <= 0.35
                      else ("ob", "超买") if p >= 0.90 else ("warm", "偏热") if p >= 0.65
                      else ("mid", "中性"))
            rows.append(_row(
                "nw", "NW 包络位置", f"{p * 100:.0f}%(下轨 0 / 上轨 100)",
                p, b, bcn,
                f"底部 10% 买入线 ${nw.get('buy_line')} / 顶部 10% 卖出线 ${nw.get('sell_line')}",
                "nw_envelope 快照字段",
                marks=[{"at": 0.10, "label": "买入线"}, {"at": 0.90, "label": "卖出线"}]))

        # ⑥ SMC 区间位置 —— 同样从快照读回(SMC 卡上就是这个数)
        smc = snapshot.get("smc") or {}
        if smc.get("range_position") is not None:
            p = float(smc["range_position"])
            b, bcn = (("cool", "折价区") if p < 0.4 else
                      ("warm", "溢价区") if p > 0.6 else ("mid", "均衡区"))
            rng = smc.get("range") or {}
            rows.append(_row(
                "smc_range", "SMC 区间位置", f"{p * 100:.0f}%",
                p, b, bcn,
                f"dealing range ${rng.get('low')}–${rng.get('high')};< 40% 折价 / > 60% 溢价",
                "smc 快照字段(与 SMC 卡同源)", marks=[{"at": 0.40, "label": "40%"},
                                                     {"at": 0.60, "label": "60%"}]))

        if not rows:
            return None

        # ── 汇总成一句人话。刻意**不给合成分数** ──────────────────────
        n_os   = sum(1 for r in rows if r["band"] == "os")
        n_cool = sum(1 for r in rows if r["band"] == "cool")
        n_ob   = sum(1 for r in rows if r["band"] == "ob")
        n_warm = sum(1 for r in rows if r["band"] == "warm")
        cold_side, hot_side = n_os + n_cool, n_ob + n_warm
        if n_os >= 2:      state, state_cn = "cold", "深度偏冷"
        elif cold_side > hot_side: state, state_cn = "cool", "偏冷"
        elif n_ob >= 2:    state, state_cn = "hot", "深度偏热"
        elif hot_side > cold_side: state, state_cn = "warm", "偏热"
        else:              state, state_cn = "mid", "中性"

        # 已触发的**在册**扳机 —— 状态归状态,扳机归扳机,别让人把前者当后者
        fired = [r["name"] for r in rows if r.get("fired")]
        extreme = min(rows, key=lambda r: min(r["pos"], 1 - r["pos"]))

        summary = (f"{len(rows)} 项读数:{n_os} 项超卖 / {n_cool} 项偏冷 / "
                   f"{n_warm} 项偏热 / {n_ob} 项超买。最极端的是 "
                   f"{extreme['name']} = {extreme['value_cn']}({extreme['band_cn']})。")
        caveat = ("在册扳机已触发:" + "、".join(fired) + "。") if fired else \
                 "没有任何在册扳机触发 —— 偏冷不等于该买。"

        return {
            "as_of": str(d.index[-1].date()) if len(d) else None,
            "state": state, "state_cn": state_cn,
            "rows": rows, "summary_cn": summary, "caveat_cn": caveat,
            "n_os": n_os, "n_cool": n_cool, "n_warm": n_warm, "n_ob": n_ob,
            "fired": fired,
            "discipline_cn": (
                "零决策权:不进 edge / 不进打分 / 不驱动 playbook / 不发推送 —— 和成交量画像、"
                "Intrabar 一样是「地图不是信号」。通用超买超卖当独立系统已判死"
                "(9 套经典指标在场胜率 47–54%,等于抛硬币);活着的只有具体的深度超卖扳机。"
                "这张卡只回答「现在贵还是便宜」,不回答「该不该买」。"),
        }
    except Exception:
        return None


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from data.fetcher import load_or_fetch
    from dashboard.nadaraya_watson import analyze_nw_envelope

    _, df_d = load_or_fetch()
    snap = {"nw_envelope": analyze_nw_envelope(df_d.rename(columns=str.lower))}
    print(json.dumps(build_oscillator_board(df_d, snap),
                     ensure_ascii=False, indent=2, default=str))
