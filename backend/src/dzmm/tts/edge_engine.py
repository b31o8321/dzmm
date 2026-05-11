"""edge-tts synthesis — calls Microsoft Neural TTS (free, online)."""
# ============================================================
# Edge TTS 引擎（edge_engine.py）
# ============================================================
# 【TTS 是什么？】
#   TTS = Text-To-Speech（文字转语音）。
#   把 GM 叙事的文字转换成语音，让玩家可以"听"跑团，而不只是"看"。
#   这能大幅提升沉浸感，特别是在 NPC 对白部分（每个 NPC 用不同声音）。
#
# 【edge-tts 是什么？】
#   edge-tts 是微软 Edge 浏览器内置 TTS 的 Python 客户端库。
#   微软 Edge 的 TTS 底层是 Azure 神经网络 TTS（Neural TTS），
#   语音质量非常高（支持情感、停顿、重音等），而且**完全免费**。
#   edge-tts 库通过调用 Edge 浏览器的 WebSocket API 实现，
#   不需要 API Key，只需要有网络连接。
#   支持 100+ 种声音（包括多种中文普通话和方言声音）。
#
# 【这个函数做什么？】
#   接收一段文本 + 声音选项，返回 MP3 格式的音频二进制数据（bytes）。
#   调用方把这个 bytes 保存为文件或直接发给前端播放。
#
# 【rate 和 pitch 参数】
#   rate：语速调整，如 "+10%" 表示比正常快 10%，"-15%" 表示慢 15%
#   pitch：音调调整，如 "+3Hz" 表示音调稍高（更年轻/更轻快的感觉）
#   这两个参数让同一个声音可以表现不同的情绪状态。
#
# 【为什么用 io.BytesIO？】
#   io.BytesIO 是"内存中的文件"（In-Memory Buffer）。
#   edge-tts 的 stream() 方法每次产出一个音频数据块，
#   用 BytesIO 把所有块合并，最后 .getvalue() 得到完整的 MP3 数据。
#   不需要先写入磁盘文件再读取，更高效。
# ============================================================
import io
import edge_tts  # Microsoft Edge TTS 客户端库（pip install edge-tts）


async def synthesize(
    text: str,
    voice: str,        # 声音名称，如 "zh-CN-XiaoxiaoNeural"（小晓，女声）
    rate: str = "+0%", # 语速（相对调整）："+10%" 快，"-15%" 慢
    pitch: str = "+0Hz", # 音调（相对调整）："+3Hz" 高，"-5Hz" 低
) -> bytes:
    """Return MP3 bytes for *text* spoken with *voice*.

    rate: percent string, e.g. "+10%" or "-15%"
    pitch: Hz string, e.g. "+3Hz" or "-5Hz"
    """
    # 空文本不需要合成，直接返回空字节（避免无意义的网络请求）
    if not text.strip():
        return b""

    # 创建 TTS 通信对象（建立与 Edge TTS 服务的连接参数）
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)

    # BytesIO：内存中的字节缓冲区（类似文件，但存在内存里）
    buf = io.BytesIO()

    # 流式接收音频数据块
    # edge-tts 的 stream() 会产出多种类型的块：
    # - type="audio"：音频数据（我们需要的）
    # - type="WordBoundary"：单词边界信息（用于字幕同步，这里忽略）
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])  # 把音频数据追加到缓冲区

    # 返回完整的 MP3 数据（所有音频块合并后的二进制内容）
    return buf.getvalue()
