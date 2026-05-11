# ============================================================
# state_apply 包的入口文件
#
# 【整体设计思路】
#
# dzmm 是一个 AI 跑团（TRPG）引擎，由 LLM 担任 GM（游戏主持人）。
# GM 每回合输出一段叙事文本，同时在文本里嵌入 XML 标签，例如：
#
#   <npc_update name="王欣" favor_delta="+2"/>
#   <character_xp delta="50"/>
#   <doom delta="+5"/>
#
# state_apply 子系统的职责是：
#   1. 从 LLM 回复中解析出这些 XML 标签（由上层 parsing 模块完成）
#   2. 把每个标签"应用"到数据库，更新对应的游戏状态
#
# 设计上把这个子系统拆成多个小模块（npc.py / doom.py / ...），
# 每个模块只负责一类标签，理由是：
#   - 单一职责：每个文件只关心一类数据，方便独立修改和测试
#   - 避免巨型文件：原始版本是 1091 行的单文件，已难以维护
#   - 可读性：新人只需找到对应模块就能理解某类标签的处理逻辑
#
# 外部调用者（FastAPI 路由等）只需导入 `apply_tags` 这一个函数，
# 传入当前回合的标签列表，该函数会把路由工作分发给各子模块。
# ============================================================

# 这是包初始化文件，Python 导入 state_apply 包时会自动执行这里的代码

# 通配符导入 _impl 中的所有公共符号，保持向后兼容
# noqa 注释告诉 flake8 不要对这行报 "unused import" 警告
from dzmm.service.state_apply._impl import *  # noqa: F401, F403

# 同时以模块对象的形式导出 _impl，供需要 _impl.xxx 写法的调用方使用
from dzmm.service.state_apply import _impl as _impl  # noqa: F401

# 显式地从 _impl 导出最核心的公共入口函数 apply_tags，
# 这样外部代码可以直接写 `from state_apply import apply_tags`，
# 不必关心内部是哪个子模块实现的。
# （经 grep 确认，整个后端和测试代码里，外部只消费 apply_tags 这一个符号）
from dzmm.service.state_apply._impl import (  # noqa: E402
    apply_tags,
)
