"""ntfy.sh 推送 —— 全仓唯一一份(2026-08-05 从 `intraday_smc` 抽出来)。

抽出来的原因:这份实现本来就已经是事实上的公共件 —— 8 个模块在
`from dashboard.intraday_smc import _ntfy`,从一个不相干的模块里进口一个私有名。
另外还有两份各自为政的拷贝(`champions._ntfy` 24 行、`guerrilla._ntfy` 11 行),
其中 guerrilla 那份既不做标题编码也吞掉所有异常,还额外依赖 `requests`。
现在三份合一,`intraday_smc` 只剩 SMC 的事。
"""

from __future__ import annotations

import os
import urllib.request
from datetime import datetime, timezone
from email.header import Header      # RFC 2047:非 ASCII 标题装进 HTTP 头(见 _hdr)

# 推送通道的健康状态。**失败必须能被看见** —— 07-30 夜盘 +10.2% 那次,错误每分钟
# 打进 Lambda 日志却没有任何界面告诉用户,于是又一次没有推送。日志不是监控。
_LAST_PUSH: dict = {"ok_at": None, "err_at": None, "err": None, "title": None}


def health() -> dict:
    """推送通道最近一次成功/失败(冷启动后重置;失败会每分钟重现,够用)。"""
    return dict(_LAST_PUSH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stamp() -> str:
    """推送落款:美东 + 墨尔本双时区(2026-08-18 用户点单「带个时间」)。

    为什么两个时区都要:事件按**美东**发生(盘前/盘中/收盘都是 ET 口径),
    而用户在**墨尔本**看手机。只给一个,他每次都得在脑子里换算一次;
    换算错了就会把昨天的消息当成刚发生的。

    还有个更实际的理由:推送**堆在通知栏里是没有时间的**(手机只显示"送达
    时间",而 Lambda 重试/延迟会让两者差好几分钟)。落款是唯一能回答
    「这条消息说的是几点的事」的东西 —— 尤其在同一件事反复出现的时候。

    zoneinfo 缺 tzdata 时(精简容器)退回 UTC,绝不让落款把整条推送炸掉。
    """
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(timezone.utc)
        et = now.astimezone(ZoneInfo("America/New_York"))
        mel = now.astimezone(ZoneInfo("Australia/Melbourne"))
        return (f"🕒 {et:%m-%d %H:%M} ET / {mel:%m-%d %H:%M} 墨尔本")
    except Exception:
        return f"🕒 {datetime.now(timezone.utc):%m-%d %H:%M} UTC"


def _hdr(s: str) -> str:
    """把标题编成 HTTP 头能装的形式。

    HTTP 头按 latin-1 编码,非 ASCII 标题会让 urllib 在**发送前**抛
    UnicodeEncodeError —— 整条推送丢失,而调用方只看到 False。
    原实现只在 docstring 里写了"Title stays ASCII" —— 文档不是守门员,
    event_day 就这么违约了两天。改成函数自己保证。

    RFC 2047 encoded-word(`=?utf-8?b?...?=`)实测 ntfy 能正确解码回
    "QBTS ⚠️ 事件日"(2026-07-31 用一次性 topic 实打验证)。
    纯 ASCII 标题原样返回 → 现役调用点字节级不变。
    """
    try:
        s.encode("latin-1")
        return s
    except UnicodeEncodeError:
        return Header(s, "utf-8").encode()


# ── 推送优先级三档(2026-08-22 用户点单)────────────────────────────────
# **起因**:`ntfy_log` 建账 4 天后第一次能数账 —— 31 条推送里 **16 条(52%)是地缘
# 雷达**,而唯一一条真正说"可以买"的(决策线触发)只有 1 条,还落在墨尔本凌晨 6 点。
# 全部 31 条里 15 条(48%)在墨尔本 00:00-08:00(美股收盘 = 墨尔本早 6 点)。
# 病根:**所有推送都用同一个 priority**,于是决策线触发和第 16 条伊朗新闻在手机上
# 长得一模一样,信号被自己的噪音埋了。
#
# 分档依据 **不是感觉,是 8/15 审判的成绩单**:
#   · 地缘雷达 —— ②📋 记分卡 n=2 命中 0% 技巧 −53pp;第三十一轮已定性「后视镜」
#     → 它没有资格在半夜把人吵醒。降到 low(静默进通知栏,卡片照常更新)。
#   · 买点/卖点/事件日 —— 这些是**要你动手**的东西,漏掉的代价最大 → urgent。
#   · 催化剂 🔴 重大 —— 值得知道但不必立刻动 → high。
P_ACTION  = "urgent"   # 买点/卖点/扳机/事件日:会响会震,漏了代价最大
P_NEWS    = "high"     # 重大催化剂:值得知道,不必立刻动手
P_AMBIENT = "low"      # 雷达常规刷新 / 日检:静默进通知栏,不打扰

_LOG_TABLE = "ntfy_log"


def _log(title: str, body: str, tags: str, priority: str, sent: bool) -> None:
    """把每一条推送存进 `ntfy_log`(2026-08-13 用户点单:「以后每一个都存下来」)。

    为什么值得存:ntfy.sh 免费版**只保留最近十几条**(查刷屏那次拉 `since=all`
    也只回来 5 条),历史一过就没了。而推送是这套系统唯一的对外输出 —— 想回答
    「哪条提醒真的带来了机会」「噪音占几成」,必须有自己的账本。

    ⚠️ 台账**绝不能反过来影响推送**:写库整段包在 try 里,失败只打印。
    表没建时静默降级(与 overnight_ticks 同一约定)。
    """
    try:
        from dashboard.db import supabase
        sb = supabase()
        if sb is None:
            return
        sb.table(_LOG_TABLE).insert({
            "ts": _now_iso(), "title": title, "body": body[:4000],
            "tags": tags, "priority": priority, "sent": sent,
        }).execute()
    except Exception as e:
        print(f"! ntfy_log skipped: {type(e).__name__}: {e}")


def pushed_since(title: str, since_iso: str) -> bool:
    """台账里 `since_iso` 之后有没有**成功**推过这个 title —— 去重的第二道保险。

    为什么需要它:各模块的「今天推过了」标记都住在 `live_quote.data` 这一个整块
    覆写的 blob 里,那一次读或写失败,标记就凭空消失(2026-09-14:周末BTC 推了
    18 条)。`ntfy_log` 是独立的一张表,两处同时抖的概率低得多。

    ⚠️ 查不到、查失败、没配库 —— 一律返回 False。台账只能拦重复,**绝不许**反过来
    把一条真信号挡掉。"""
    try:
        from dashboard.db import supabase
        sb = supabase()
        if sb is None:
            return False
        r = (sb.table(_LOG_TABLE).select("ts").eq("title", title).eq("sent", True)
             .gte("ts", since_iso).limit(1).execute())
        return bool(r.data)
    except Exception as e:
        print(f"! ntfy_log dedup check skipped: {type(e).__name__}: {e}")
        return False


def push(title: str, body: str, tags: str = "rotating_light",
         priority: str = "high", stamp: bool = True) -> bool:
    """POST to ntfy.sh (no auth needed). 中文/emoji 标题会自动按 RFC 2047 编码
    (见 `_hdr`);正文一律 UTF-8。没配 NTFY_TOPIC 就 no-op 返回 False。

    `stamp=True`(默认)在正文末尾加一行 ET/墨尔本双时区落款(见 `_stamp`)。
    每条推送(**含失败的**)都记进 `ntfy_log`;台账失败不影响推送本身。"""
    topic = os.getenv("NTFY_TOPIC")
    if not topic:
        return False
    if stamp:
        body = f"{body}\n\n{_stamp()}"
    base = os.getenv("NTFY_URL", "https://ntfy.sh").rstrip("/")
    try:
        req = urllib.request.Request(
            f"{base}/{topic}", data=body.encode("utf-8"), method="POST",
            headers={"Title": _hdr(title), "Tags": tags, "Priority": priority,
                     "Content-Type": "text/plain; charset=utf-8"})
        urllib.request.urlopen(req, timeout=8)
        _LAST_PUSH.update(ok_at=_now_iso(), err_at=None, err=None, title=title)
        _log(title, body, tags, priority, True)
        return True
    except Exception as e:
        # ⚠️ Request(...) 的构造本身就可能抛(头编码)——所以它也在 try 里面。
        print(f"! ntfy push failed: {type(e).__name__}: {e}")
        _LAST_PUSH.update(err_at=_now_iso(), err=f"{type(e).__name__}: {e}"[:160],
                          title=title)
        _log(title, body, tags, priority, False)   # 失败的也记 —— 查哑火要靠它
        return False


if __name__ == "__main__":
    # 自检:标题编码是这个模块唯一有分支的逻辑(丢过一次真推送),必须跑得起来。
    assert _hdr("QBTS SMC TRIGGER") == "QBTS SMC TRIGGER", "纯 ASCII 必须原样"
    enc = _hdr("QBTS ⚠️ 事件日")
    enc.encode("latin-1")                       # 装不进 HTTP 头就当场炸
    assert enc.startswith("=?utf-8?b?"), enc
    from email.header import decode_header
    raw, cs = decode_header(enc)[0]
    assert raw.decode(cs) == "QBTS ⚠️ 事件日", "编回去必须还原"

    os.environ.pop("NTFY_TOPIC", None)
    assert push("t", "b") is False, "没配 topic 必须 no-op,不许抛"
    assert health()["ok_at"] is None and health()["err_at"] is None, "no-op 不该记账"

    # 落款:必须两个时区都在、且绝不抛(容器缺 tzdata 时退回 UTC)
    st = _stamp()
    assert st.startswith("🕒"), st
    assert ("ET" in st and "墨尔本" in st) or "UTC" in st, st
    print("notify.py self-check OK —— 落款示例:", st)
