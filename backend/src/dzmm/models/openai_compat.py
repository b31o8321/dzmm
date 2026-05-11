# ============================================================
# OpenAI 兼容接口客户端（openai_compat.py）
# ============================================================
# 【OpenAI 兼容接口是什么？】
#   OpenAI 在 2023 年发布了 Chat Completions API，成为事实标准。
#   现在很多 LLM 服务都提供"兼容 OpenAI 格式"的接口：
#   - DeepSeek、Moonshot（月之暗面）、豆包（ByteDance）
#   - 智谱 AI（GLM）、零一万物（01.AI）
#   - LM Studio（本地模型）、vLLM（自托管）
#   这些服务的 API 端点路径和请求/响应格式与 OpenAI 一致，
#   只需要换 base_url 和 api_key 就能切换使用。
#
# 【为什么要封装而不是直接用 openai Python 库？】
#   1. openai 库很重，而且默认依赖 openai 的服务，配置麻烦
#   2. 用 httpx 直接发 HTTP 请求，代码完全可控，方便调试
#   3. 可以添加自定义重试逻辑（如 429 限流重试）
#   4. 可以处理部分 API 不支持 json_mode 的情况（自动降级）
#
# 【并发信号量（Semaphore）是什么？】
#   信号量是并发控制工具，用来限制"同时运行的任务数量"。
#   比如智谱 AI 免费套餐只允许每秒 1 个请求（并发为 1）。
#   如果两个请求同时到来，第二个会等第一个完成后才开始。
#   asyncio.Semaphore(1) 就是一个"最多 1 个任务同时持有的令牌"。
#   持有令牌 = 可以发请求；没令牌 = 等待；请求完成 = 归还令牌。
#
# 【429 重试逻辑】
#   HTTP 429 = "Too Many Requests"（请求过多）
#   当 API 返回 429 时，等一段时间后重试。
#   等待时间：
#   - 如果响应头里有 Retry-After（API 告诉我们等多久），就等那么长
#   - 否则用指数退避（每次重试等待时间翻倍）：1.5s → 3s → 6s
# ============================================================

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import httpx   # 异步 HTTP 客户端库（比 requests 支持异步）

from dzmm.models.client import (
    GenerationParams,
    Message,
    ModelClient,
    StreamChunk,
    TokenUsage,
)

log = logging.getLogger(__name__)  # 获取当前模块的日志记录器

# 429 重试配置
_MAX_429_RETRIES = 3      # 最多重试 3 次（加上第一次共 4 次尝试）
_429_BASE_DELAY = 1.5     # 指数退避的基础延迟（秒）
_429_MAX_DELAY = 8.0      # 最大延迟上限（避免等太久）


def _parse_retry_after(value: str | None) -> float | None:
    """解析 HTTP 响应头里的 Retry-After 字段。

    RFC 7231 规定：Retry-After 可以是"秒数"或"HTTP 日期格式"。
    我们只处理秒数格式（云 LLM 提供商通常用这个）。
    返回 None 表示不支持/解析失败，调用方应使用指数退避。
    """
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))  # 确保不返回负数
    except (TypeError, ValueError):
        return None  # 解析失败（如日期格式），忽略，使用默认指数退避


