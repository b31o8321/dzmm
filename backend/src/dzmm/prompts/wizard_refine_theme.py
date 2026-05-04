"""Wizard refine theme — expand a rough direction into a polished one-line theme."""
from dzmm.models.client import Message

_SYSTEM = """你是 TRPG 故事策划师，擅长把模糊的想法精炼成有画面感的故事主题。

# 任务
玩家给了一个粗糙的故事方向（可能只有几个词或一句话），帮他精炼成一句**有画面感、有具体细节、点出核心矛盾或氛围**的主题描述（20-60字）。

# 要求
- 直接输出那一句话，不加任何前后说明、不加引号
- 保留玩家原意，用具体细节替换抽象词汇
- 要有画面感：能让人脑海中浮现具体场景
- 点出最核心的矛盾或情感张力
"""


def build_refine_theme_messages(genre: str, rough: str) -> list[Message]:
    user = f"题材：{genre.strip() or '自定义'}\n玩家方向：{rough.strip()}\n\n精炼后的主题描述："
    return [Message(role="system", content=_SYSTEM), Message(role="user", content=user)]
