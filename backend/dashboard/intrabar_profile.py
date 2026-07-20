"""
Intrabar Profile — 单根日线 bar 内部的成交量画像 + 签名 delta。

辅助地图(2026-07-20 用户点单,仿 TradingView editor's pick「Intrabar Profile
[Kioseff Trading]」)。POC 卡回答"过去 N 天成交都在哪个价位"(跨 bar 宏观);这个模块
回答的是**最近一根日线 bar 内部**发生了什么——普通蜡烛只给 OHLC 四个数,看不见
一天之内成交量堆在高处还是低处、买盘还是卖盘主导。用日内 1h 子 bar 重构:

  intrabar VPOC   当日成交最密集的价位(日内价值中枢)
  poc_position    VPOC 在当日区间的位置(0=贴当日低,1=贴当日高)
  CLV             收盘位置(-1=收在最低,+1=收在最高)
  net delta       签名成交量(1h bar 收>开=买量,收<开=卖量;无 tick 的标准近似)
  read            吸收 / 投降 / 派发 / 突破接受 / 均衡

核心用途(用户提出):价格跌到需求区时,判断"买盘在吸收 vs 卖盘继续投降"——
  吸收 = 低位放量下杀但收盘拉回(卖单被买盘吃掉,价格拒绝下探)→ 偏多拐点线索
  投降 = 低位放量且收在低位(卖盘主导,尚无承接)→ 下跌延续风险

这是**地图不是信号**:不进 edge、不进机械扫描打分、不驱动交易;只展示 + 喂决策
prompt 作"确认腿"参考(同 POC / NW 待遇)。delta 是 1h 收-开 符号近似,非真实
tick delta —— 当趋势线索,别当精确的主动买卖量。所有计算因果(仅用已完成子 bar)。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_N_BINS       = 24    # 日内价位分辨率(1h bar 少,bin-spread 会平滑)
_CONTEXT_DAYS = 5     # delta 趋势条回看天数
_LOW_ZONE     = 0.40  # poc_position ≤ 此 = 放量在区间下沿
_HIGH_ZONE    = 0.60  # poc_position ≥ 此 = 放量在区间上沿


def _signed(bar) -> float:
    """1h 子 bar 的 delta 符号:收>开=+1(买),收<开=-1(卖),平=0。"""
    if bar["close"] > bar["open"]:
        return 1.0
    if bar["close"] < bar["open"]:
        return -1.0
    return 0.0


def _day_delta(day: pd.DataFrame) -> tuple[float, float]:
    """(up_vol, down_vol):按每根 1h 收-开方向分桶的成交量。"""
    up = float(day.loc[day["close"] > day["open"], "volume"].sum())
    dn = float(day.loc[day["close"] < day["open"], "volume"].sum())
    return up, dn


def analyze_intrabar_profile(df_h: pd.DataFrame, live_price: float | None = None,
                             n_bins: int = _N_BINS,
                             context_days: int = _CONTEXT_DAYS) -> dict:
    """最近一根日线 bar 的日内成交量画像 + 签名 delta + 吸收/投降/派发读数。"""
    if df_h is None or len(df_h) < 8:
        return {"available": False, "rationale": "1h 数据不足,无法构建日内画像"}
    d = df_h.rename(columns=str.lower)
    if not {"open", "high", "low", "close", "volume"}.issubset(d.columns):
        return {"available": False, "rationale": "1h 数据缺 OHLCV 列"}

    dates = pd.DatetimeIndex(d.index).normalize()
    uniq  = pd.Index(dates.unique()).sort_values()
    last  = uniq[-1]
    day   = d[dates == last]
    if len(day) < 2:
        return {"available": False, "rationale": "当日 1h 子 bar 不足(<2),画像无意义"}

    lo, hi = float(day["low"].min()), float(day["high"].max())
    span   = (hi - lo) or 1e-6
    close  = float(live_price) if live_price else float(day["close"].iloc[-1])

    # 成交量 + 签名 delta 按价位分桶(每根子 bar 摊到它跨越的 bins)
    vol_at   = np.zeros(n_bins)
    delta_at = np.zeros(n_bins)
    for _, b in day.iterrows():
        v, sgn = float(b["volume"]), _signed(b)
        lo_i = int(np.clip((b["low"]  - lo) / span * n_bins, 0, n_bins - 1))
        hi_i = int(np.clip((b["high"] - lo) / span * n_bins, 0, n_bins - 1))
        nspan = hi_i - lo_i + 1
        vol_at[lo_i:hi_i + 1]   += v / nspan
        delta_at[lo_i:hi_i + 1] += sgn * v / nspan

    centers  = (np.linspace(lo, hi, n_bins + 1)[:-1] + np.linspace(lo, hi, n_bins + 1)[1:]) / 2
    poc_idx  = int(np.argmax(vol_at))
    vpoc     = float(centers[poc_idx])
    poc_pos  = (vpoc - lo) / span                       # 0=贴低, 1=贴高
    clv      = float(np.clip((close - lo) / span * 2 - 1, -1, 1))  # -1=收最低, +1=收最高

    up_vol, dn_vol = _day_delta(day)
    tot_dir   = (up_vol + dn_vol) or 1e-9
    delta_pct = (up_vol - dn_vol) / tot_dir              # -1..+1

    # ── 读数:VPOC 位置(放量在哪) × CLV(收在哪) ──────────────────
    if poc_pos <= _LOW_ZONE:
        if clv >= 0.20:
            read, stance = "吸收", "偏多"
            note_r = "低位放量下杀但收盘拉回——卖单被买盘吃掉,价格拒绝下探(偏多拐点线索)"
        elif clv <= -0.33:
            read, stance = "投降", "偏空"
            note_r = "低位放量且收在低位——卖盘主导,买盘尚未接手(下跌延续风险)"
        else:
            read, stance = "低位承接", "中性"
            note_r = "放量在区间下沿、收在中部——有人接但方向未定,等确认"
    elif poc_pos >= _HIGH_ZONE:
        if clv <= -0.20:
            read, stance = "派发", "偏空"
            note_r = "高位放量后被打回——买盘力竭,上方在派发(偏空线索)"
        elif clv >= 0.33:
            read, stance = "突破接受", "偏多"
            note_r = "高位放量且守住——市场接受更高价(偏多)"
        else:
            read, stance = "高位换手", "中性"
            note_r = "放量在区间上沿、收在中部——高位分歧,等确认"
    else:
        read, stance = "均衡", "中性"
        note_r = "放量堆在日内中枢——多空拉锯,无日内 edge"

    # delta 符号与读数背离时降级提示(如判"吸收"但 delta 仍大幅净卖)
    delta_disagree = (stance == "偏多" and delta_pct < -0.25) or \
                     (stance == "偏空" and delta_pct > 0.25)

    # ── 近 N 日 delta 趋势条(吸收在累积 or 抛压在加速)────────────
    strip = []
    for dd in uniq[-context_days:]:
        sub = d[dates == dd]
        uv, dv = _day_delta(sub)
        t = (uv + dv) or 1e-9
        strip.append({"date": str(dd.date()),
                      "delta_pct": round(float((uv - dv) / t), 3),
                      "sign": 1 if uv >= dv else -1})

    return {
        "available":     True,
        "bar_date":      str(last.date()),
        "n_subbars":     int(len(day)),
        "day_high":      round(hi, 2),
        "day_low":       round(lo, 2),
        "close":         round(close, 2),
        "intrabar_poc":  round(vpoc, 2),
        "poc_position":  round(float(poc_pos), 2),
        "clv":           round(clv, 2),
        "up_vol_pct":    round(up_vol / tot_dir, 3),
        "down_vol_pct":  round(dn_vol / tot_dir, 3),
        "net_delta_pct": round(float(delta_pct), 3),
        "read":          read,
        "stance":        stance,
        "read_note":     note_r,
        "delta_disagree": bool(delta_disagree),
        "delta_strip":   strip,
        "rationale":     (f"{last.date()} 日内({len(day)}根1h):VPOC ${vpoc:.2f}"
                          f"(位置{poc_pos:.0%}), 收盘位置CLV {clv:+.2f}, "
                          f"净delta {delta_pct:+.0%} → {read}"),
        "note":          "1h 子bar 重构日内画像;delta=收-开 符号近似(无 tick 数据,当趋势不当精确量)",
    }


if __name__ == "__main__":
    import sys, json
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from data.fetcher import load_or_fetch
    df_h, _ = load_or_fetch()
    print(json.dumps(analyze_intrabar_profile(df_h), ensure_ascii=False, indent=2))
