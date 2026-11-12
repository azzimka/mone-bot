"""ElevenLabs Text-to-Speech client with strict cost, concurrency, and stability guards."""

from __future__ import annotations

import asyncio
import logging
import re

import httpx

logger = logging.getLogger(__name__)

DEFAULT_ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"


class TTSError(RuntimeError):
    """Base error raised when speech synthesis cannot be completed."""


class TTSNotConfiguredError(TTSError):
    """Raised when ElevenLabs API key is not configured (no remote call made)."""


class TTSSynthesisError(TTSError):
    """Raised when the ElevenLabs API rejects or fails a synthesis request."""


_AUDIO_TAG_RE = re.compile(r"\[[a-zA-Z][a-zA-Z0-9 ,_-]{1,48}\]")


def strip_tts_tags(text: str) -> str:
    """Remove ElevenLabs inline [audio tags] when storing history or displaying text fallback."""
    cleaned = _AUDIO_TAG_RE.sub("", text or "")
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def prepare_text_for_tts(text: str, max_chars: int = 1300) -> str:
    """Strip Markdown/HTML noise while preserving ElevenLabs v4 [audio tags] within max_chars."""
    cleaned = re.sub(r"<think>.*?</think>", " ", text or "", flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"```.*?```", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"\*\*([^\*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"(?m)^#{1,6}\s+", "", cleaned)
    # Replace math symbols with natural spoken Russian words before TTS
    cleaned = re.sub(r"(?:≈|~=|~(?=\s*\d))", " около ", cleaned)
    cleaned = cleaned.replace("≥", " не меньше ").replace("≤", " не больше ").replace("±", " примерно ")
    # Remove decorative symbols/emojis that waste credits or sound unnatural aloud
    cleaned = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf🧠📊🔍💡🗑⬅️⚠️✅⏳🎙📝💳🎤•]+", " ", cleaned)
    cleaned = re.sub(r"[|*_~]+", " ", cleaned)
    # Remove non-tag brackets (e.g. [150 000], empty []) while keeping valid [emotion] tags
    cleaned = re.sub(
        r"\[([^\]]*)\]",
        lambda m: m.group(0) if _AUDIO_TAG_RE.fullmatch(m.group(0)) else f" {m.group(1)} ",
        cleaned,
    )
    cleaned = re.sub(r"\n+", ". ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" .")

    if not cleaned:
        return ""

    limit = max(100, int(max_chars))
    if len(cleaned) <= limit:
        return cleaned

    slice_ = cleaned[:limit]
    # Avoid cutting in the middle of an inline [audio tag]
    last_open = slice_.rfind("[")
    last_close = slice_.rfind("]")
    if last_open > last_close:
        slice_ = slice_[:last_open].rstrip()

    # Prefer ending on a sentence boundary so spoken delivery never cuts mid-thought
    for sep in (". ", "! ", "? "):
        idx = slice_.rfind(sep)
        if idx >= int(limit * 0.5):
            return slice_[: idx + 1].strip()
    space_idx = slice_.rfind(" ")
    if space_idx >= int(limit * 0.6):
        return slice_[:space_idx].rstrip(" ,;:-") + "."
    return slice_.rstrip(" ,;:-") + "."


class ElevenLabsTTSService:
    """Async, pooled ElevenLabs TTS client invoked ONLY on explicit user voice requests."""

    def __init__(
        self,
        api_key: str,
        voice_id: str = "nPczCjzI2devNBz1zQrb",
        model_id: str = "eleven_v4_turbo",
        output_format: str = "opus_48000_64",
        stability: float = 0.40,
        similarity_boost: float = 0.78,
        max_chars: int = 1300,
        max_concurrency: int = 2,
        queue_timeout: float = 20.0,
        base_url: str = DEFAULT_ELEVENLABS_BASE_URL,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.api_key = (api_key or "").strip()
        self.voice_id = (voice_id or "nPczCjzI2devNBz1zQrb").strip()
        self.model_id = (model_id or "eleven_v4_turbo").strip()
        self.output_format = (output_format or "opus_48000_64").strip()
        self.stability = max(0.0, min(1.0, float(stability)))
        self.similarity_boost = max(0.0, min(1.0, float(similarity_boost)))
        self.max_chars = max(100, int(max_chars))
        self.queue_timeout = float(queue_timeout)
        self.base_url = base_url.rstrip("/")
        self._semaphore = asyncio.Semaphore(max(1, int(max_concurrency)))
        self._owns_client = http_client is None
        self._client = http_client

    @property
    def is_configured(self) -> bool:
        """Return True only when an explicit ElevenLabs API key is present."""
        return bool(self.api_key)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or getattr(self._client, "is_closed", False):
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=25.0, write=5.0, pool=5.0),
                limits=httpx.Limits(max_connections=30, max_keepalive_connections=15),
            )
            self._owns_client = True
        return self._client

    async def close(self) -> None:
        """Close the underlying pooled HTTP client if owned by this service."""
        if self._owns_client and self._client is not None and not getattr(self._client, "is_closed", False):
            await self._client.aclose()

    async def synthesize(self, text: str, max_chars: int | None = None) -> bytes:
        """Convert prepared text into Ogg/Opus bytes suitable for Telegram send_voice.

        Never performs hidden/automatic retries so a single request cannot be double-billed.
        """
        if not self.is_configured:
            raise TTSNotConfiguredError("ELEVENLABS_API_KEY is not configured.")

        effective_limit = self.max_chars if max_chars is None else min(self.max_chars, max(100, int(max_chars)))
        spoken_text = prepare_text_for_tts(text, max_chars=effective_limit)
        if not spoken_text:
            raise ValueError("Nothing speakable remains after cleaning text for TTS.")

        url = f"{self.base_url}/text-to-speech/{self.voice_id}"
        params = {"output_format": self.output_format}
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/ogg, audio/opus, application/octet-stream",
        }
        payload = {
            "text": spoken_text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": self.stability,
                "similarity_boost": self.similarity_boost,
            },
        }

        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.queue_timeout)
        except TimeoutError as exc:
            raise TTSSynthesisError("TTS concurrency queue timed out under heavy load.") from exc

        try:
            client = self._get_client()
            # Zero automatic retries on POST to ensure no double-billing on ElevenLabs
            response = await client.post(url, params=params, headers=headers, json=payload)
            if response.status_code != 200:
                logger.warning("ElevenLabs TTS returned HTTP %s", response.status_code)
                raise TTSSynthesisError(f"ElevenLabs HTTP {response.status_code}")
            if not response.content:
                raise TTSSynthesisError("ElevenLabs returned an empty audio payload.")
            return response.content
        except httpx.HTTPError as exc:
            logger.warning("ElevenLabs network failure (%s)", type(exc).__name__)
            raise TTSSynthesisError(f"Network error: {type(exc).__name__}") from exc
        finally:
            self._semaphore.release()
