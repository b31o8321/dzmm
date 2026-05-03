"""Archetype → TTS voice/prosody mappings for edge-tts and kokoro-onnx."""

# edge-tts: archetype → (voice_name, rate_adjust, pitch_adjust_hz)
_EDGE_MAP: dict[str, tuple[str, str, str]] = {
    "导师":  ("zh-CN-YunyeNeural",    "-5%",  "-2Hz"),
    "盟友":  ("zh-CN-YunxiNeural",    "+0%",  "+0Hz"),
    "反派":  ("zh-CN-YunyeNeural",    "+5%",  "-5Hz"),
    "神秘人":("zh-CN-XiaoqiuNeural",  "-15%", "-3Hz"),
    "商人":  ("zh-CN-YunyangNeural",  "+8%",  "+0Hz"),
    "守卫":  ("zh-CN-YunfengNeural",  "+0%",  "-1Hz"),
    "平民":  ("zh-CN-XiaozhenNeural", "+0%",  "+0Hz"),
    "智者":  ("zh-CN-XiaoqiuNeural",  "-20%", "-4Hz"),
    "冷酷":  ("zh-CN-XiaomoNeural",   "-10%", "-3Hz"),
    "温柔":  ("zh-CN-XiaoxiaoNeural", "-5%",  "+2Hz"),
    "活泼":  ("zh-CN-XiaohanNeural",  "+15%", "+3Hz"),
    "邪恶":  ("zh-CN-YunyeNeural",    "+0%",  "-6Hz"),
    "儿童":  ("zh-CN-XiaoshuangNeural","+15%","+5Hz"),
    "长老":  ("zh-CN-XiaoqiuNeural",  "-20%", "-5Hz"),
    "武将":  ("zh-CN-YunfengNeural",  "+5%",  "-2Hz"),
    "贵族":  ("zh-CN-YunyangNeural",  "-5%",  "+0Hz"),
}

_EDGE_DEFAULT = ("zh-CN-YunxiNeural", "+0%", "+0Hz")
NARRATOR_EDGE_VOICE = "zh-CN-XiaoxiaoNeural"  # audiobook-style narrator

# All distinct edge voice names (for validation/listing)
EDGE_VOICES: list[str] = sorted({v for v, _, _ in _EDGE_MAP.values()} | {NARRATOR_EDGE_VOICE})

# kokoro-onnx: archetype → voice (zh voices: zf_xiaobei, zf_xiaoni, zm_yunxi, zm_yundong)
_KOKORO_MAP: dict[str, str] = {
    "导师":   "zm_yunxi",
    "盟友":   "zm_yunxi",
    "反派":   "zm_yundong",
    "神秘人": "zm_yundong",
    "商人":   "zm_yunxi",
    "守卫":   "zm_yundong",
    "平民":   "zf_xiaobei",
    "智者":   "zm_yunxi",
    "冷酷":   "zf_xiaobei",
    "温柔":   "zf_xiaobei",
    "活泼":   "zf_xiaoni",
    "邪恶":   "zm_yundong",
    "儿童":   "zf_xiaoni",
    "长老":   "zm_yunxi",
    "武将":   "zm_yundong",
    "贵族":   "zf_xiaobei",
}

_KOKORO_DEFAULT = "zf_xiaobei"
NARRATOR_KOKORO_VOICE = "zf_xiaobei"

# CosyVoice-300M-Instruct: archetype → speaker preset
# Available: 中文女 中文男 粤语女 日语男 英文女 英文男 韩语女
_COSYVOICE_MAP: dict[str, str] = {
    "导师":   "中文男",
    "盟友":   "中文男",
    "反派":   "中文男",
    "神秘人": "中文男",
    "商人":   "中文男",
    "守卫":   "中文男",
    "平民":   "中文女",
    "智者":   "中文男",
    "冷酷":   "中文女",
    "温柔":   "中文女",
    "活泼":   "中文女",
    "邪恶":   "中文男",
    "儿童":   "中文女",
    "长老":   "中文男",
    "武将":   "中文男",
    "贵族":   "中文女",
}

_COSYVOICE_DEFAULT = "中文女"
NARRATOR_COSYVOICE_VOICE = "中文女"


def edge_voice_for_archetype(archetype: str) -> str:
    return _EDGE_MAP.get(archetype, _EDGE_DEFAULT)[0]


def edge_prosody_for_archetype(archetype: str) -> tuple[str, str]:
    """Return (rate, pitch_hz) for edge-tts prosody."""
    entry = _EDGE_MAP.get(archetype, _EDGE_DEFAULT)
    return entry[1], entry[2]


def kokoro_voice_for_archetype(archetype: str) -> str:
    return _KOKORO_MAP.get(archetype, _KOKORO_DEFAULT)


def cosyvoice_voice_for_archetype(archetype: str) -> str:
    return _COSYVOICE_MAP.get(archetype, _COSYVOICE_DEFAULT)
