"""Volcano Engine (Doubao) Speech-to-Text adapter.

WebSocket bidirectional streaming ASR.
Docs: https://www.volcengine.com/docs/6561/80814

Protocol:
  Endpoint: wss://openspeech.bytedance.com/api/v3/sauc/bigmodel
  Auth: X-Api-App-Id + X-Api-Access-Key + X-Api-Resource-Id
  Audio: PCM 16kHz 16-bit mono little-endian
  Binary protocol with 4-byte header
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
from typing import Optional

import websockets
from websockets.asyncio.client import ClientConnection

from app.core.config import settings

# ── Constants ────────────────────────────────────────────
WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
RESOURCE_ID = "volc.seedasr.sauc.duration"  # ASR 2.0
SAMPLE_RATE = 16000

# Binary protocol header
HEADER_SIZE = 4


def _build_header(
    message_type: int = 0x01,
    flags: int = 0x10,       # bit 2 = has event id
    serialization: int = 0x01,  # JSON
) -> bytes:
    """Build the 4-byte binary protocol header.

    Byte 0: protocol_version(4b) | header_size(4b) → 0x11
    Byte 1: message_type(4b) | flags(4b)
    Byte 2: serialization(4b) | compression(4b)
    Byte 3: reserved(8b)
    """
    protocol_version = 1
    header_size = 1  # ×4 = 4 bytes
    byte0 = (protocol_version << 4) | header_size

    compression = 0x00  # no compression
    byte1 = (message_type << 4) | flags
    byte2 = (serialization << 4) | compression
    byte3 = 0x00

    return struct.pack(">BBBB", byte0, byte1, byte2, byte3)


def _encode_message(event_id: int, payload: dict) -> bytes:
    """Encode a JSON payload with the binary header."""
    header = _build_header(message_type=0x01, flags=0x10)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return header + body


def _encode_audio(audio_data: bytes) -> bytes:
    """Encode raw audio with the binary header."""
    header = _build_header(message_type=0x02, flags=0x00)
    return header + audio_data


# ── Adapter ──────────────────────────────────────────────

class VolcanoSTT:
    """Volcano Engine streaming speech-to-text.

    Usage:
        stt = VolcanoSTT()
        async for text in stt.transcribe_stream(audio_chunks):
            if text:
                print(text)
    """

    def __init__(
        self,
        app_id: str | None = None,
        access_key: str | None = None,
        resource_id: str | None = None,
    ):
        self.app_id = app_id or settings.volcano_stt_app_id
        self.access_key = access_key or settings.volcano_stt_token
        self.resource_id = resource_id or RESOURCE_ID
        self._ws: Optional[ClientConnection] = None
        self._session_id: str = ""
        self._event_id = 100
        self._full_text = ""

    # ── Public API ───────────────────────────────────────

    async def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> str:
        """One-shot transcription of a complete audio buffer."""
        chunks = [audio_data[i:i+640] for i in range(0, len(audio_data), 640)]
        result = ""
        async for text in self.transcribe_stream(chunks, sample_rate):
            if text:
                result = text  # keep the latest (final) result
        return result

    async def transcribe_stream(self, audio_chunks, sample_rate: int = 16000):
        """Stream audio chunks and yield partial/final transcription text."""
        self._full_text = ""

        async with websockets.connect(
            WS_URL,
            additional_headers=self._auth_headers(),
            max_size=2**24,
        ) as ws:
            self._ws = ws

            # Start session
            await self._start_session()
            resp = await self._recv_response()
            # Wait for session ready

            # Send audio chunks
            for chunk in audio_chunks:
                await ws.send(_encode_audio(chunk))
                await asyncio.sleep(0.02)  # ~20ms per chunk

            # Finish session
            await self._finish_session()

            # Read results
            while True:
                try:
                    text = await self._recv_response()
                    if text is not None:
                        yield text
                except Exception:
                    break

    # ── Internal ─────────────────────────────────────────

    def _auth_headers(self) -> dict:
        return {
            "X-Api-App-Id": self.app_id,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": self.resource_id,
        }

    async def _start_session(self):
        payload = {
            "user": {"uid": f"interview-{int(time.time())}"},
            "audio": {
                "format": "pcm",
                "sample_rate": SAMPLE_RATE,
                "channels": 1,
                "codec": "raw",
            },
            "request": {
                "model_name": "bigmodel",
                "enable_punctuation": True,
                "enable_itn": True,
            },
        }
        await self._ws.send(_encode_message(event_id=100, payload=payload))

    async def _finish_session(self):
        payload = {"event": "FinishSession"}
        await self._ws.send(_encode_message(event_id=150, payload=payload))

    async def _recv_response(self) -> Optional[str]:
        """Receive a binary message and decode it. Returns text if ASR result, None otherwise."""
        try:
            data = await asyncio.wait_for(self._ws.recv(), timeout=30)
        except asyncio.TimeoutError:
            return None

        if isinstance(data, bytes) and len(data) > HEADER_SIZE:
            header = data[:HEADER_SIZE]
            body = data[HEADER_SIZE:]
            try:
                payload = json.loads(body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None

            # ASR result event (451)
            if payload.get("event") == "ASRResponse":
                result = payload.get("payload_msg", {}).get("result", "")
                is_interim = payload.get("payload_msg", {}).get("is_interim", False)
                if result and not is_interim:
                    self._full_text = result
                    return result
                if result and is_interim:
                    return None  # partial result, wait for final

            # ASR ended (459)
            if payload.get("event") == "ASREnded":
                return self._full_text

        return None
