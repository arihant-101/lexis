"""
Sarvam speech tools: TTS, STT, and English→Hindi translation.

Moved out of the old `mcp/server.py`. Each tool degrades gracefully to an empty
result when no API key is configured, and logs latency via `log_tool_call`.
"""

import base64
import time

import httpx

from observability.logger import log, log_tool_call
from tools.config import SARVAM_API_KEY, _has_real_key
from tools.registry import register


@register(description="Synthesize speech with Sarvam TTS; returns base64 WAV audio.")
def synthesize_pronunciation(
    text: str,
    language_code: str = "en-IN",
    speaker: str = "shubh",
) -> str:
    """
    Synthesize speech using Sarvam TTS API. Returns base64-encoded WAV audio.

    Args:
        text: Text to synthesize (word or sentence)
        language_code: BCP-47 code — "en-IN" for English, "hi-IN" for Hindi
        speaker: Sarvam speaker name
    """
    start = time.time()
    if not _has_real_key(SARVAM_API_KEY):
        log("sarvam_tts_skipped", reason="missing_api_key", chars=len(text))
        return ""

    try:
        resp = httpx.post(
            "https://api.sarvam.ai/text-to-speech",
            headers={"api-subscription-key": SARVAM_API_KEY},
            json={
                "text": text,
                "target_language_code": language_code,
                "speaker": speaker,
                "model": "bulbul:v3",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        audio_b64 = data.get("audios", [None])[0] or data.get("audio") or data.get("data", {}).get("audio")
        if not audio_b64:
            raise ValueError("Sarvam TTS response did not include audio data")
        log_tool_call("synthesize_pronunciation", int((time.time() - start) * 1000),
                      chars=len(text), language=language_code)
        return audio_b64
    except httpx.HTTPStatusError as e:
        log_tool_call("synthesize_pronunciation", int((time.time() - start) * 1000),
                      success=False, error=str(e), status=e.response.status_code)
        raise


@register(description="Transcribe base64 WAV audio with Sarvam STT; returns text.")
def transcribe_speech(audio_b64: str, language_code: str = "en-IN") -> str:
    """
    Transcribe speech using Sarvam STT API. Returns transcribed text.

    Args:
        audio_b64: Base64-encoded WAV audio (16kHz mono PCM)
        language_code: Expected spoken language
    """
    start = time.time()
    if not _has_real_key(SARVAM_API_KEY):
        log("sarvam_stt_skipped", reason="missing_api_key")
        return ""

    try:
        audio_bytes = base64.b64decode(audio_b64)
        resp = httpx.post(
            "https://api.sarvam.ai/speech-to-text",
            headers={"api-subscription-key": SARVAM_API_KEY},
            files={"file": ("audio.wav", audio_bytes, "audio/wav")},
            data={"language_code": language_code, "model": "saarika:v2"},
            timeout=15.0,
        )
        resp.raise_for_status()
        transcript = resp.json()["transcript"]
        log_tool_call("transcribe_speech", int((time.time() - start) * 1000),
                      audio_bytes=len(audio_bytes))
        return transcript
    except httpx.HTTPStatusError as e:
        log_tool_call("transcribe_speech", int((time.time() - start) * 1000),
                      success=False, error=str(e), status=e.response.status_code)
        raise


@register(description="Translate English text to Hindi with Sarvam Translate.")
def translate_to_hindi(text: str) -> str:
    """
    Translate English text to Hindi using Sarvam Translate API.
    Used to show word meanings in Hindi for better retention.

    Args:
        text: English definition or example sentence
    """
    start = time.time()
    if not _has_real_key(SARVAM_API_KEY):
        log("sarvam_translate_skipped", reason="missing_api_key", chars=len(text))
        return ""

    try:
        resp = httpx.post(
            "https://api.sarvam.ai/translate",
            headers={"api-subscription-key": SARVAM_API_KEY},
            json={
                "input": text,
                "source_language_code": "en-IN",
                "target_language_code": "hi-IN",
                "model": "mayura:v1",
                "enable_preprocessing": True,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        translated = resp.json()["translated_text"]
        log_tool_call("translate_to_hindi", int((time.time() - start) * 1000), chars=len(text))
        return translated
    except httpx.HTTPStatusError as e:
        log_tool_call("translate_to_hindi", int((time.time() - start) * 1000),
                      success=False, error=str(e), status=e.response.status_code)
        raise
