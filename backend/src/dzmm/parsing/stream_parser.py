# ============================================================
# 流式 XML 标签解析器
# ============================================================
# 【背景】
#   LLM 逐字输出文本，我们约定它用 XML 标签区分内容类型：
#     <narrative>正常叙事文本</narrative>
#     <state_change>{"hp": -5}</state_change>
#     <dice skill="感知" target="12">15</dice>
#   这个解析器从"字符流"中实时识别这些标签，边接收边处理。
#
# 【为什么需要流式解析？】
#   如果等 LLM 全部说完再解析，玩家要等 10-30 秒才能看到任何文字，
#   体验很差。流式解析让 <narrative> 的内容边生成边显示（打字机效果）。
#   而其他标签（<state_change>、<npc_update>）需要完整内容才能处理，
#   所以先缓冲，等闭合标签出现再整体处理。
#
# 【流式解析的难点】
#   标签可能被切在两次 feed() 之间（如第一次收到 "<narr"，第二次才收到 "ative>"）。
#   因此需要维护"状态机"而不是一次性解析。
#
# 【Java 对比】
#   这是一个典型的状态机（State Machine）设计。
#   Java 里会用 enum 定义状态，Python 这里用字符串常量代替（更简洁）。
#   方法返回 list[ParseEvent] 而不是用回调（callback），让调用方更容易测试。
# ============================================================

import re
from difflib import SequenceMatcher  # 标准库：计算两个序列的相似度

from dzmm.parsing.events import NarrativeDelta, ParseError, ParseEvent, TagComplete

# ── 已知标签白名单 ────────────────────────────────────────
# 只处理这些已知标签；其他标签（包括 LLM 乱写的）直接丢弃。
# 用 set（集合）存储，因为 `in` 操作对 set 是 O(1)（比 list 快得多）。
KNOWN_TAGS: set[str] = {
    "narrative",
    "dice",
    "state_change",
    "npc_update",
    "plot_event",
    "choices",
    "character_xp",
    "recall",
    "pc_goal",
    "pc_mood",
    "npc_relation",
    "hidden_event",
    "say",
    "pc_action",
    "scene_shift",
    "chapter_advance",
    "event_complete",
    "plot_turn",
    "ending",
    "location_enter",
    "location_edge",
    "bgm",
    "time_advance",
    "combat_start",
    "combat_end",
    "faction_create",
    "faction_change",
    "npc_cue",
    "event_trigger",
    # v0.15 Batch 2 — Python-engine intent tags
    "dice_request",   # GM asks Python to roll & resolve
    "skill_request",  # GM asks Python to perform skill check
    "item_use",       # GM signals player consumed/used an item
    # v0.15 Batch 3 — combat resolution tags
    "attack",              # GM triggers single attack resolution
    "initiative_request",  # GM triggers initiative rolling for a list of combatants
}

# 只有 narrative 标签需要"流式"输出（边到边推给前端显示）；
# 其他标签缓冲到闭合后再整体处理（因为需要完整内容才能解析）。
STREAMING_TAGS: set[str] = {"narrative"}

# ── 正则表达式预编译 ──────────────────────────────────────
# 【Python 特点】re.compile() 预编译正则，比每次都传字符串快。
# 【Java 对比】相当于 Pattern.compile()。

# 匹配开标签，如 <dice skill="感知" target="12"> 或 <location_enter/>
# 捕获组 1：标签名  捕获组 2：属性字符串  捕获组 3：是否自闭合（/）
# 解释：
#   (\w+)               → 标签名（字母/数字/下划线）
#   ((?:\s+\w+="[^"]*")*) → 0或多个属性（key="value"），(?:...) 是非捕获组
#   \s*(/?))            → 可选的斜杠（自闭合标签如 <br/>）
_OPEN_TAG_RE = re.compile(r"<(\w+)((?:\s+\w+=\"[^\"]*\")*)\s*(/?)>")

# 匹配闭标签，如 </narrative>
_CLOSE_TAG_RE = re.compile(r"</(\w+)\s*>")

