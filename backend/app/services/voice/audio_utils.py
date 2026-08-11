"""Audio utilities — PCM/WAV conversion for browser-compatible playback."""

import struct


def pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, bits_per_sample: int = 16) -> bytes:
    """Wrap raw PCM audio with a 44-byte WAV/RIFF header.

    Browsers require WAV format for <audio> elements. Raw PCM bytes without
    a WAV header will not decode. This function prepends the header without
    re-encoding — it's just a 44-byte struct + the original data.
    """
    if not pcm_data:
        return b""

    byte_rate = sample_rate * channels * (bits_per_sample // 8)
    block_align = channels * (bits_per_sample // 8)
    data_size = len(pcm_data)
    riff_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", riff_size, b"WAVE",        # RIFF chunk
        b"fmt ", 16, 1, channels,            # fmt chunk (PCM)
        sample_rate, byte_rate, block_align, bits_per_sample,
        b"data", data_size,                  # data chunk
    )
    return header + pcm_data
