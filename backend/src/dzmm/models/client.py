# ============================================================
# LLM 客户端抽象层
# ============================================================
# 【架构说明】
#   定义了与所有 LLM 交互的统一接口。
#   Ollama（本地）和 OpenAI 兼容接口各自实现这个抽象类。
#   业务代码只依赖 ModelClient，不关心底层是哪个供应商。
#
# 【为什么要封装 LLM 客户端？】
#   不封装的话，如果要把 Ollama 换成 OpenAI，需要改很多地方。
#   有了统一接口（ModelClient），只需要换掉客户端实现，
#   所有调用 ModelClient 的地方一行代码都不用改。
#   这叫"面向接口编程"（Programming to Interface），是软件设计的基本原则。
#
# 【Java 对比】
#   ModelClient 相当于 Java 的 interface（或 abstract class）。
#   Python 用 abc.ABC + @abstractmethod 实现同样的效果。
#   Pydantic 的 BaseModel 相当于 Java 的 record 或 Lombok @Data 类：
#   自动提供构造、校验、序列化，不需要写 getter/setter。
# ============================================================

from abc import ABC, abstractmethod          # ABC = Abstract Base Class（抽象基类）
from collections.abc import AsyncIterator   # 异步迭代器类型（用于类型注解）
from typing import Literal                  # 字面量类型，限制值只能是指定的几个

from pydantic import BaseModel              # 数据校验 + 自动生成 __init__ 的基类


# ── 数据模型（Pydantic）────────────────────────────────────
# 【Pydantic BaseModel 是什么？】
#   继承 BaseModel 的类会自动获得：
#   1. 类型验证：创建实例时如果类型不对会抛错（如传 int 给 str 字段）
#   2. 自动 __init__：不需要自己写 def __init__(self, role, content)
#   3. JSON 序列化：.model_dump() 输出字典，方便转成 JSON 发给 API
#
# 【Python 特点】BaseModel 字段直接写在类体里，不需要写 __init__。
# Pydantic 会自动生成构造函数、类型校验、JSON 序列化/反序列化。

class Message(BaseModel):
    # Literal["system", "user", "assistant"] → 枚举约束，只允许这三个字符串值
    # 【为什么只有三种角色？】
    #   这是 OpenAI Chat Completions API 的对话格式：
    #   - system：系统指令（GM 的角色设定，玩家看不到）
    #   - user：用户输入（玩家的行动）
    #   - assistant：LLM 的回复（GM 的叙事输出）
    #   三种角色交替出现，形成"对话历史"。
    #   LLM 读完对话历史后，续写下一条 assistant 消息。
    # 【Java 对比】相当于用 enum 限制类型，但更轻量
    role: Literal["system", "user", "assistant"]
    content: str


class GenerationParams(BaseModel):
    """LLM 生成参数。调用时可只传需要修改的字段，其余用默认值。"""
    # temperature（温度）：控制输出的随机性/创意度
    # 0=确定性输出（每次一样），1=正常随机，>1=混乱（几乎不用）
    # TRPG 叙事用 0.8 左右：有创意但不乱
    temperature: float = 0.8
    # max_tokens：单次生成的最大 token 数（token 大约等于一个词或汉字）
    # 1500 tokens ≈ 大约 1000-1200 个汉字，足够一回合的 GM 叙事
    max_tokens: int = 1500
    # top_p（核采样）：只从概率前 p% 的词中随机选
    # 与 temperature 协同工作，进一步控制输出质量
    top_p: float = 0.95
    # stop：遇到这些字符串时停止生成；None=不限制
    # 可以用来强制在某个标签后停止，避免 LLM 继续无意义输出
    stop: list[str] | None = None
    # json_mode：强制 LLM 输出合法 JSON（Ollama: format=json; OpenAI: response_format）
    # 用于 Outliner、Wizard 等需要结构化输出的 Agent
    json_mode: bool = False


class TokenUsage(BaseModel):
    """记录一次 LLM 调用消耗的 token 数（用于计费统计）。"""
    input_tokens: int = 0   # 输入 token 数（提示词长度）
    output_tokens: int = 0  # 输出 token 数（LLM 生成的内容长度）


