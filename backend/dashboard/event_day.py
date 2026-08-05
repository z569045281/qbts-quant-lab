"""事件日熔断(第二十八轮,2026-07-29)。

**这不是 alpha 信号,是一个熔断器。** 起因:2026-07-27 QBTS +20.4%(AT&T 240× 公告
+ 纳斯达克首日)、QBTX +40.1%,而当晚的分析用「跳空≥3% → 日内 −0.91%」把用户劝退了。
复盘后把跳空重新分档,发现那个负期望根本不覆盖极端档:

    QBTS 5年 · 当日「开→收」(扣 0.4% 双边)
      跳空 3~8%   n=162  均值 −1.79%  中位 −2.94%  胜率 32%  t=−2.02  p=0.045  ← 技术面有效
      跳空 ≥8%    n= 37  均值 +0.81%  中位 −0.00%  胜率 49%  t=+0.36  p=0.722  ← 技术面失效

也就是说:**普通跳空可以用技术面劝退,极端跳空不行** —— 后者是"有大事发生"的代理,
统计上没有任何分辨力(p=0.72),此时再拿技术读数下方向结论就是在编。

所以本模块只做一件事:**命中事件日 → 给技术面结论熔断,方向留白,只给风控。**
它 **不产生买卖信号,不改任何已有读数的数值**(预注册条件),只在决策 prompt 与
卡片上加一段披露 + 盘前推一条 ntfy。

判死存档(同轮预注册,不得重提):
  A 极端跳空当买入信号 —— QBTS ≥8% 中位 −0.00%、姐妹 IONQ −0.87%/RGTI −2.35% 反向 → 判死
  B 暴涨次日日内空     —— 胜率 56%<60%、t=−0.33 → 判死
  D 暴涨日收盘买次日卖 —— QBTS 单独很强(n=59 +5.33% t=+2.73 p=0.008 近1年不反号),
                          但姐妹 IONQ/RGTI 均不同向 → 按预注册第⑤条判死
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 技术面失效阈值。上行档由 n=37 实测(t=+0.36,p=0.72);下行档 n=10 只做过描述性
# 观察(p=0.38),证据弱得多 —— 对称套用是保守选择:熔断只会让系统少说话,不会让
# 它多下注,宁可在证据不足的一侧也闭嘴。
_GAP_MUTE = 0.08

_EVIDENCE_CN = ("跳空≥8% 档实测 n=37 · 日内 t=+0.36 · p=0.72 —— "
                "该区间技术读数无分辨力(对照:跳空 3~8% 档 t=−2.02 · p=0.045 有效)")


def detect_event_day(df_d, live_price: float | None = None,
                     catalyst: dict | None = None) -> dict | None:
    """事件日检测。非事件日返回 None(前端卡片自动消失)。

    df_d       — 日线(收盘口径);用 [-1] 作为"前收",[-2] 备用
    live_price — 实时价(夜盘/盘前/盘中均可);缺失则退回用最新日线的开盘价算跳空
    catalyst   — catalyst_radar 的 snapshot,读 impact_level
    """
    try:
        reasons: list[str] = []
        gap = None

        d = df_d.rename(columns=str.lower)
        prev_close = float(d["close"].iloc[-1])

        # 跳空口径:优先实时价(盘前就能判,这正是 07-27 需要的),否则用当日开盘。
        # 注意 df_d 最后一根在盘中是"活的"部分 bar,它的 open 已是今日开盘价。
        if live_price and prev_close > 0:
            ref, basis = float(live_price), "实时价"
            # 实时价对应的"前收"要往前退一根,否则拿今天比今天
            if len(d) >= 2:
                prev_close = float(d["close"].iloc[-2])
        else:
            ref, basis = float(d["open"].iloc[-1]), "开盘价"
            if len(d) >= 2:
                prev_close = float(d["close"].iloc[-2])

        if prev_close > 0:
            gap = ref / prev_close - 1
            if abs(gap) >= _GAP_MUTE:
                reasons.append(f"{basis}较前收 {gap * 100:+.1f}%(≥±8% 极端档)")

        lvl = (catalyst or {}).get("impact_level")
        if lvl == "breaking":
            head = (catalyst or {}).get("headline_cn") or "重大催化剂"
            reasons.append(f"催化剂雷达 🔴 breaking:{head[:40]}")

        if not reasons:
            return None

        return {
            "is_event_day": True,
            "reasons": reasons,
            "gap": round(gap, 4) if gap is not None else None,
            "gap_basis": basis,
            "catalyst_level": lvl,
            "technical_muted": True,
            "evidence_cn": _EVIDENCE_CN,
            "note_cn": (
                "事件日:技术面结论已熔断。这天的价格由消息主导,跳空幅度/超卖读数/"
                "均线位置都失去分辨力 —— 系统既不劝进也不劝退,只负责把风控说清楚。"
                "要不要参与、参与多少,是你的判断,不是读数的判断。"
            ),
        }
    except Exception as e:
        logger.warning(f"detect_event_day failed: {e}")
        return None


def from_quote(quotes: dict | None, catalyst: dict | None = None) -> dict | None:
    """分钟级用的轻量版:直接吃 quote_pusher 已经算好的 `change_pct`
    (= price/prev_close−1),不碰 yfinance —— 每分钟的 Lambda 里不能拉日线。"""
    q = ((quotes or {}).get("qbts") or {})
    chg = q.get("change_pct")
    reasons: list[str] = []
    # ⚠️ 前收对不上账时**不许**据此判极端跳空(2026-07-31)。实测事故:
    # `fast_info.previous_close` 给了 16.45 而真实收盘 17.97 → 这里算出
    # 「隔夜 +9.8% 极端跳空」并高优先级推送,而真实隔夜只有 +0.5%。
    # 一个没对过账的基准凭空造出了一次警报。宁可漏报,不可错报:
    # 错报会让技术面无谓熔断一整天,还教用户不要信这个铃。
    # (`prev_close_trusted` 由 quote_pusher._prev_close 打;老 payload 无此字段
    #  → None → 按旧行为放行,不因为升级把历史数据判成不可信。)
    trusted = q.get("prev_close_trusted")
    if chg is not None and abs(float(chg)) >= _GAP_MUTE and trusted is not False:
        reasons.append(f"现价较前收 {float(chg) * 100:+.1f}%(≥±8% 极端档)")
    elif chg is not None and abs(float(chg)) >= _GAP_MUTE:
        logger.warning("event_day: 跳空 %.1f%% 但 prev_close 未对上账 → 不判事件日",
                       float(chg) * 100)
    lvl = (catalyst or {}).get("impact_level")
    if lvl == "breaking":
        reasons.append(f"催化剂雷达 🔴 breaking:{((catalyst or {}).get('headline_cn') or '')[:40]}")
    if not reasons:
        return None
    return {
        "is_event_day": True,
        "reasons": reasons,
        "gap": round(float(chg), 4) if chg is not None else None,
        "gap_basis": "实时价",
        "price": q.get("price"),
        # 只要雷达手上有任何一条消息就带上 —— 「有事发生」而不告诉你是什么事,
        # 等于让你自己去翻新闻,那就白推了(哪怕它只判到 watch 级也比没有强)。
        "catalyst_headline": (catalyst or {}).get("headline_cn"),
        "catalyst_level": lvl,
        "technical_muted": True,
        "evidence_cn": _EVIDENCE_CN,
        "note_cn": ("事件日:技术面结论已熔断。系统既不劝进也不劝退 —— "
                    "这天由消息定价,读数没有发言权。"),
    }


def maybe_event_day_push(prev: dict | None, now_et, quotes: dict | None,
                         catalyst: dict | None = None) -> dict | None:
    """盘前/盘中命中事件日 → ntfy 一次(每交易日每"原因条数"各一次)。

    **为什么必须有这条推送**:07-27 的 +20.4% 在盘前就能看见(夜盘已 +2.75%、
    开盘跳空 +10.2%),但用户当时手上只有一份 23:00 才到的、基于收盘价的决策,
    而那份决策的技术面结论是"别追"。这条推送的唯一职责是**在开盘前把熔断
    这件事本身告诉他** —— 不给方向,只解除那个错误的拦阻。
    """
    today = now_et.date().isoformat()
    prev_key = str((prev or {}).get("push_key") or "")

    ev = from_quote(quotes, catalyst)
    if not ev:
        # ⚠️ **判不出事件日 ≠ 今天不是事件日**(2026-07-31 实况修复)。
        # 事故:用户一早收到两条一模一样的「⚠️ 事件日」,间隔 100 分钟。
        # 病理:去重键 `push_key` 存活在 live_quote 里,而 live_quote 每分钟被
        # **整块覆写** —— 这一分钟 `from_quote` 返回 None(催化剂分级挂了、
        # 返回 unknown 而不是 breaking),handler 的 `if ev:` 就不写 event_day,
        # 键随之消失;下一跳分级恢复 → prev 里没键 → 当成第一次,再推一遍。
        # 只要上游读数偶尔抖一下,这条推送就会一天响好几次。
        #
        # 修法:**键与状态分离**。键属于"今天推没推过",跟这一分钟判不判得出来
        # 无关,同一 ET 日一律带走;`is_event_day` 属于"现在还熔不熔断",判不出来
        # 就老实说 False,不冒充在熔断(与第三十轮「分级挂了就说不知道」同一条纪律)。
        if prev_key.startswith(today):
            return {"push_key": prev_key, "is_event_day": False,
                    "carry_note": "本分钟判不出事件日(上游读数缺失);今日已推过,不重复响铃"}
        return None
    key = f"{today}#{len(ev['reasons'])}"
    # 原因**变多**才值得再响一次(比如跳空之外又来了 breaking 新闻);原因变少
    # 只是读数回落,不是新情况 —— 早先版本用 `== key` 判等,2 条掉回 1 条时键不
    # 相等就会再推一遍。改成"只认已推过的最高档"。
    prev_n = 0
    if prev_key.startswith(today) and "#" in prev_key:
        try:
            prev_n = int(prev_key.rsplit("#", 1)[1])
        except ValueError:
            prev_n = 0
    if prev_n >= len(ev["reasons"]):
        ev["push_key"] = prev_key      # 保留最高档,别被降档冲掉
        return ev                      # 已推过,只做 carry-forward

    px = ev.get("price")
    head = ev.get("catalyst_headline")
    body = (f"QBTS ${px:.2f}\n" if px else "")
    body += "\n".join(f"· {r}" for r in ev["reasons"])
    if head and ev.get("catalyst_level") != "breaking":
        # breaking 已经作为 reason 写进去了,别重复;watch 级则单独带一行当线索
        body += f"\n· 雷达最近消息:{head[:50]}"
    body += ("\n\n技术面结论已熔断:跳空≥8% 档实测 t=+0.36 / p=0.72,"
             "超卖、折价区、均线这些读数今天没有分辨力。\n"
             "→ 系统不劝进也不劝退,方向由你判断。\n"
             "→ 做空仍然不做(全部已知路径已判死)。")
    try:
        from dashboard.notify import push as _ntfy
        if _ntfy("QBTS ⚠️ 事件日", body, tags="rotating_light", priority="high"):
            ev["push_key"] = key
    except Exception as e:
        logger.warning(f"event_day ntfy failed: {e}")
    return ev


def prompt_block(ev: dict | None) -> str:
    """决策 prompt 里的事件日段。非事件日返回空串。

    `is_event_day` 必须显式为真才渲染 —— carry-forward 的那种只带去重键、
    不带熔断状态的记录(见 `maybe_event_day_push`)不能触发熔断段。
    """
    if not ev or not ev.get("is_event_day"):
        return ""
    why = " · ".join(ev["reasons"])
    return (
        "\n【⚠️ 事件日熔断(强制规则)】\n"
        f"命中原因:{why}\n"
        f"实测依据:{ev['evidence_cn']}\n"
        "你必须遵守:\n"
        "① **不得**用跳空幅度、超卖/超买读数、均线位置作为劝进或劝退的主要理由 ——\n"
        "   已实测这些读数在本区间无统计分辨力(p=0.72),拿它们下方向结论等于编造。\n"
        "② 方向可以留白。允许直说「今天技术面没有发言权」,这比硬凑一个方向更诚实。\n"
        "③ 仍要给:关键价位、失效位、仓位上限、事件本身的性质(一次性 vs 可持续)。\n"
        "④ **不得**因为「涨太多了」或「跳空太大了」建议做空 —— 做空 QBTS 的全部已知\n"
        "   路径均已判死,本轮复盘又新判死两条(暴涨次日日内空 / 暴涨日收盘买次日卖)。\n"
    )
