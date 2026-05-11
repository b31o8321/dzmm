# ============================================================
# 解析事件数据结构（parsing/events.py）
# ============================================================
# 【这个文件做什么？】
#   定义了流式解析器（stream_parser.py）产出的"事件"类型。
#   解析器读取 LLM 的输出流，识别 XML 标签，然后产出这些事件对象。
#   下游代码（如 game.py）订阅这些事件，分别处理不同类型。
#
# 【什么是流式解析？】
#   LLM 是逐字（逐 token）输出的，不是一次性给出整个响应。
#   我们不能等 LLM 说完再处理，而是要边接收边解析。
#   流式解析就是：每收到一小段文字（chunk），就尝试从中提取完整的标签。
#
# 【为什么用 dataclass？】
#   @dataclass 是 Python 的装饰器，自动生成：
#   - __init__：构造函数
#   - __repr__：调试打印
#   - __eq__：相等比较
#   不需要手写这些方法，代码更简洁。
#   Java 里类似的概念是 Lombok 的 @Data 或 Java 16+ 的 record。
#
# 【类型联合（ParseEvent）】
#   ParseEvent = NarrativeDelta | TagComplete | ParseError
#   这是 Python 的"联合类型"（Union Type）。
#   下游代码用 isinstance() 判断具体是哪种事件，然后分支处理：
#     if isinstance(event, NarrativeDelta): ...  # 流式文字，直接推给前端
#     elif isinstance(event, TagComplete): ...   # 完整标签，解析并更新状态
#     elif isinstance(event, ParseError): ...    # 错误，记录日志
# ============================================================
from dataclasses import dataclass, field


@dataclass
class NarrativeDelta:
    # 流式叙事文本片段：LLM 在 <narrative> 标签内输出的文字，
    # 每收到一小段就立刻推给前端显示（这样玩家不需要等整个回合结束）。
    # 就像聊天软件里看到对方"正在打字"时逐字出现的效果。
    text: str


@dataclass
class TagComplete:
    # 完整标签事件：当解析器找到一对完整的开闭标签（<xxx>...</xxx>）时产出。
    # name：标签名（如 "state_change"、"npc_update"、"dice"）
    # attrs：标签的属性字典（如 <dice category="stealth" dc="12"> → {"category": "stealth", "dc": "12"}）
    # content：标签内的文本内容（如 <state_change>{"hp": -5}</state_change> → '{"hp": -5}')
    name: str
    attrs: dict[str, str] = field(default_factory=dict)  # 默认为空字典（不共享可变对象）
    content: str = ""


@dataclass
class ParseError:
    # 解析错误事件：当解析遇到异常时产出（如拼写错误的闭标签、未闭合标签）。
    # 不抛出异常（Python 里叫"异常"，Java 里叫"Exception"），
    # 而是作为事件产出，让调用方决定是否记录/忽略/重试。
    # 这种设计叫"错误即值"（Error as Value），比异常传递更易测试。
    message: str  # 错误描述
    raw: str      # 原始文本（方便调试）


@dataclass
class UsageSummary:
    # Token 使用量汇总：每次 LLM 调用结束后产出，记录本次消耗的 token 数。
    # 用于计费统计和调试（token 消耗过多可能意味着提示词太长）。
    # 【注意】这不是 ParseEvent 的一部分，所以没有放在联合类型里。
    # run_turn_v10 会在最后产出这个对象，但在转发 SSE 给前端之前会过滤掉。
    tokens_in: int = 0   # 输入 token 数（提示词的长度）
    tokens_out: int = 0  # 输出 token 数（LLM 生成的文字长度）


# 联合类型：解析器可能产出的三种事件之一
# 调用方用 isinstance() 判断类型，分别处理
ParseEvent = NarrativeDelta | TagComplete | ParseError
