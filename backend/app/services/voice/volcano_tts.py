"""Volcano Engine (Doubao) Text-to-Speech adapter.

WebSocket bidirectional streaming TTS.
Docs: https://www.volcengine.com/docs/6561/1329505

Protocol:
  Endpoint: wss://openspeech.bytedance.com/api/v3/tts/bidirection
  Auth: X-Api-Key + X-Api-Resource-Id (new console)
  Output: PCM 24kHz 16-bit mono (or mp3/ogg_opus)
"""

from __future__ import annotations

import asyncio
import json
import struct
from typing import Optional

import websockets
from websockets.asyncio.client import ClientConnection

from app.core.config import settings

# ── Constants ────────────────────────────────────────────
WS_URL = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
RESOURCE_ID = "seed-tts-2.0"  # 豆包语音合成模型 2.0
SAMPLE_RATE = 24000
HEADER_SIZE = 4


def _build_header(
    message_type: int = 0x01,
    flags: int = 0x10,
    serialization: int = 0x01,
) -> bytes:
    protocol_version = 1
    header_size = 1
    byte0 = (protocol_version << 4) | header_size
    compression = 0x00
    byte1 = (message_type << 4) | flags
    byte2 = (serialization << 4) | compression
    byte3 = 0x00
    return struct.pack(">BBBB", byte0, byte1, byte2, byte3)


def _encode_message(event_id: int, payload: dict) -> bytes:
    header = _build_header(message_type=0x01, flags=0x10)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return header + body


# ── Adapter ──────────────────────────────────────────────

class VolcanoTTS:
    """Volcano Engine streaming text-to-speech.

    Usage:
        tts = VolcanoTTS()
        audio = await tts.synthesise("你好，欢迎参加面试")
    """

    def __init__(
        self,
        api_key: str | None = None,
        resource_id: str | None = None,
        speaker: str = "zh_female_vv_jupiter_bigtts",
    ):
        self.api_key = api_key or settings.volcano_tts_token
        self.resource_id = resource_id or RESOURCE_ID
        self.speaker = speaker
        self._ws: Optional[ClientConnection] = None

    # ── Public API ───────────────────────────────────────

    async def synthesise(self, text: str) -> bytes:
        """Convert text to PCM audio bytes."""
        if not text.strip():
            return b""

        all_audio = bytearray()
        async for chunk in self.synthesise_stream(text):
            all_audio.extend(chunk)
        return bytes(all_audio)

    async def synthesise_stream(self, text: str):
        """Stream TTS synthesis, yielding audio chunks."""
        async with websockets.connect(
            WS_URL,
            additional_headers=self._auth_headers(),
            max_size=2**24,
        ) as ws:
            self._ws = ws

            # Start session
            await self._start_session(text)
            await ws.recv()  # ACK

            # Send text
            await self._send_text(text)

            # Finish
            await self._finish_session()

            # Receive audio frames
            while True:
                try:
                    data = await asyncio.wait_for(ws.recv(), timeout=30)
                except asyncio.TimeoutError:
                    break

                if isinstance(data, bytes) and len(data) > HEADER_SIZE:
                    header = data[:HEADER_SIZE]
                    body = data[HEADER_SIZE:]
                    # Message type 0x0B = TTS audio
                    msg_type = (header[1] >> 4) & 0x0F
                    if msg_type == 0x0B and body:
                        yield body
                    elif msg_type == 0x09:  # server response (JSON)
                        try:
                            payload = json.loads(body.decode("utf-8"))
                        except Exception:
                            continue
                        if payload.get("event") == "SessionFinished":
                            break

    # ── Internal ─────────────────────────────────────────

    def _auth_headers(self) -> dict:
        return {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": self.resource_id,
        }

    async def _start_session(self, text: str):
        payload = {
            "user": {"uid": "ai-interview"},
            "event": "BidirectionalTTS",
            "req_params": {
                "text": text,
                "speaker": self.speaker,
                "audio_params": {
                    "format": "pcm",
                    "sample_rate": SAMPLE_RATE,
                    "speech_rate": 1.0,
                },
            },
        }
        await self._ws.send(_encode_message(event_id=100, payload=payload))

    async def _send_text(self, text: str):
        payload = {
            "event": "TaskRequest",
            "req_params": {"text": text},
        }
        await self._ws.send(_encode_message(event_id=200, payload=payload))

    async def _finish_session(self):
        payload = {"event": "FinishSession"}
        await self._ws.send(_encode_message(event_id=150, payload=payload))