# 从属性字符串中提取 key="value" 对
# 例如 ' skill="感知" target="12"' → [("skill","感知"), ("target","12")]
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def _edit_distance(a: str, b: str) -> int:
    """计算两个字符串的编辑距离（Levenshtein distance）。

    【算法】经典 DP 问题：dp[i][j] = a[:i] 变成 b[:j] 的最小操作数。
    这里用滚动数组优化空间（只保留两行）。
    用于判断 LLM 是否写了拼写错误的闭标签（如 </narriative>）。
    """
    if a == b:
        return 0       # 完全相同，距离为 0
    if not a:
        return len(b)  # a 为空，需要插入 len(b) 次
    if not b:
        return len(a)  # b 为空，需要删除 len(a) 次
    prev = list(range(len(b) + 1))  # 初始化：空字符串变成 b[:j] 需要 j 次插入
    for i, ca in enumerate(a, 1):   # enumerate(a, 1)：从 1 开始计数
        curr = [i] + [0] * len(b)   # 当前行，首列 = a[:i] 变成空串需要 i 次删除
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1  # 相同字符替换代价为 0，不同为 1
            curr[j] = min(
                curr[j - 1] + 1,      # 插入操作
                prev[j] + 1,          # 删除操作
                prev[j - 1] + cost,   # 替换操作（相同字符 cost=0）
            )
        prev = curr  # 当前行变成下一轮的前一行（滚动数组）
    return prev[-1]  # 最后一个元素是完整的编辑距离


def _is_typo_close(opened: str, found: str) -> bool:
    """判断 </found> 是否可能是 </opened> 的拼写错误。

    同时满足两个条件才认为是 typo：
      1. SequenceMatcher 相似度 >= 0.7（字符层面 70% 相似）
      2. 编辑距离 <= 2（最多改 2 个字符）

    设计意图：LLM 偶尔会写 </narriative> 而不是 </narrative>，
    与其让整个标签内容丢失，不如容错处理。
    """
    if not opened or not found:
        return False
    if opened == found:
        return False  # 完全相同，不是 typo（应该由精确匹配处理）
    # 快速拒绝：长度差超过 2 的话编辑距离一定 > 2
    if abs(len(opened) - len(found)) > 2:
        return False
    # SequenceMatcher 计算"公共子序列"长度，ratio 是相似度分数（0-1）
    ratio = SequenceMatcher(None, opened, found).ratio()
    if ratio < 0.7:
        return False
    return _edit_distance(opened, found) <= 2  # 确认编辑距离 <= 2