class OpenAICompatClient(ModelClient):
    """Works for OpenAI, Doubao, Tongyi, DeepSeek, 零一万物 — any provider
    exposing an OpenAI /chat/completions-shaped endpoint."""

    def __init__(
        self,
        name: str,
        base_url: str,       # API 基础 URL，如 "https://api.deepseek.com"
        api_key: str,        # API 密钥（Bearer Token）
        model: str,          # 模型名，如 "deepseek-chat" 或 "glm-4"
        timeout: float = 60.0,           # 请求超时时间（秒）
        concurrency_gate: asyncio.Semaphore | None = None,  # 并发控制信号量
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")  # 去掉末尾的斜杠，避免 URL 拼接出现双斜杠
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        # json_mode 支持状态：None=未测试过，True=支持，False=不支持（如 LM Studio 旧版）
        # 第一次使用 json_mode 时会测试，如果失败（HTTP 400）则记为 False，
        # 之后自动跳过 json_mode，不再重复尝试（"记住失败，别再试了"）
        self._json_mode_supported: bool | None = None
        # 并发信号量：None 表示不限制并发（高端 API 通常不需要限制）
        # 设置为 asyncio.Semaphore(1) 表示同时最多 1 个请求（免费套餐常见限制）
        self._concurrency_gate = concurrency_gate

    def _build_headers(self) -> dict:
        # 构建 HTTP 请求头
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            # Bearer Token 认证方式（OpenAI 兼容 API 的标准认证方式）
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _raw_stream(
        self,
        messages: list[Message],
        params: GenerationParams,
        use_json_mode: bool,
    ) -> AsyncIterator[StreamChunk]:
        """带 429 重试的流式请求。

        【重要设计限制】
          重试只在第一个 chunk 之前才安全！
          一旦开始向调用方推送 chunk，就不能重试（重试会产生重复输出）。
          所以 mid-stream 的 429 只能作为错误上报，不重试。
          好在云 LLM 通常在请求接入时就限流，不会在流中途限流。
        """
        # 构建请求体（符合 OpenAI Chat Completions API 格式）
        payload: dict = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],  # Pydantic → dict → JSON
            "temperature": params.temperature,
            "max_tokens": params.max_tokens,
            "top_p": params.top_p,
            "stream": True,  # 开启流式输出（Server-Sent Events）
            "stream_options": {"include_usage": True},  # 在最后一个 chunk 里包含 token 用量
        }
        if params.stop:
            payload["stop"] = params.stop
        if use_json_mode:
            # 强制 JSON 输出格式（OpenAI 格式）
            payload["response_format"] = {"type": "json_object"}

        attempt = 0  # 当前重试次数（0 = 第一次尝试）
        while True:
            try:
                # 实际发送请求，逐个产出 StreamChunk
                async for chunk in self._do_request(payload):
                    yield chunk
                return  # 成功，退出循环
            except httpx.HTTPStatusError as exc:
                # 如果不是 429 或者已经重试了最大次数，重新抛出异常
                if exc.response.status_code != 429 or attempt >= _MAX_429_RETRIES:
                    raise
                # 尝试从响应头里读取 Retry-After
                retry_after = _parse_retry_after(exc.response.headers.get("Retry-After"))
                # 计算等待时间：优先用 Retry-After，其次用指数退避
                delay = retry_after if retry_after is not None else min(
                    _429_BASE_DELAY * (2 ** attempt),  # 1.5 → 3 → 6
                    _429_MAX_DELAY,                     # 最多等 8 秒
                )
                attempt += 1
                log.info(
                    "openai_compat 429 from %s (attempt %d/%d); sleeping %.1fs before retry",
                    self.base_url, attempt, _MAX_429_RETRIES, delay,
                )
                await asyncio.sleep(delay)  # 异步等待（不阻塞事件循环）

    async def _do_request(self, payload: dict) -> AsyncIterator[StreamChunk]:
        # 实际发送 HTTP 请求，解析 Server-Sent Events（SSE）流
        # SSE 格式：每行以 "data: " 开头，最后一行是 "data: [DONE]"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # 使用 client.stream() 开启流式接收（不等全部数据到才处理）
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",   # OpenAI 标准端点路径
                json=payload,
                headers=self._build_headers(),
            ) as resp:
                if resp.status_code == 429:
                    # 429 需要读完 body（释放连接），然后抛错让上层重试
                    await resp.aread()
                    resp.raise_for_status()  # 抛出 HTTPStatusError
                resp.raise_for_status()  # 其他错误（401/500 等）也抛出

                # 逐行读取 SSE 流
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue  # 跳过空行和非 data 行（SSE 协议有 comment 行等）
                    data = line[6:]  # 去掉 "data: " 前缀
                    if data == "[DONE]":
                        break  # OpenAI SSE 流的结束标志
                    try:
                        obj = json.loads(data)   # 解析 JSON
                    except json.JSONDecodeError:
                        continue  # 忽略解析失败的行（不完整的 JSON 等）

                    # 从 choices 数组里提取文字增量（delta）
                    choices = obj.get("choices") or []
                    delta = ""
                    finish = None
                    if choices:
                        # choices[0].delta.content 是本次新增的文字片段
                        delta = (choices[0].get("delta") or {}).get("content") or ""
                        finish = choices[0].get("finish_reason")  # None 或 "stop"/"length"

                    # 从顶层的 usage 字段提取 token 用量
                    # （只在最后一个 chunk 里存在，由 stream_options.include_usage 触发）
                    usage = None
                    raw_usage = obj.get("usage")
                    if raw_usage:
                        usage = TokenUsage(
                            input_tokens=raw_usage.get("prompt_tokens", 0),
                            output_tokens=raw_usage.get("completion_tokens", 0),
                        )

                    # 只有有实质内容的 chunk 才产出（避免产出全空的 chunk）
                    if delta or finish or usage:
                        yield StreamChunk(delta=delta, finish_reason=finish, usage=usage)

    async def stream(
        self,
        messages: list[Message],
        params: GenerationParams,
    ) -> AsyncIterator[StreamChunk]:
        # 如果没有并发控制信号量，直接调用内部方法
        if self._concurrency_gate is None:
            async for chunk in self._stream_inner(messages, params):
                yield chunk
            return

        # ── 并发信号量保护 ────────────────────────────────
        # 【信号量工作原理】
        #   asyncio.Semaphore(N) 相当于 N 个"令牌"。
        #   acquire()：请求一个令牌（如果没有则等待）
        #   release()：归还令牌（让下一个等待者获得）
        #
        # 【为什么用 acquire/release 而不是 async with】
        #   Python async generator 的生命周期比较复杂：
        #   - 正常迭代完成：finally 块会运行
        #   - 显式 aclose()：finally 块会运行
        #   - 被 GC 回收（GeneratorExit）：finally 块延迟运行（GC 触发时）
        #   用显式 acquire/release 加日志，可以检测"信号量泄漏"（发现 finally 没有运行）
        #
        # 【wait_t0/acquire_t0】
        #   记录等待开始时间和获取时间，用于日志和性能监控
        import time
        wait_t0 = time.monotonic()  # 等待开始时间
        await self._concurrency_gate.acquire()  # 等待获取信号量（可能阻塞）
        wait_ms = int((time.monotonic() - wait_t0) * 1000)   # 等待了多少毫秒
        acquire_t0 = time.monotonic()  # 获取到信号量的时间
        held_for_warned = False  # 是否已经警告过"持有太久"
        log.info(
            "openai_compat: gate ACQUIRED for %s (waited %dms)",
            self.base_url, wait_ms,
        )
        try:
            async for chunk in self._stream_inner(messages, params):
                # 如果信号量持有时间超过 60 秒，记录警告（可能是卡住的流）
                if not held_for_warned and (time.monotonic() - acquire_t0) > 60.0:
                    log.warning(
                        "openai_compat: gate held >60s for %s/%s — possible stuck stream",
                        self.base_url, self.model,
                    )
                    held_for_warned = True
                yield chunk
        except BaseException as e:
            # 捕获 BaseException（包括 GeneratorExit 和 CancelledError）而不只是 Exception，
            # 确保所有退出路径都能到达 finally 块释放信号量
            # 记录是什么原因导致提前退出（最常见的泄漏原因）
            log.info(
                "openai_compat: gate path exiting via %s for %s",
                type(e).__name__, self.base_url,
            )
            raise  # 重新抛出异常，不吞掉
        finally:
            # finally 块无论如何都会执行（正常结束/异常/取消）
            held_ms = int((time.monotonic() - acquire_t0) * 1000)
            self._concurrency_gate.release()  # 归还信号量令牌
            log.info(
                "openai_compat: gate RELEASED after %dms for %s",
                held_ms, self.base_url,
            )

    async def _stream_inner(
        self,
        messages: list[Message],
        params: GenerationParams,
    ) -> AsyncIterator[StreamChunk]:
        # 处理 json_mode 的自动降级逻辑
        # 如果已知不支持（_json_mode_supported is False），直接跳过 json_mode
        want_json = params.json_mode and self._json_mode_supported is not False

        if not want_json:
            # 不需要 json_mode，直接发请求
            async for chunk in self._raw_stream(messages, params, use_json_mode=False):
                yield chunk
            return

        # 尝试用 json_mode 发请求；如果服务器返回 400（不支持），自动降级
        collected: list[StreamChunk] = []  # 收集已推送的 chunk（用于判断是否 mid-stream）
        try:
            async for chunk in self._raw_stream(messages, params, use_json_mode=True):
                collected.append(chunk)
                yield chunk  # 边收边推给调用方
            # 如果到这里没有异常，说明 json_mode 被支持
            self._json_mode_supported = True
        except httpx.HTTPStatusError as exc:
            # 400 Bad Request 且还没推送任何 chunk → 服务器不支持 json_mode，降级重试
            if exc.response.status_code == 400 and not collected:
                self._json_mode_supported = False  # 记住：这个服务器不支持 json_mode
                # 不用 json_mode 重试一次
                async for chunk in self._raw_stream(messages, params, use_json_mode=False):
                    yield chunk
            else:
                raise  # 其他情况（mid-stream 错误/非 400）重新抛出
