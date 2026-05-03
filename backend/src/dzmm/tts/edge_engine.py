"""edge-tts synthesis — calls Microsoft Neural TTS (free, online)."""
import io
import edge_tts


async def synthesize(
    text: str,
    voice: str,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> bytes:
    """Return MP3 bytes for *text* spoken with *voice*.

    rate: percent string, e.g. "+10%" or "-15%"
    pitch: Hz string, e.g. "+3Hz" or "-5Hz"
    """
    if not text.strip():
        return b""
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()