# ── 解析器主类 ────────────────────────────────────────────
class StreamingTagParser:
    """增量解析 LLM 流式输出中的 XML 标签。

    用法（伪代码）：
        parser = StreamingTagParser()
        async for chunk in llm.stream(...):
            for event in parser.feed(chunk.delta):
                handle(event)
        for event in parser.finish():  # 流结束时清理残留
            handle(event)

    【状态机设计】
        OUTSIDE       → 在任何标签外部，等待开标签
        IN_STREAMING  → 在 <narrative> 内部，每收到文本立即推送 NarrativeDelta
        IN_BUFFERED   → 在其他已知标签内部，缓冲直到闭合
        IN_UNKNOWN    → 在未知标签内部，静默丢弃内容
    """

    def __init__(self) -> None:
        self._buf: str = ""                   # 尚未处理的原始输入缓冲区（跨 chunk 积累）
        self._state: str = "OUTSIDE"          # 当前状态机状态（4 种之一）
        self._current_tag: str | None = None  # 当前正在处理的标签名
        self._current_attrs: dict[str, str] = {}  # 当前标签的属性字典
        self._tag_buf: str = ""               # 当前标签内已收集的内容（缓冲模式用）

    def feed(self, chunk: str) -> list[ParseEvent]:
        """喂入一个文本片段，返回本次产生的事件列表。

        【设计原则】
          - 不抛异常，所有错误通过 ParseError 事件上报
          - 调用方可以随时调用，不需要知道内部状态
          - 返回列表而不是回调，便于测试和单步调试
        """
        self._buf += chunk   # 把新来的文本追加到缓冲区
        events: list[ParseEvent] = []

        # 循环处理缓冲区，直到没有可以消费的内容为止
        while True:
            consumed = False  # 标记本轮循环是否消费了任何内容

            # ── 状态 1：在标签外 ───────────────────────────
            if self._state == "OUTSIDE":
                m = _OPEN_TAG_RE.search(self._buf)   # 在缓冲区里找开标签
                if not m:
                    # 没有找到开标签：如果缓冲区里也没有 "<"，可以安全清空
                    # （因为 "<" 可能是某个开标签的开始，需要保留等待后续输入）
                    if "<" not in self._buf:
                        self._buf = ""  # 纯文本，没有标签，可以丢弃（GM 输出规范里标签外的文字会被忽略）
                    break  # 等待更多输入
                tag = m.group(1).lower()                              # 标签名（转小写）
                attrs_str = m.group(2) or ""                          # 属性字符串
                self_close = m.group(3) == "/"                        # 是否是自闭合标签
                self._current_tag = tag
                self._current_attrs = dict(_ATTR_RE.findall(attrs_str))  # 解析所有属性
                self._tag_buf = ""
                self._buf = self._buf[m.end():]   # 消费掉开标签之前的内容和开标签本身

                if self_close:
                    # 自闭合标签（如 <location_enter name="..." />）没有内容体，
                    # 直接产出 TagComplete，不需要等闭合标签
                    if tag in KNOWN_TAGS:
                        events.append(TagComplete(
                            name=tag,
                            attrs=self._current_attrs,
                            content="",  # 自闭合标签内容为空
                        ))
                    self._state = "OUTSIDE"    # 处理完，回到初始状态
                    self._current_tag = None
                    self._current_attrs = {}
                elif tag in STREAMING_TAGS:
                    self._state = "IN_STREAMING"   # narrative → 边接收边推送
                elif tag in KNOWN_TAGS:
                    self._state = "IN_BUFFERED"    # 其他已知标签 → 缓冲整体
                else:
                    self._state = "IN_UNKNOWN"     # 未知标签 → 静默丢弃
                consumed = True

            # ── 状态 2/3/4：在标签内 ──────────────────────
            elif self._state in ("IN_STREAMING", "IN_BUFFERED", "IN_UNKNOWN"):
                exact_close = f"</{self._current_tag}>"  # 精确闭合标签字符串
                exact_idx = self._buf.find(exact_close)   # 在缓冲区中查找

                # 尝试查找拼写错误的闭合标签（只对已知标签做容错，未知标签不做）
                typo_idx = -1
                typo_close: str = ""
                typo_found_name: str = ""
                if self._state in ("IN_STREAMING", "IN_BUFFERED"):
                    for cm in _CLOSE_TAG_RE.finditer(self._buf):
                        found = cm.group(1).lower()
                        if found == self._current_tag:
                            continue  # 跳过精确匹配（已在上面用 find 处理）
                        if _is_typo_close(self._current_tag or "", found):
                            typo_idx = cm.start()    # 记录找到的 typo 闭标签位置
                            typo_close = cm.group(0)
                            typo_found_name = found
                            break  # 找到第一个就够了

                # A different known close tag means the model mismatched the
                # closing name (for example <pc_action>...</narrative>). Treat
                # it as an implicit close so later tags remain independently
                # parseable instead of being swallowed into the current body.
                mismatch_idx = -1
                mismatch_close = ""
                mismatch_name = ""
                if self._state in ("IN_STREAMING", "IN_BUFFERED"):
                    for cm in _CLOSE_TAG_RE.finditer(self._buf):
                        found = cm.group(1).lower()
                        if found == self._current_tag or _is_typo_close(self._current_tag or "", found):
                            continue
                        if found in KNOWN_TAGS:
                            mismatch_idx = cm.start()
                            mismatch_close = cm.group(0)
                            mismatch_name = found
                            break

                if exact_idx == -1 and typo_idx == -1 and mismatch_idx == -1:
                    # 还没找到闭合标签：需要等待更多输入
                    # 但可以把"安全"的前缀部分推送出去（避免缓冲区无限增长）
                    # hold = 保留尾部的长度（确保跨块的闭标签不被切断）
                    hold = len(exact_close) + 2   # +2 是 typo 最多比精确多 2 个字符
                    safe_len = max(0, len(self._buf) - hold)
                    if safe_len > 0:
                        safe = self._buf[:safe_len]
                        if self._state == "IN_STREAMING":
                            # 流式标签（narrative）：立刻推送给前端显示
                            events.append(NarrativeDelta(safe))
                            self._tag_buf += safe   # 同时记录到标签缓冲（finish 时用）
                        elif self._state == "IN_BUFFERED":
                            self._tag_buf += safe   # 非流式标签：只缓冲，等闭合后整体处理
                        # IN_UNKNOWN：静默丢弃，什么都不做
                        self._buf = self._buf[safe_len:]   # 消费掉已处理的部分
                    break  # 等待更多输入

                # 如果精确闭合标签和 typo 闭合标签都找到了，选位置更靠前的那个
                # （更靠前意味着更早结束当前标签，避免把不该包含的内容吃进来）
                candidates = [
                    (idx, kind) for idx, kind in (
                        (exact_idx, "exact"),
                        (typo_idx, "typo"),
                        (mismatch_idx, "mismatch"),
                    ) if idx != -1
                ]
                idx, close_kind = min(candidates, key=lambda item: item[0])
                use_typo = close_kind == "typo"
                use_mismatch = close_kind == "mismatch"
                if use_typo:
                    close_len = len(typo_close)
                elif use_mismatch:
                    close_len = len(mismatch_close)
                else:
                    close_len = len(exact_close)

                inner = self._buf[:idx]  # 闭合标签之前的内容就是标签的 body

                if self._state == "IN_STREAMING" and inner:
                    # narrative 的最后一段文字
                    events.append(NarrativeDelta(inner))
                elif self._state == "IN_BUFFERED":
                    self._tag_buf += inner  # 把最后一段内容追加到缓冲区
                    # 现在缓冲区包含了完整的标签内容，可以产出 TagComplete
                    events.append(TagComplete(
                        name=self._current_tag or "",
                        attrs=self._current_attrs,
                        content=self._tag_buf.strip(),  # .strip() 去掉首尾空白
                    ))

                if use_typo:
                    # 记录 typo 修复，供调试
                    events.append(ParseError(
                        message=(
                            f"close-tag typo: </{typo_found_name}> "
                            f"matched as </{self._current_tag}>"
                        ),
                        raw=typo_close,
                    ))
                elif use_mismatch:
                    events.append(ParseError(
                        message=(
                            f"mismatched close tag: </{mismatch_name}> "
                            f"closed <{self._current_tag}>"
                        ),
                        raw=mismatch_close,
                    ))

                # 消费掉闭合标签，重置状态机到 OUTSIDE
                self._buf = self._buf[idx + close_len:]
                self._state = "OUTSIDE"
                self._current_tag = None
                self._current_attrs = {}
                self._tag_buf = ""
                consumed = True

            if not consumed:
                break  # 本轮没有进展，退出循环，等下一次 feed()

        return events

    def finish(self) -> list[ParseEvent]:
        """LLM 流结束时调用。清理未关闭的标签。

        【设计】
          - IN_STREAMING 残留：直接推出剩余文本（LLM 忘了写 </narrative>）
          - IN_BUFFERED 残留：发一个 ParseError + 一个部分 TagComplete
            （宁可拿到不完整的数据，也比丢弃整个标签好）
        """
        events: list[ParseEvent] = []
        if self._state == "IN_STREAMING":
            # LLM 在 narrative 里没有写闭合标签就结束了，把剩余内容推出去
            residual = self._tag_buf + self._buf   # 已缓冲 + 还未处理的
            if residual:
                events.append(NarrativeDelta(residual))
        elif self._state == "IN_BUFFERED":
            # 非流式标签没有闭合（LLM 被截断或忘了写闭标签）
            partial = (self._tag_buf + self._buf).strip()
            events.append(ParseError(
                message=f"Unclosed tag <{self._current_tag}>",
                raw=self._tag_buf + self._buf,
            ))
            # 尽管不完整，还是把收集到的部分内容产出，而不是完全丢弃
            # 调用方可以判断 ParseError 之后的 TagComplete 是部分数据，酌情使用
            events.append(TagComplete(
                name=self._current_tag or "",
                attrs=dict(self._current_attrs),
                content=partial,
            ))

        # 重置所有状态，供下次使用（虽然通常每次对话都创建新的解析器实例）
        self._buf = ""
        self._state = "OUTSIDE"
        self._current_tag = None
        self._current_attrs = {}
        self._tag_buf = ""
        return events
