# ============================================================
# routes_sessions 包入口
# ============================================================
# 【包的作用】
#   routes_sessions 是一个 Python 包（目录里有 __init__.py 就叫包）。
#   它把所有与"游戏存档（session）"相关的 HTTP 接口拆分到多个子模块，
#   每个子模块负责一个功能域（消息、回合、NPC……），
#   这里负责把它们全部汇总成一个 router，供 main.py 一次性挂载。
#
# 【为什么拆文件？】
#   如果所有路由都写在一个文件里，文件会超过几千行，难以维护。
#   拆分后每个文件 100~300 行，职责单一，修改某个功能只需找对应文件。
#
# 【测试打补丁（monkeypatch）的问题】
#   测试代码有时需要用假实现替换 build_client（例如返回固定文本而不真的调用 LLM）。
#   Python 的替换方式是 `setattr(模块, "build_client", 假实现)`。
#   但各子模块在 import 时已经把 build_client 复制到自己的命名空间，
#   只替换包级别的引用不会影响子模块里的本地绑定。
#   这里通过自定义 __setattr__ 代理，确保在包层面写入的属性会同步传播到每个子模块。
# ============================================================
import sys as _sys

from fastapi import APIRouter

# 从公共模块导入共享的工具函数和依赖注入占位符
# noqa: F401 表示"这些 import 虽然在本文件没有直接使用，但作为公开 API 重新导出，不要报 unused import 警告"
from dzmm.api.routes_sessions._common import (  # noqa: F401 — public re-exports
    build_client,
    get_session_dep,
    get_session_maker_dep,
)
from dzmm.api.routes_sessions._common import (  # noqa: F401 — backward compat
    _npc_to_dict,
    _parse_events_json,
    _to_out,
)

# 导入每个功能子模块的 router 对象（每个子模块都定义了自己的 APIRouter）
from dzmm.api.routes_sessions.base import router as _base_router
from dzmm.api.routes_sessions.locations import router as _locations_router
from dzmm.api.routes_sessions.export import router as _export_router
from dzmm.api.routes_sessions.feedback import router as _feedback_router
from dzmm.api.routes_sessions.goals import router as _goals_router
from dzmm.api.routes_sessions.hidden_events import router as _hidden_events_router
from dzmm.api.routes_sessions.messages import router as _messages_router
from dzmm.api.routes_sessions.npcs import router as _npcs_router
from dzmm.api.routes_sessions.spinoff import router as _spinoff_router
from dzmm.api.routes_sessions.threads import router as _threads_router
from dzmm.api.routes_sessions.suggest import router as _suggest_router
from dzmm.api.routes_sessions.turn import router as _turn_router
from dzmm.api.routes_sessions.npc_tick import router as _npc_tick_router
from dzmm.api.routes_sessions.debug_chain import router as _debug_chain_router

# 创建本包对外暴露的总 router
# main.py 只需 `app.include_router(router, prefix="/sessions")` 就能注册全部接口
router = APIRouter()

# 把所有子路由合并进总路由
# include_router 类似把多个子路由树"嫁接"到父树上
for _sub in (
    _base_router,
    _messages_router,
    _turn_router,
    _threads_router,
    _npcs_router,
    _goals_router,
    _hidden_events_router,
    _feedback_router,
    _export_router,
    _locations_router,
    _spinoff_router,
    _suggest_router,
    _npc_tick_router,
    _debug_chain_router,
):
    router.include_router(_sub)


# ── 测试 monkeypatch 同步代理机制 ────────────────────────────────────────
# 问题背景：
#   测试代码执行 `monkeypatch.setattr(dzmm.api.routes_sessions, "build_client", fake)`
#   实际上等同于 `setattr(该模块对象, "build_client", fake)`。
#   但各子模块（如 turn.py）在自己 import 时已经把 build_client 绑定到本地变量，
#   修改包层面的属性不会改变子模块内的绑定。
#
# 解决方案：
#   给这个模块对象的类注入自定义 __setattr__，当有公开属性被写入时，
#   同时遍历所有子模块，把相同名字的属性也更新过去。
#   这样测试打补丁就能透明地穿透到真正使用它的地方。

# 获取当前模块对象（即这个 __init__.py 对应的模块）
_pkg_module = _sys.modules[__name__]
# 保存原始的 __setattr__，后面代理里调用它完成默认的属性写入
_pkg_module_setattr = _pkg_module.__class__.__setattr__

# 所有可能缓存了可打补丁符号的子模块名（字符串形式，通过 sys.modules 查找）
# 新增子模块时，如果它从 _common 导入了可被测试替换的符号，要把模块名加到这里
_SUBMODULES = (
    "dzmm.api.routes_sessions._common",
    "dzmm.api.routes_sessions.base",
    "dzmm.api.routes_sessions.export",
    "dzmm.api.routes_sessions.feedback",
    "dzmm.api.routes_sessions.goals",
    "dzmm.api.routes_sessions.hidden_events",
    "dzmm.api.routes_sessions.messages",
    "dzmm.api.routes_sessions.npcs",
    "dzmm.api.routes_sessions.spinoff",
    "dzmm.api.routes_sessions.threads",
    "dzmm.api.routes_sessions.turn",
    "dzmm.api.routes_sessions.locations",
    "dzmm.api.routes_sessions.suggest",
    "dzmm.api.routes_sessions.npc_tick",
    "dzmm.api.routes_sessions.debug_chain",
)


def _proxy_setattr(self, name, value):  # type: ignore[no-redef]
    # 先执行默认的属性写入（把值保存到包模块自身）
    _pkg_module_setattr(self, name, value)
    # 以下划线开头的私有属性不需要同步（比如 _pkg_module 本身）
    if name.startswith("_"):
        return
    # 遍历所有子模块，如果该子模块已经加载（在 sys.modules 里）
    # 并且拥有同名属性，则把新值同步过去
    for _mod_name in _SUBMODULES:
        _mod = _sys.modules.get(_mod_name)
        if _mod is not None and hasattr(_mod, name):
            setattr(_mod, name, value)


# 动态创建一个新的模块类，继承原来的模块类但覆盖 __setattr__
# 然后把当前模块对象的 __class__ 换成这个新类
# 这是 Python 里"给已存在对象的类打补丁"的标准技巧
_pkg_module.__class__ = type(
    "_RoutesSessionsModule",       # 新类的名字（仅用于调试/repr）
    (_pkg_module.__class__,),      # 继承原来的模块类
    {"__setattr__": _proxy_setattr},  # 覆盖 __setattr__
)
