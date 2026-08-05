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


def push(title: str, body: str, tags: str = "rotating_light",
         priority: str = "high") -> bool:
    """POST to ntfy.sh (no auth needed). 中文/emoji 标题会自动按 RFC 2047 编码
    (见 `_hdr`);正文一律 UTF-8。没配 NTFY_TOPIC 就 no-op 返回 False。"""
    topic = os.getenv("NTFY_TOPIC")
    if not topic:
        return False
    base = os.getenv("NTFY_URL", "https://ntfy.sh").rstrip("/")
    try:
        req = urllib.request.Request(
            f"{base}/{topic}", data=body.encode("utf-8"), method="POST",
            headers={"Title": _hdr(title), "Tags": tags, "Priority": priority,
                     "Content-Type": "text/plain; charset=utf-8"})
        urllib.request.urlopen(req, timeout=8)
        _LAST_PUSH.update(ok_at=_now_iso(), err_at=None, err=None, title=title)
        return True
    except Exception as e:
        # ⚠️ Request(...) 的构造本身就可能抛(头编码)——所以它也在 try 里面。
        print(f"! ntfy push failed: {type(e).__name__}: {e}")
        _LAST_PUSH.update(err_at=_now_iso(), err=f"{type(e).__name__}: {e}"[:160],
                          title=title)
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
    print("notify.py self-check OK")
