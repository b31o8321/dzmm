import pytest
from dzmm.tts.voice_map import (
    edge_voice_for_archetype,
    edge_prosody_for_archetype,
    kokoro_voice_for_archetype,
    EDGE_VOICES,
    NARRATOR_EDGE_VOICE,
    NARRATOR_KOKORO_VOICE,
)


def test_edge_known_archetypes():
    assert edge_voice_for_archetype("冷酷") == "zh-CN-XiaomoNeural"
    assert edge_voice_for_archetype("温柔") == "zh-CN-XiaoxiaoNeural"
    assert edge_voice_for_archetype("活泼") == "zh-CN-XiaohanNeural"
    assert edge_voice_for_archetype("反派") == "zh-CN-YunyeNeural"
    assert edge_voice_for_archetype("导师") == "zh-CN-YunyeNeural"


def test_edge_unknown_archetype_returns_default():
    v = edge_voice_for_archetype("未知类型")
    assert v in EDGE_VOICES


def test_edge_prosody_returns_tuple():
    rate, pitch = edge_prosody_for_archetype("冷酷")
    assert rate.endswith("%")
    assert pitch.endswith("Hz")


def test_kokoro_known_archetypes():
    assert kokoro_voice_for_archetype("温柔") == "zf_xiaobei"
    assert kokoro_voice_for_archetype("活泼") == "zf_xiaoni"
    assert kokoro_voice_for_archetype("导师") == "zm_yunxi"
    assert kokoro_voice_for_archetype("反派") == "zm_yundong"


def test_kokoro_unknown_archetype_returns_default():
    v = kokoro_voice_for_archetype("未知")
    assert v in ("zf_xiaobei", "zf_xiaoni", "zm_yunxi", "zm_yundong")


def test_narrator_voices_defined():
    assert NARRATOR_EDGE_VOICE.startswith("zh-CN-")
    assert NARRATOR_KOKORO_VOICE.startswith("z")
