"""🏆 策略冠军 —— 记分卡前三名 + 大盘闸门,同向就推 ntfy。

出身(2026-08-05,用户点单):当天的全板块回测审计(docs/AUDIT-AND-EDGE.md)
把 15 个板块在 36 个交易日 / 16 个大波动日上排了一次序:

    成交量画像 POC   大波动日 8 表态 87.5% 命中(全部日 16 表态 81.2%)
    日内画像 Intrabar 大波动日 7 表态 85.7% 命中(全部日 10 表态 80.0%)
    地缘政治雷达      大波动日 8 表态 75.0% 命中(全部日 17 表态 70.6%)
    ────────────────────────────────────────────
    SMC 聪明钱结构    大波动日 50.0% = 硬币 · NW 包络 0/2 · 另外 9 个板块 0 次表态

用户要:"把前三名加大盘做成一个模块,触发了推 ntfy,放页面最上面"。

━━ 纪律(预注册,看到结果之前写死)━━━━━━━━━━━━━━━━━━━━━━━━

① **表态一律走 `readings.collect`,不新造判据。** 那是 07-31 就写死的导出规则
   (readings.py 纪律②),本模块只做投票聚合。事后改导出规则 = 套线。

② **它是 UNPROVEN,而且模块自己要说出来。** 前两名的 n 只有 7/8,Wilson 95%
   下界 ≈47%,**打不过"大波动日无脑喊跌"的 56.2% 基线**。判决线(n≥30 · Wilson
   下界 > 基线)一条都没过。所以卡片和推送里都必须带这句话,不许只显示胜率。

③ **大盘是闸门,不是第四票。** QQQ50 是仓库里唯一被姐妹票 3/3 验证过的通用过滤
   (第十一轮),但它没有方向表态。红灯时看多降级为「观察」不推送 —— 与在册
   「QQQ50×波目」同构,也与 08-05 审计里"5日新低抄底:绿灯 +3.69% / 红灯 −1.04%"
   的实测方向一致。

④ **只推做多,不推做空。** 做空 QBTS 全部已知路径第 7/9/13/23 轮四次判死;
   `intraday_smc.py` 拦 bear lock 是同一条纪律的另一个出口。空头方向照常显示、
   照常记账,只是不推送、不给动作。

⑤ **上升沿才推。** 与 SMC TRIGGER 推送同一套去重:状态存进 `live_quote`,
   非触发→触发那一跳才响一次,连续触发不重复轰炸。

⑥ **零决策权。** 不进 edge 权重、不进决策 prompt、不改任何阈值。它是一张把
   已有读数排序显示的卡 + 一条推送。真要给它权重,得等 readings 台账 n≥30。

━━ ⚠️ 建成当天就必须写下来的实测(142 份快照回放)━━━━━━━━━━━━━━

    状态分布:IDLE 89 · SHORT_MUTED 50 · GATED 3 · **TRIGGER 0**

**这两个月它一次都不会响。** 原因不是规则太严,是这种日子根本没出现过:

    成交量画像:偏空 61 / 偏多 **4** / 中性 67 / 缺 10
    日内画像  :偏空 16 / 偏多 13 / 中性 7 / **缺 106**
    地缘雷达  :偏空 58 / 偏多 **0** / 中性 12 / 缺 72   ← 只在 risk_level=calm 才说多
    大盘绿灯  :**10 / 142**

偏多的那 4 天和绿灯的那 10 天**不重叠**,所以任何「≥2 票偏多 + 绿灯」的组合都是 0。

**而且这暴露了一件更根本的事**:这三名 87.5% / 85.7% / 75% 的大波动日命中率,
**主要来自它们「喊跌喊对了」**(成交量画像 61 次偏空 : 4 次偏多)。这两个月是跌市,
它们说跌,所以准。**拿一个空头准确率去驱动一个做多触发器,逻辑上不成立。**

所以本模块的定位必须是:**一张每天都有内容的排序显示卡**(三名读数 + 闸门状态,
让"最会看的三个模块今天说什么"一眼可见),推送只是顺带 —— 它响不响不是它的
价值来源。等 readings 台账攒够 n≥30、并且攒到足够多的**上涨**样本,再回来判它。
"""

from __future__ import annotations

import logging
import os
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

try:
    from dashboard.readings import collect as collect_readings
except ImportError:  # loose-module import path (aws lambda / scripts)
    from readings import collect as collect_readings

# ── 冠军名册:key → (显示名, 08-05 审计的大波动日成绩) ──────────────────
# 成绩是**写死的历史读数**,不是实时算的 —— 卡片上要能说清"凭什么是它".
CHAMPIONS: list[tuple[str, str, dict]] = [
    ("volume_profile", "成交量画像 / POC",
     {"big_n": 8, "big_hit": 87.5, "all_n": 16, "all_hit": 81.2}),
    ("intrabar", "日内画像 Intrabar",
     {"big_n": 7, "big_hit": 85.7, "all_n": 10, "all_hit": 80.0}),
    ("geopolitics", "地缘政治雷达",
     {"big_n": 8, "big_hit": 75.0, "all_n": 17, "all_hit": 70.6}),
]

# 大波动日「无脑喊跌」的命中率 —— 任何板块低于它就不如一句看空。
BASELINE_BIG = 56.2
UNPROVEN_NOTE = (
    "⚠️ UNPROVEN:前两名 n 只有 7/8,Wilson 95% 下界 ≈47%,"
    f"打不过大波动日「无脑喊跌」的 {BASELINE_BIG}% 基线。判决线(n≥30)一条没过 —— "
    "这是一张排序显示卡,不是已验证的信号。"
)

_STANCE_CN = {"up": "偏多", "down": "偏空", "neutral": "中性"}


