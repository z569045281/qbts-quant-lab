"""
QBTS 深坑抄底信号 —— 纯测量的纸面台账(measurement-only)。

规则:收盘 ≤ 20日最高 × 0.80 → $1000 虚拟买入(收盘价,0.2%/边);
     收盘 ≥ 触发日20日最高 × 0.95 → 止盈;15 个交易日未达 → 到期平仓。

出身:2026-07-03 策略动物园(18 套)里的胜率冠军 — 64%@25 笔、全期 +1914%/
回撤 -49%(vs 买持 +1944%/-71%),但近一年仅 +32%、且有 18 选 1 的多重比较
嫌疑。与 DCA 哲学独立得出的「-20%+ 恐慌才值得动用储备」同门槛互为旁证。
定位:**纸面测量,不进 edge、不进决策 prompt**;攒 ~30 笔后用真实命中率
决定去留(与 scan paper 同一哲学)。

持久化:scan_paper 表的独立行 id='qbts_dip20'(零迁移;本地文件回退)。
幂等:每个交易日只推进一步(last_date 防重),漏跑的日子不回填。
已知粗糙点:每日 publish(09:00 ET)用的是当日「部分」日线 bar 的现价当收盘,
与 scan paper 的处理一致 — 测量工具够用,不为此引入盘后二次跑。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_DIR = Path(__file__).parent.parent / "data" / "cache"
_DIR.mkdir(parents=True, exist_ok=True)
_FILE = _DIR / "qbts_dip20.json"
_ROW_ID = "qbts_dip20"
_TABLE = "scan_paper"

_USD = 1000.0
_COST = 0.002     # ~0.2%/side,与 scan paper 一致
_TRIG = 0.80      # 触发:收盘 ≤ 20日高 × 0.80(跌 20%+)
_TP = 0.95        # 止盈:收盘 ≥ 触发日 20日高 × 0.95
_MAX_HOLD = 15    # 最长持有(交易日),到期平仓不死扛


def _load() -> dict:
    from dashboard.scan_store import _supabase
    sb = _supabase()
    if sb is not None:
        try:
            rows = sb.table(_TABLE).select("data").eq("id", _ROW_ID).execute().data
            if rows and rows[0].get("data"):
                return rows[0]["data"]
        except Exception as e:
            logger.warning(f"dip_buy: load failed, using file — {e}")
    if _FILE.exists():
        try:
            return json.loads(_FILE.read_text())
        except Exception:
            pass
    return {"open": None, "closed": [], "last_date": None}


def _save(state: dict) -> None:
    from dashboard.scan_store import _supabase
    sb = _supabase()
    if sb is not None:
        try:
            sb.table(_TABLE).upsert({"id": _ROW_ID, "data": state}).execute()
            return
        except Exception as e:
            logger.warning(f"dip_buy: save failed, using file — {e}")
    _FILE.write_text(json.dumps(state, ensure_ascii=False))


def analyze_dip_buy(df_d: pd.DataFrame) -> dict | None:
    """每日调用:推进台账一步 + 返回展示块。df_d 需含 high/close 列(大小写均可)。"""
    try:
        d = df_d.rename(columns=str.lower)
        if len(d) < 25:
            return None
        hi20 = float(d["high"].rolling(20).max().iloc[-1])
        close = float(d["close"].iloc[-1])
        today = str(pd.Timestamp(df_d.index[-1]).date())
        trigger_px = round(hi20 * _TRIG, 2)
        triggered = close <= hi20 * _TRIG

        st = _load()
        if st.get("last_date") != today:          # 幂等:每个交易日只走一步
            pos = st.get("open")
            if pos:
                pos["days"] = int(pos.get("days", 0)) + 1
                exit_px = reason = None
                if close >= pos["target"]:
                    exit_px, reason = close, "回95%止盈"
                elif pos["days"] >= _MAX_HOLD:
                    exit_px, reason = close, "15天到期"
                if exit_px is not None:
                    pnl = pos["shares"] * exit_px * (1 - _COST) - _USD
                    st["closed"] = (st.get("closed") or [])[-49:] + [{
                        "entry_date": pos["entry_date"], "entry": pos["entry"],
                        "exit_date": today, "exit": round(exit_px, 2),
                        "days": pos["days"], "reason": reason,
                        "pnl": round(pnl, 2), "pnl_pct": round(pnl / _USD, 4)}]
                    st["open"] = None
            elif triggered:
                shares = _USD * (1 - _COST) / close
                st["open"] = {"entry_date": today, "entry": round(close, 2),
                              "shares": round(shares, 4),
                              "target": round(hi20 * _TP, 2), "days": 0}
            st["last_date"] = today
            _save(st)

        closed = st.get("closed") or []
        n, wins = len(closed), sum(1 for t in closed if t["pnl"] > 0)
        pos = st.get("open")
        out = {
            "trigger_px": trigger_px, "hi20": round(hi20, 2),
            "close": round(close, 2), "triggered": bool(triggered),
            # 现价距触发线(负数=还要再跌这么多才触发)
            "distance_pct": round(trigger_px / close - 1, 4),
            "open": None,
            "n_closed": n, "n_win": wins,
            "win_rate": round(wins / n, 3) if n else None,
            "realized": round(sum(t["pnl"] for t in closed), 2),
            "recent": list(reversed(closed))[:5],
        }
        if pos:
            unreal = pos["shares"] * close * (1 - _COST) - _USD
            out["open"] = {**pos, "unreal": round(unreal, 2),
                           "unreal_pct": round(unreal / _USD, 4)}
        return out
    except Exception as e:
        logger.warning(f"dip_buy failed: {e}")
        return None
