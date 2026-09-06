from __future__ import annotations


def model_timeout_detail(timeout_seconds: float) -> str:
    seconds = int(timeout_seconds)
    return (
        f"模型在 {seconds} 秒内没有返回内容。"
        "当前操作未完成，也没有写入结果；"
        "请确认模型服务仍在运行，等待模型加载完成后重试，或改用更快的模型。"
    )


def model_connection_detail() -> str:
    return (
        "无法连接模型服务。当前操作未完成，也没有写入结果；"
        "请确认模型服务已启动、地址正确，且当前设备可以访问该地址后重试。"
    )


def model_invalid_response_detail() -> str:
    return (
        "模型返回了无法识别的响应。当前操作未完成，也没有写入结果；"
        "请确认模型档案的协议和地址匹配后重试。"
    )


def is_timeout_error(error: BaseException) -> bool:
    if isinstance(error, TimeoutError):
        return True
    reason = getattr(error, "reason", None)
    if isinstance(reason, BaseException) and reason is not error:
        return is_timeout_error(reason)
    detail = str(reason if reason is not None else error).casefold()
    return "timed out" in detail or "timeout" in detail
