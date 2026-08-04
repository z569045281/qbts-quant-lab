"""🔔 决策卡触发线推送 —— 收盘越线,立刻响一条。

**出身(2026-08-04,用户点单)**:08-03 的决策卡写着「收盘放量站上 $18.88 且 QQQ
不再走弱 → 小仓买 QBTX」。当晚三个条件全中(收 $19.98、量 2444 万、QQQ +1.76%),
**但没有任何东西通知用户** —— 收盘是墨尔本早上 6 点,他在睡觉;第二天醒来看到已经
涨了 10% 才追。

系统里特调、SMC playbook、事件日、催化剂、地缘、周末 BTC、挑战 bot、游击战全都有
ntfy,**唯独决策卡自己每天给的那条触发线没有**。这个模块补的就是那一条。

━━ 纪律 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
· **只推事实,不新造判断。** 价位与动作都原样来自当天已发布的 `decision.watch_levels`,
  这里不做任何方向判断、不改任何读数。它是一个闹钟,不是一个信号源。
· **只在收盘后判一次。** 盘中穿越不算 —— "只认收盘不认盘中"是在册纪律
  (盘中预挂已判死),推送口径必须与决策口径一致。
· **做空条目推不出去。** `_clean_watch_levels` 已经在源头丢弃,这里再挡一道:
  铁律不靠单点防守。
· **每天每条线最多响一次**,状态随 live_quote carry-forward。
  ⚠️ 非工作跳一律 `return prev` —— live_quote 是整块覆写的,返回 None 会把当天
  已推记录冲掉,下一跳就重复响铃(2026-07-31 事件日那次事故的同一个坑)。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# 收盘后的判定窗口(ET)。16:00 收盘,给数据源几分钟落定;窗口给宽一点,
# 免得 Lambda 某一分钟没跑就整天不判。
_WIN_START = 16 * 60 + 2
_WIN_END = 16 * 60 + 30

_TABLE = "dashboard_state"


def _today_levels() -> tuple[list[dict], str | None]:
    """从**已发布**的快照里取当天的 watch_levels。一天只读一次(收盘窗口内)。"""
    try:
        from supabase import create_client
        url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL")
        key = (os.environ.get("SUPABASE_SECRET_KEY")
               or os.environ.get("SUPABASE_SERVICE_KEY")
               or os.environ.get("SUPABASE_ANON_KEY"))
        if not (url and key):
            return [], None
        sb = create_client(url, key)
        r = (sb.table(_TABLE).select("snapshot")
             .order("published_at", desc=True).limit(1).execute())
        snap = ((r.data or [{}])[0] or {}).get("snapshot") or {}
        dec = snap.get("decision") or {}
        return list(dec.get("watch_levels") or []), snap.get("as_of")
    except Exception as e:
        logger.warning("decision_trigger: 取 watch_levels 失败: %s", e)
        return [], None


def _crossed(px: float, lv: dict) -> bool:
    p = float(lv["price"])
    return px >= p if lv["side"] == "above" else px <= p


def evaluate(levels: list[dict], close_px: float) -> list[dict]:
    """哪些线被收盘价越过了。纯函数,给测试用。"""
    out = []
    for lv in (levels or []):
        try:
            if lv.get("side") not in ("above", "below"):
                continue
            if _crossed(close_px, lv):
                out.append(lv)
        except (TypeError, ValueError, KeyError):
            continue
    return out


def maybe_trigger_push(prev: dict | None, now_et, quotes: dict | None) -> dict | None:
    """收盘窗口内判一次;越线的条各推一条 ntfy(每天每条一次)。

    非窗口/无数据 → **原样返回 prev**(carry-forward,别把已推记录冲掉)。
    """
    from quote_pusher import us_session   # 只为拿星期/时段口径,不拉行情

    today = now_et.date().isoformat()
    hm = now_et.hour * 60 + now_et.minute
    if now_et.weekday() >= 5 or not (_WIN_START <= hm <= _WIN_END):
        return prev
    if us_session(now_et) not in ("post", "closed"):
        return prev                      # 还没收盘,不判

    px = ((quotes or {}).get("qbts") or {}).get("price")
    try:
        px = float(px)
    except (TypeError, ValueError):
        return prev
    if px <= 0:
        return prev

    fired = list((prev or {}).get("fired") or []) if (prev or {}).get("date") == today else []
    levels, as_of = _today_levels()
    if not levels:
        return {"date": today, "fired": fired, "close": round(px, 2),
                "note": "当天决策卡没给 watch_levels"}

    from dashboard.decision import _SHORT_WORDS

    newly = []
    for lv in evaluate(levels, px):
        key = f"{lv['side']}@{float(lv['price']):.2f}"
        if key in fired:
            continue
        act = str(lv.get("action_cn") or "")
        if any(w in act for w in _SHORT_WORDS):   # 源头已丢,这里是第二道
            logger.warning("decision_trigger: 拒推做空条目 %s", key)
            fired.append(key)
            continue
        newly.append((key, lv, act))

    if not newly:
        return {"date": today, "fired": fired, "close": round(px, 2)}

    from dashboard.intraday_smc import _ntfy
    for key, lv, act in newly:
        arrow = "站上" if lv["side"] == "above" else "跌破"
        body = (f"QBTS 收盘 ${px:.2f} —— {arrow}决策线 ${float(lv['price']):.2f}\n\n"
                f"→ {act}\n\n"
                f"依据:{as_of or '?'} 的决策卡 watch_levels(收盘口径,盘中穿越不算)。\n"
                f"⚠️ 这是闹钟不是新信号:动作照决策卡执行,仓位上限与减仓时点别改。")
        if _ntfy(f"QBTS 🔔 {arrow} ${float(lv['price']):.2f}", body,
                 tags="bell", priority="high"):
            fired.append(key)

    return {"date": today, "fired": fired, "close": round(px, 2)}