def _market_gate(snapshot: dict) -> dict:
    """大盘红绿灯 → 闸门状态。没有数据时**明确说不知道**,不冒充绿灯。"""
    ml = snapshot.get("market_light") or {}
    qqq = ml.get("qqq_vs_50dma")
    if qqq is None:
        return {"light": "unknown", "cn": "⚪️ 大盘数据缺失", "pass_long": False,
                "note": "拿不到 QQQ 相对 50 日线的位置 —— 闸门按【不放行】处理(宁可漏,不可错)。"}
    green = float(qqq) >= 0
    return {
        "light": "green" if green else "red",
        "cn": ("🟢 大盘绿灯" if green else "🔴 大盘红灯"),
        "pass_long": green,
        "qqq_vs_50dma": round(float(qqq), 4),
        "vix": ml.get("vix"),
        "regime": ml.get("regime"),
        "note": (f"QQQ 高于 50 日线 {float(qqq)*100:+.1f}% —— 做多逻辑放行。" if green
                 else f"QQQ 低于 50 日线 {float(qqq)*100:+.1f}% —— 一切做多逻辑降档"
                      "(第十一轮姐妹票 3/3 验证过的唯一通用过滤)。"),
    }


def build(snapshot: dict, extras: dict | None = None) -> dict:
    """三名投票 + 大盘闸门 → 一张卡的 payload。纯函数,无 I/O。"""
    readings = collect_readings(snapshot or {}, extras or {})

    members, votes = [], []
    for key, cn, score in CHAMPIONS:
        r = readings.get(key) or {}
        st = r.get("stance")
        members.append({
            "key": key, "name": cn, "stance": st,
            "stance_cn": _STANCE_CN.get(st, "无表态"),
            "read": r.get("read") or "(缺)",
            **score,
        })
        if st in ("up", "down"):
            votes.append(st)

    n_up, n_down = votes.count("up"), votes.count("down")
    n_voice = len(votes)

    # ── 共识:≥2 票且**没有反对票**(2:1 不算共识 —— 三个人里一个反对就不是齐声)
    if n_up >= 2 and n_down == 0:
        direction = "up"
    elif n_down >= 2 and n_up == 0:
        direction = "down"
    else:
        direction = None

    gate = _market_gate(snapshot)

    # ── 状态机(纪律③④)────────────────────────────────────────────
    if direction is None:
        state, state_cn = "IDLE", ("冠军没凑齐共识" if n_voice else "三名今天都没表态")
        action = "wait"
    elif direction == "down":
        # 纪律④:方向照常显示、照常记账,但不推送、不给动作
        state, state_cn = "SHORT_MUTED", "冠军一致偏空 —— 只作风控背景,不推送"
        action = "wait"
    elif not gate["pass_long"]:
        state, state_cn = "GATED", f"冠军一致偏多,但{gate['cn']}拦下 —— 降级为观察"
        action = "watch"
    else:
        state, state_cn = "TRIGGER", "🎯 冠军一致偏多 + 大盘绿灯"
        action = "long"

    return {
        "state": state, "state_cn": state_cn, "action": action,
        "direction": direction,
        "n_voice": n_voice, "n_up": n_up, "n_down": n_down,
        "consensus": f"{max(n_up, n_down)}/{len(CHAMPIONS)}" if direction else f"0/{len(CHAMPIONS)}",
        "members": members,
        "gate": gate,
        "unproven_note": UNPROVEN_NOTE,
        "baseline_big": BASELINE_BIG,
        "price": snapshot.get("price"),
    }


# ── ntfy 推送(上升沿,纪律⑤)────────────────────────────────────────

from dashboard.notify import push as _ntfy   # 全仓唯一一份推送


def _prev_state() -> str | None:
    """上一份 dashboard_state 里的冠军状态 —— 上升沿去重的依据(纪律⑤)。

    发布时这一行还没写,所以"最后一行"就是上一次。拿不到就返回 None
    (宁可多推一条,也不要因为读不到状态而永远静音)。
    """
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if not (url and key):
        return None
    try:
        import json
        req = urllib.request.Request(
            f"{url}/rest/v1/dashboard_state?select=snapshot&order=published_at.desc&limit=1",
            headers={"apikey": key, "Authorization": f"Bearer {key}"})
        rows = json.load(urllib.request.urlopen(req, timeout=15))
        return (((rows or [{}])[0].get("snapshot") or {}).get("champions") or {}).get("state")
    except Exception as e:
        logger.warning("champions: 读上一次状态失败(按无历史处理) — %s", e)
        return None


def push_if_new(card: dict) -> bool:
    """发布链路的一行调用:自己去读上一次状态,只在上升沿推。"""
    try:
        return maybe_push(card, _prev_state())
    except Exception as e:
        logger.warning("champions push failed: %s", e)
        return False


def maybe_push(card: dict, prev_state: str | None) -> bool:
    """只在 **非 TRIGGER → TRIGGER** 那一跳推一次(纪律⑤)。"""
    if not card or card.get("state") != "TRIGGER":
        return False
    if prev_state == "TRIGGER":
        return False          # 已经在触发态,不重复轰炸
    lines = [
        f"QBTS ${card.get('price')} · 冠军共识 {card.get('consensus')} 偏多 + 大盘绿灯",
        "",
    ]
    for m in card.get("members") or []:
        mark = "✅" if m["stance"] == "up" else ("❌" if m["stance"] == "down" else "—")
        lines.append(f"{mark} {m['name']}（大波动日 {m['big_hit']}%/n={m['big_n']}）：{m['read'][:48]}")
    lines += ["", card.get("gate", {}).get("note", ""), "", UNPROVEN_NOTE]
    return _ntfy("QBTS CHAMPIONS", "\n".join(x for x in lines if x is not None),
                 tags="trophy")
