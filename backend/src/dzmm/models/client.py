# ============================================================
# LLM 客户端抽象层
# ============================================================
# 【架构说明】
#   定义了与所有 LLM 交互的统一接口。
#   Ollama（本地）和 OpenAI 兼容接口各自实现这个抽象类。
#   业务代码只依赖 ModelClient，不关心底层是哪个供应商。
#
# 【Java 对比】
#   ModelClient 相当于 Java 的 interface（或 abstract class）。
#   Python 用 abc.ABC + @abstractmethod 实现同样的效果。
#   Pydantic 的 BaseModel 相当于 Java 的 record 或 Lombok @Data 类：
#   自动提供构造、校验、序列化，不需要写 getter/setter。
# ============================================================

from abc import ABC, abstractmethod          # ABC = Abstract Base Class
from collections.abc import AsyncIterator   # 异步迭代器类型（用于类型注解）
from typing import Literal                  # 字面量类型，限制值只能是指定的几个

from pydantic import BaseModel              # 数据校验 + 自动生成 __init__ 的基类


# ── 数据模型（Pydantic）────────────────────────────────────
# 【Python 特点】BaseModel 字段直接写在类体里，不需要写 __init__。
# Pydantic 会自动生成构造函数、类型校验、JSON 序列化/反序列化。

class Message(BaseModel):
    # Literal["system", "user", "assistant"] → 枚举约束，只允许这三个字符串值
    # 【Java 对比】相当于用 enum 限制类型，但更轻量
    role: Literal["system", "user", "assistant"]
    content: str


class GenerationParams(BaseModel):
    """LLM 生成参数。调用时可只传需要修改的字段，其余用默认值。"""
    temperature: float = 0.8   # 创意度：0=确定性输出，1=随机，>1=混乱
    max_tokens: int = 1500     # 单次生成的最大 token 数
    top_p: float = 0.95        # 核采样概率阈值
    stop: list[str] | None = None  # 遇到这些字符串时停止生成；None=不限制
    json_mode: bool = False    # 强制 JSON 输出（Ollama: format=json; OpenAI: response_format）


class TokenUsage(BaseModel):
    """记录一次 LLM 调用消耗的 token 数（用于计费统计）。"""
    input_tokens: int = 0
    output_tokens: int = 0


class StreamChunk(BaseModel):
    """流式响应的单个数据块。LLM 逐字输出时，每次推送一个 StreamChunk。"""
    delta: str = ""                     # 本次新增的文本片段（可能是空字符串）
    finish_reason: str | None = None    # 结束原因：None=还没结束，"stop"=正常结束
    usage: TokenUsage | None = None     # 通常只在最后一个 chunk 里有值


# ── 抽象客户端 ────────────────────────────────────────────
class ModelClient(ABC):
    """所有 LLM 客户端必须实现的接口。

    【Java 对比】
      ABC（Abstract Base Class）相当于 Java 的 abstract class。
      @abstractmethod 相当于 abstract 关键字修饰的方法。
      子类不实现 abstractmethod 则无法实例化（会抛 TypeError）。
    """
    name: str  # 子类需要设置这个类变量（标识符，用于日志）

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        params: GenerationParams,
    ) -> AsyncIterator[StreamChunk]:
        """流式生成。子类实现为 async generator（异步生成器）。

        【重要概念：async generator】
          普通函数 return 一个值就结束。
          生成器（generator）用 yield 逐个产出值，调用方用 for 循环消费。
          async generator = 异步 + 生成器：用 async for 消费，每个 yield 点都可以挂起等待 IO。

        【Java 对比】
          类似 Java 的 Iterable<StreamChunk>，但支持异步非阻塞。
          最接近的 Java 类比是 Flux<StreamChunk>（Project Reactor）或 Stream<StreamChunk>。
        """
        ...

    async def complete(
        self,
        messages: list[Message],
        params: GenerationParams,
    ) -> tuple[str, TokenUsage]:
        """阻塞式生成（等全部输出完再返回）。

        这是一个具体方法（非抽象），直接调用 stream() 收集所有片段再拼接。
        子类不需要重写，除非有更高效的非流式 API。

        返回值是 tuple（元组）。
        【Java 对比】Python 没有 Pair/Result 类，直接用 (值1, 值2) 返回多个值，
          调用方写 text, usage = await client.complete(...) 来解包。
        """
        parts: list[str] = []
        usage = TokenUsage()
        # async for → 消费异步迭代器，等价于 Java 的 flux.block() 收集所有元素
        async for chunk in self.stream(messages, params):
            parts.append(chunk.delta)
            if chunk.usage is not None:
                usage = chunk.usage
        return "".join(parts), usage  # 拼接所有片段，返回完整文本

    async def health_check(self) -> tuple[bool, str]:
        """向模型发一条"ok"消息，检测连接是否正常。返回 (成功?, 响应文本/错误信息)。"""
        try:
            text, _ = await self.complete(
                [Message(role="user", content="Reply with the single word: ok")],
                GenerationParams(max_tokens=10, temperature=0.0),
            )
            return True, text.strip()
        except Exception as e:  # noqa: BLE001  ← 忽略"捕获宽泛异常"的 lint 警告
            # type(e).__name__ 取异常类名，如 "ConnectionError"
            return False, f"{type(e).__name__}: {e}"
