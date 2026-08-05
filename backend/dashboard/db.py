"""一个 Supabase 客户端,全仓共用(2026-08-05)。

原本 9 个模块各自抄了一遍同样的 16 行 —— 其中 `challenge2` 和 `positions` 已经
学乖了,函数内转发 `scan_store._supabase`。现在全部转发这里。

拿不到 URL/KEY(或 `supabase` 包装不上)就返回 None,各模块照旧退回本地文件。

**失败不缓存**:本地跑的时候 `load_dotenv()` 有可能比某个模块的首次调用还晚,
早期那一次拿不到 key 不该毒死整个进程 —— 旧的 `_SB_INIT` 写法就有这个毛病,
只是当时每个模块各有一份缓存,互相隔离才没炸出来。共用一份就必须补上。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_SB = None


def supabase():
    """缓存的 Supabase 客户端(secret key,可写);没配好返回 None。"""
    global _SB
    if _SB is not None:
        return _SB
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if not (url and key):
        return None
    try:
        from supabase import create_client
        _SB = create_client(url, key)
    except Exception as e:
        logger.warning("Supabase init failed — %s", e)
    return _SB


if __name__ == "__main__":
    # 自检:没有 key 时必须安静地给 None,而且**不缓存**这次失败。
    for k in ("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL",
              "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_KEY"):
        os.environ.pop(k, None)
    assert supabase() is None
    assert _SB is None, "失败被缓存了 —— dotenv 晚加载就再也连不上了"
    os.environ["SUPABASE_URL"] = "https://example.supabase.co"
    os.environ["SUPABASE_SECRET_KEY"] = "fake-key-for-selfcheck"
    assert supabase() is not None, "有 key 就该建出客户端"
    assert supabase() is supabase(), "成功的客户端必须缓存"
    print("db.py self-check OK")
