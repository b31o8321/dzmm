# ============================================================
# activity_log.py — 结构化活动日志（v0.1.7）
# ============================================================
# 【什么是活动日志（activity log）？】
#   游戏运行时会产生两种日志：
#   1. dzmm.log（由 Python logging 写入）：给开发者看的文字日志，
#      记录模块级别的调试信息，格式不固定
#   2. activity.jsonl（本文件写入）：机器可读的结构化事件流，
#      每行一个 JSON 对象，前端可以直接读取和渲染
#
# 【记录哪些事件？】
#   - turn_start / turn_end：每回合的开始/结束，含耗时、token 数、标签数
#   - llm_error / parser_error / state_apply_error：各类错误
#   - screenplay_generate_start / end：剧本生成的开始/结束
#   - ner_fallback_created：NER 启发式自动创建了一个新 NPC
#
# 【谁使用活动日志？】
#   - service/game.run_turn：记录每回合的 LLM 调用和解析结果
#   - service/screenplay.generate_screenplay：记录剧本生成耗时
#   - api/routes_sessions.activity：GET 接口，前端定期拉取最新事件
#
# 【文件格式示例】
#   {"ts":"2026-05-01T12:34:56.789","session_id":7,"kind":"turn_end",
#    "duration_ms":3421,"tokens_in":7800,"tokens_out":420}
#
# 【日志轮转】
#   文件超过 5MB 时，把旧文件重命名为 activity.jsonl.1，开始新文件
#   （简单的单备份轮转，适合小规模本地应用）
# ============================================================
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from dzmm.config import APP_DIR  # 应用数据目录（~/.dzmm/）

log = logging.getLogger(__name__)

_ACTIVITY_PATH = Path(APP_DIR) / "activity.jsonl"  # 日志文件路径
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB，超出则触发轮转


def _ensure_dir() -> None:
    # 确保日志文件所在目录存在（首次运行时可能尚未创建）
    try:
        _ACTIVITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # 如果创建失败（权限问题等），静默忽略


def _maybe_rotate() -> None:
    # 检查文件大小，超过 5MB 时做一次日志轮转
    # 轮转策略：旧文件 → activity.jsonl.1（只保留 1 个备份，更简单）
    try:
        if _ACTIVITY_PATH.exists() and _ACTIVITY_PATH.stat().st_size > _MAX_BYTES:
            old = _ACTIVITY_PATH.with_suffix(".jsonl.1")
            if old.exists():
                old.unlink()  # 删除上一个备份
            os.rename(_ACTIVITY_PATH, old)  # 当前文件变成备份
            # 下一次 log_event 调用会重新创建 activity.jsonl
    except OSError as e:
        log.warning("activity log rotation failed: %s", e)


def log_event(session_id: int | None, kind: str, **payload: Any) -> None:
    # 向活动日志追加一条结构化事件
    #
    # 参数：
    #   session_id: 哪个游戏存档（可以为 None，如应用级事件）
    #   kind:       事件类型（如 "turn_end"、"llm_error"）
    #   **payload:  其他任意键值对（如 duration_ms=3421, tokens_in=7800）
    #
    # 设计原则：「尽力而为」——写入失败只记警告，绝不因为日志问题而中断游戏
    _ensure_dir()
    _maybe_rotate()
    record = {
        "ts": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="milliseconds"),
        # replace(tzinfo=None)：去掉时区标记，让时间戳更简洁（+00:00 → 无后缀）
        "session_id": session_id,
        "kind": kind,
        **payload,  # 把调用者传入的额外字段展开合并到记录里
    }
    try:
        # "a" 模式：追加写入（不覆盖已有内容）
        with _ACTIVITY_PATH.open("a", encoding="utf-8") as f:
            # ensure_ascii=False：让中文字符直接写入，不转义为 \u xxxx
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("activity log write failed: %s", e)  # 写入失败只记警告


def read_recent(session_id: int | None = None, limit: int = 200) -> list[dict]:
    # 读取最近的活动日志事件（最新的在前）
    #
    # 参数：
    #   session_id: 若指定，只返回该存档的事件；若为 None，返回所有事件
    #   limit:      最多返回多少条（默认 200 条）
    #
    # 实现：读取整个文件，在内存里过滤（5MB 以内这么做够用，比维护索引简单）
    if not _ACTIVITY_PATH.exists():
        return []
    out: list[dict] = []
    try:
        with _ACTIVITY_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)  # 每行解析成 Python dict
                except json.JSONDecodeError:
                    continue  # 损坏的行跳过
                # 按 session_id 过滤（如果调用者传了 session_id 参数）
                if session_id is not None and rec.get("session_id") != session_id:
                    continue
                out.append(rec)
    except OSError as e:
        log.warning("activity log read failed: %s", e)
        return []
    out.reverse()       # 反转为最新的在前
    return out[:limit]  # 截取前 limit 条