class StreamChunk(BaseModel):
    """流式响应的单个数据块。LLM 逐字输出时，每次推送一个 StreamChunk。"""
    # delta：本次新增的文本片段
    # 可能只有一两个字（"你"、"好"）或一段词（"突然"）
    # 可能是空字符串（仅表示状态变化，如 finish_reason 出现时）
    delta: str = ""
    # finish_reason：结束原因
    # None=还没结束（继续生成中）
    # "stop"=正常结束（LLM 认为内容完整了）
    # "length"=达到 max_tokens 上限被截断
    finish_reason: str | None = None
    # usage：token 使用量，通常只在最后一个 chunk 里有值
    # 接收方累积所有 chunk 直到 usage 不为 None，才知道总消耗
    usage: TokenUsage | None = None


# ── 抽象客户端 ────────────────────────────────────────────
class ModelClient(ABC):
    """所有 LLM 客户端必须实现的接口。

    【Java 对比】
      ABC（Abstract Base Class）相当于 Java 的 abstract class。
      @abstractmethod 相当于 abstract 关键字修饰的方法。
      子类不实现 abstractmethod 则无法实例化（会抛 TypeError）。
    """
    name: str  # 子类需要设置这个类变量（标识符，用于日志，如 "ollama" 或 "deepseek"）

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        params: GenerationParams,
    ) -> AsyncIterator[StreamChunk]:
        """流式生成。子类实现为 async generator（异步生成器）。

        【重要概念：async generator（异步生成器）】
          普通函数 return 一个值就结束。
          生成器（generator）用 yield 逐个产出值，调用方用 for 循环消费。
          async generator = 异步 + 生成器：用 async for 消费，每个 yield 点都可以挂起等待 IO。
          实际上就是"分批次产出结果"，不用等全部完成再返回。

        【Java 对比】
          类似 Java 的 Iterable<StreamChunk>，但支持异步非阻塞。
          最接近的 Java 类比是 Flux<StreamChunk>（Project Reactor）或 Stream<StreamChunk>。
          在 Python 里用 `async for chunk in client.stream(...)` 消费。
        """
        ...  # 抽象方法，子类必须实现（这里的 ... 是 Python 的"pass"的等价写法）

    async def complete(
        self,
        messages: list[Message],
        params: GenerationParams,
    ) -> tuple[str, TokenUsage]:
        """阻塞式生成（等全部输出完再返回）。

        这是一个具体方法（非抽象），直接调用 stream() 收集所有片段再拼接。
        子类不需要重写，除非有更高效的非流式 API。

        【返回值 tuple 说明】
          Python 函数可以直接返回多个值，写成 (值1, 值2) 形式。
          调用方用 text, usage = await client.complete(...) 解包（"解构赋值"）。
        【Java 对比】Java 没有原生多返回值，要用 Pair/Record/自定义类。
          Python 直接用 tuple，更简洁。
        """
        parts: list[str] = []   # 收集所有 delta 片段
        usage = TokenUsage()    # 初始化 token 用量（默认 0/0）
        # async for → 消费异步迭代器，等价于 Java 的 flux.block() 收集所有元素
        async for chunk in self.stream(messages, params):
            parts.append(chunk.delta)    # 把每个文字片段收集到列表
            if chunk.usage is not None:
                usage = chunk.usage      # 最后一个 chunk 通常包含 token 用量
        return "".join(parts), usage     # 拼接所有片段，返回完整文本

    async def health_check(self) -> tuple[bool, str]:
        """向模型发一条"ok"消息，检测连接是否正常。返回 (成功?, 响应文本/错误信息)。

        用于应用启动时检测 LLM 服务是否可用，
        或者用户在 UI 里点"测试连接"按钮时调用。
        """
        try:
            text, _ = await self.complete(
                [Message(role="user", content="Reply with the single word: ok")],
                GenerationParams(max_tokens=10, temperature=0.0),  # 确定性输出，期望得到 "ok"
            )
            return True, text.strip()  # 连接成功
        except Exception as e:  # noqa: BLE001  ← 忽略"捕获宽泛异常"的 lint 警告
            # 任何异常（网络错误/超时/认证失败）都视为健康检查失败
            # type(e).__name__ 取异常类名，如 "ConnectionError"
            return False, f"{type(e).__name__}: {e}"
