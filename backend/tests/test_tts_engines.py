import pytest
from unittest.mock import MagicMock, patch

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


@pytest.mark.asyncio
async def test_edge_synthesize_returns_bytes():
    """edge engine should return non-empty bytes on success."""
    from dzmm.tts.edge_engine import synthesize as edge_synthesize

    fake_chunk_audio = {"type": "audio", "data": b"fakemp3data"}
    fake_chunk_meta = {"type": "WordBoundary", "data": {}}

    async def fake_stream():
        yield fake_chunk_meta
        yield fake_chunk_audio

    mock_communicate = MagicMock()
    mock_communicate.stream = fake_stream

    with patch("dzmm.tts.edge_engine.edge_tts.Communicate", return_value=mock_communicate):
        result = await edge_synthesize("你好世界", "zh-CN-XiaoxiaoNeural")

    assert result == b"fakemp3data"


@pytest.mark.asyncio
async def test_edge_synthesize_empty_text_returns_empty():
    from dzmm.tts.edge_engine import synthesize as edge_synthesize

    async def fake_stream():
        return
        yield  # make it an async generator

    mock_communicate = MagicMock()
    mock_communicate.stream = fake_stream

    with patch("dzmm.tts.edge_engine.edge_tts.Communicate", return_value=mock_communicate):
        result = await edge_synthesize("", "zh-CN-XiaoxiaoNeural")

    assert result == b""


def test_kokoro_model_ready_false_when_no_file(tmp_path):
    from dzmm.tts.kokoro_engine import is_model_ready
    assert is_model_ready(tmp_path) is False


def test_kokoro_model_ready_true_when_files_exist(tmp_path):
    from dzmm.tts.kokoro_engine import is_model_ready, MODEL_FILENAME, VOICES_FILENAME
    (tmp_path / MODEL_FILENAME).write_bytes(b"fake")
    (tmp_path / VOICES_FILENAME).write_bytes(b"fake")
    assert is_model_ready(tmp_path) is True


@pytest.mark.asyncio
async def test_kokoro_synthesize_returns_wav_bytes(tmp_path):
    """kokoro engine returns WAV bytes (numpy→soundfile)."""
    import numpy as np
    from dzmm.tts.kokoro_engine import synthesize as kokoro_synthesize, MODEL_FILENAME, VOICES_FILENAME

    fake_samples = np.zeros(22050, dtype=np.float32)  # 1 second silence
    fake_sample_rate = 22050

    # Create dummy model files so is_model_ready returns True
    (tmp_path / MODEL_FILENAME).write_bytes(b"fake")
    (tmp_path / VOICES_FILENAME).write_bytes(b"fake")

    mock_kokoro = MagicMock()
    mock_kokoro.create.return_value = (fake_samples, fake_sample_rate)

    with patch("dzmm.tts.kokoro_engine.Kokoro", return_value=mock_kokoro):
        result = await kokoro_synthesize("你好", "zf_xiaobei", models_dir=tmp_path)

    assert len(result) > 44  # at least WAV header (44 bytes)
    assert result[:4] == b"RIFF"  # WAV magic bytes
