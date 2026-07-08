"""用户实盘持仓(💼 当前持仓)。

存 Supabase `scan_paper` 表独立行 id='user_positions'(复用 JSON 行存储,零迁移;
本地文件回退)。每个 ticker 一条,重复添加 = 覆盖更新。**只允许 QBTS/QBTX/QBTZ**
—— 决策大脑是 QBTS 专用系统,别的票它没有任何信号上下文,硬给建议 = 幻觉。

流向:每日 publish 时 `load_positions()` → snapshot['user_positions'] →
decision prompt「用户实盘持仓」段 → 模型逐笔输出 `position_advice`(持有/加仓/
减仓/清仓 + 一句话理由,受执行军规约束)→ 前端 💼 卡展示。站上编辑走
/scan/watch(本地)或 PublishFunction URL(云)的 pos_add / pos_remove 动作,
与自选清单编辑同一条通道。
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

ALLOWED = ("QBTS", "QBTX", "QBTZ")
_TABLE = "scan_paper"
_ROW_ID = "user_positions"
_FILE = Path(__file__).parent.parent / "data" / "cache" / "user_positions.json"


def _sb():
    from dashboard.scan_store import _supabase
    return _supabase()


def load_positions() -> list[dict]:
    """[{ticker, qty, cost, date}] — Supabase 优先,本地文件回退,失败 = 空表。"""
    sb = _sb()
    if sb is not None:
        try:
            rows = sb.table(_TABLE).select("data").eq("id", _ROW_ID).execute().data
            if rows and rows[0].get("data") is not None:
                return rows[0]["data"].get("positions") or []
        except Exception as e:
            logger.warning(f"positions: load failed, using file — {e}")
    if _FILE.exists():
        try:
            return json.loads(_FILE.read_text()).get("positions") or []
        except Exception:
            pass
    return []


def _save(positions: list[dict]) -> None:
    data = {"positions": positions}
    sb = _sb()
    if sb is not None:
        try:
            sb.table(_TABLE).upsert({"id": _ROW_ID, "data": data}).execute()
            return
        except Exception as e:
            logger.warning(f"positions: save failed, using file — {e}")
    _FILE.write_text(json.dumps(data, ensure_ascii=False))


def upsert_position(ticker: str, qty, cost, bought: str | None = None) -> list[dict]:
    """新增/覆盖一笔持仓;返回最新持仓表。bought 缺省 = 今天(用户可回填买入日)。"""
    t = (ticker or "").strip().upper()
    if t not in ALLOWED:
        raise ValueError(f"ticker 仅限 {'/'.join(ALLOWED)}(决策系统只认识它们)")
    qty, cost = float(qty), float(cost)
    if not (qty > 0 and cost > 0):
        raise ValueError("qty/cost 必须为正数")
    pos = [p for p in load_positions() if p.get("ticker") != t]
    pos.append({"ticker": t, "qty": qty, "cost": cost,
                "date": (bought or date.today().isoformat())[:10]})
    pos.sort(key=lambda p: p.get("ticker", ""))
    _save(pos)
    return pos


def remove_position(ticker: str) -> list[dict]:
    t = (ticker or "").strip().upper()
    pos = [p for p in load_positions() if p.get("ticker") != t]
    _save(pos)
    return pos
