"""
QBTS 冠军策略陪跑(纸面测量)—— 2026-07-03 两轮策略动物园(35 套)的前两名:

  ① QQQ50 × 波动率目标   连续仓位规则 → 虚拟 $1000 净值曲线,每日结算,
     与"死拿"净值并排对照。敞口 = QQQ>50日线 ? clip(0.6/20日年化波动, 0.2, 1) : 0。
     回测:全期 +630% / 近1年 +113% / 回撤 -40%(B&H 同期 +1944%/+52%/-71%)。
  ② 5日swing × QQQ50     事件式 → 同 dip_buy 的状态机。收盘≤5日最低 且 QQQ 在
     50日线上 → $1000 虚拟买入;收盘≥5日最高 → 止盈;10 个交易日到期平仓。
     回测:72%(23/32) / 全期 +554% / 近1年 +75% / 回撤 -39%。

定位与 dip_buy 相同:**纯纸面测量,不进 edge、不进决策 prompt**,多重比较
折扣照打(35 选 2),攒够样本后用真实成绩决定去留。
持久化:scan_paper 表独立行 id='qbts_champs'(零迁移;本地文件回退);
last_date 幂等,每个交易日只推进一步,漏跑不回填。
QQQ 数据:yfinance 现拉 6mo(publish 每日一次,失败则该日跳过、状态不动)。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_DIR = Path(__file__).parent.parent / "data" / "cache"
_DIR.mkdir(parents=True, exist_ok=True)
_FILE = _DIR / "qbts_champs.json"
_ROW_ID = "qbts_champs"
_TABLE = "scan_paper"

_USD = 1000.0
_COST = 0.002
_TARGET_VOL = 0.60
_SWING_LOOKBACK = 5
_SWING_MAX_HOLD = 10


def _load() -> dict:
    from dashboard.scan_store import _supabase
    sb = _supabase()
    if sb is not None:
        try:
            rows = sb.table(_TABLE).select("data").eq("id", _ROW_ID).execute().data
            if rows and rows[0].get("data"):
                return rows[0]["data"]
        except Exception as e:
            logger.warning(f"qbts_paper: load failed, using file — {e}")
    if _FILE.exists():
        try:
            return json.loads(_FILE.read_text())
        except Exception:
            pass
    return {"volreg": None, "swing": {"open": None, "closed": []}, "last_date": None}


def _save(state: dict) -> None:
    from dashboard.scan_store import _supabase
    sb = _supabase()
    if sb is not None:
        try:
            sb.table(_TABLE).upsert({"id": _ROW_ID, "data": state}).execute()
            return
        except Exception as e:
            logger.warning(f"qbts_paper: save failed, using file — {e}")
    _FILE.write_text(json.dumps(state, ensure_ascii=False))


def _qqq_risk_on() -> "bool | None":
    """QQQ 收盘 vs 自身 50 日线;失败返回 None(该日跳过,不猜)。"""
    try:
        import yfinance as yf
        q = yf.download("QQQ", period="6mo", progress=False)["Close"].squeeze()
        if len(q) < 55:
            return None
        return bool(float(q.iloc[-1]) > float(q.rolling(50).mean().iloc[-1]))
    except Exception as e:
        logger.warning(f"qbts_paper: QQQ fetch failed — {e}")
        return None


def analyze_champs(df_d: pd.DataFrame) -> dict | None:
    """每日调用:推进两个台账一步 + 返回展示块。df_d 需含 close(大小写均可)。"""
    try:
        d = df_d.rename(columns=str.lower)
        if len(d) < 30:
            return None
        c = d["close"].astype(float)
        close = float(c.iloc[-1])
        today = str(pd.Timestamp(df_d.index[-1]).date())
        lo5 = float(c.tail(_SWING_LOOKBACK).min())
        hi5 = float(c.tail(_SWING_LOOKBACK).max())
        rets = c.pct_change()
        vol20 = float(rets.tail(20).std() * (252 ** 0.5))
        vt = max(0.20, min(1.00, _TARGET_VOL / vol20)) if vol20 > 0 else 0.50

        st = _load()
        risk_on = _qqq_risk_on()

        if st.get("last_date") != today and risk_on is not None:
            exposure = vt if risk_on else 0.0
            # ── ① 净值曲线:用昨日敞口吃今天的收益,再调到今日目标敞口 ──
            vr = st.get("volreg")
            if vr is None:
                vr = {"nav": _USD, "bh_nav": _USD, "start_date": today,
                      "prev_close": close, "exposure": exposure}
            else:
                r = close / vr["prev_close"] - 1 if vr.get("prev_close") else 0.0
                vr["nav"] = vr["nav"] * (1 + vr.get("exposure", 0.0) * r) \
                    - vr["nav"] * abs(exposure - vr.get("exposure", 0.0)) * _COST
                vr["bh_nav"] = vr["bh_nav"] * (1 + r)
                vr["prev_close"] = close
                vr["exposure"] = exposure
            st["volreg"] = vr

            # ── ② 5日swing 状态机 ──
            sw = st.get("swing") or {"open": None, "closed": []}
            pos = sw.get("open")
            if pos:
                pos["days"] = int(pos.get("days", 0)) + 1
                exit_px = reason = None
                if close >= hi5:
                    exit_px, reason = close, "破5日新高"
                elif pos["days"] >= _SWING_MAX_HOLD:
                    exit_px, reason = close, "10天到期"
                if exit_px is not None:
                    pnl = pos["shares"] * exit_px * (1 - _COST) - _USD
                    sw["closed"] = (sw.get("closed") or [])[-49:] + [{
                        "entry_date": pos["entry_date"], "entry": pos["entry"],
                        "exit_date": today, "exit": round(exit_px, 2),
                        "days": pos["days"], "reason": reason,
                        "pnl": round(pnl, 2), "pnl_pct": round(pnl / _USD, 4)}]
                    sw["open"] = None
            elif close <= lo5 and risk_on:
                shares = _USD * (1 - _COST) / close
                sw["open"] = {"entry_date": today, "entry": round(close, 2),
                              "shares": round(shares, 4), "days": 0}
            st["swing"] = sw
            st["last_date"] = today
            st["risk_on"] = risk_on
            _save(st)

        vr = st.get("volreg")
        sw = st.get("swing") or {}
        closed = sw.get("closed") or []
        n, wins = len(closed), sum(1 for t in closed if t["pnl"] > 0)
        pos = sw.get("open")
        out = {
            "risk_on": st.get("risk_on"),
            "vt_pct": round(vt, 2),
            "volreg": ({
                "nav": round(vr["nav"], 2), "bh_nav": round(vr["bh_nav"], 2),
                "start_date": vr["start_date"],
                "exposure": round(vr.get("exposure", 0.0), 2),
                "ret_pct": round(vr["nav"] / _USD - 1, 4),
                "bh_ret_pct": round(vr["bh_nav"] / _USD - 1, 4),
            } if vr else None),
            "swing": {
                "lo5": round(lo5, 2), "hi5": round(hi5, 2), "close": round(close, 2),
                "would_trigger": bool(close <= lo5),
                "open": None,
                "n_closed": n, "n_win": wins,
                "win_rate": round(wins / n, 3) if n else None,
                "realized": round(sum(t["pnl"] for t in closed), 2),
            },
        }
        if pos:
            unreal = pos["shares"] * close * (1 - _COST) - _USD
            out["swing"]["open"] = {**pos, "unreal": round(unreal, 2),
                                    "unreal_pct": round(unreal / _USD, 4),
                                    "hi5": round(hi5, 2)}
        return out
    except Exception as e:
        logger.warning(f"qbts_paper failed: {e}")
        return None
