# ============================================================
# NPC 回忆召回（Recall）处理模块
#
# 负责处理 <recall> XML 标签，将特定 NPC 加入"下回合重注入"队列。
#
# 【为什么需要 Recall 机制？】
# AI 语言模型有上下文长度限制。在长对话中，早期的 NPC 信息
# 可能已经"滚出"了上下文窗口，GM（LLM）实际上已经"忘记"了
# 某些 NPC 的完整档案（外貌/背景/动机/与 PC 的历史等）。
#
# 当 GM 想要让一个"沉寂已久"的 NPC 重新出场，
# 但又担心自己记忆不完整时，可以 emit <recall name="王欣"/>，
# 告诉系统"下一回合，请把王欣的完整档案塞回我的提示词里"。
#
# 【工作原理】
# 1. GM emit <recall name="王欣"/> 时，本函数把 "王欣" 添加到
#    Session.recall_pending_json（一个 JSON 字符串列表）
# 2. 下一回合构建 GM 提示词时，_build_key_facts 函数会读取这个列表，
#    把每个 NPC 的完整档案注入 system prompt
# 3. 注入后，列表被清空（"drain"），避免重复注入
#
# 典型的 GM 输出示例：
#   <recall name="王欣"/>        （最常见形式）
#   <recall>王欣</recall>         （兜底写法，GM 可能把名字放在 body 里）
# ============================================================

"""<recall> handler — append NPC name to Session.recall_pending_json."""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Session as GameSession


async def _apply_recall(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],  # XML 属性，含 name="..."
    content: str,           # 标签 body（GM 有时把名字放这里）
) -> None:
    # -------------------------------------------------------
    # 处理 <recall> 标签
    #
    # 提取 NPC 名字（优先从 name 属性，其次从 body 文本），
    # 然后追加到 Session.recall_pending_json 列表。
    # 避免重复添加同一个名字（幂等性）。
    # -------------------------------------------------------
    """GM-driven NPC recall: signals 'this NPC is back, re-inject full dossier
    next turn.' Appends the name to Session.recall_pending_json (a JSON list).
    The list is drained on the next prompt build."""
    # 优先使用 name 属性
    name = (attrs.get("name") or "").strip()
    if not name:
        # 兜底：GM 有时不规范地把名字写在标签 body 里
        # Tolerate GM placing the name in body text as a fallback.
        name = (content or "").strip()
    if not name:
        return  # 没有找到名字，忽略这个标签

    sess = await session.get(GameSession, session_id)
    if sess is None:
        return  # 游戏局不存在，跳过

    # 读取现有的待召回列表
    pending = json.loads(sess.recall_pending_json or "[]")
    if not isinstance(pending, list):
        pending = []

    # 避免重复：同一个 NPC 名字只加一次
    if name not in pending:
        pending.append(name)

    sess.recall_pending_json = json.dumps(pending, ensure_ascii=False)  # 写回数据库
