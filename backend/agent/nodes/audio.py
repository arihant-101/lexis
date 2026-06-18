"""
audio nodes — two nodes that wrap MCP Sarvam API calls:

  transcribe_audio : base64 WAV → text (Sarvam STT, saarika:v2)
  generate_audio   : agent_text → base64 WAV (Sarvam TTS, bulbul:v1)
"""

import time
from agent.state import AgentState
from tools.config import SARVAM_API_KEY, _has_real_key
from tools.speech import transcribe_speech, synthesize_pronunciation
from memory.working import check_rate_limit
from observability.logger import log


async def transcribe_audio(state: AgentState) -> AgentState:
    """STT node — runs only when user_audio_b64 is set and user_text is empty."""
    audio_b64 = state.get("user_audio_b64")
    if not audio_b64:
        return state  # nothing to transcribe

    user_id = state["user_id"]

    if not _has_real_key(SARVAM_API_KEY):
        log("stt_skipped", reason="missing_api_key", user_id=user_id)
        return {
            **state,
            "user_text": "",
            "agent_text": "Voice transcription needs a Sarvam API key. Type your answer for now, or add SARVAM_API_KEY to enable voice.",
        }

    # Rate-limit check (30 calls / 60s per user)
    if not check_rate_limit(user_id, "sarvam_stt"):
        log("rate_limit_hit", api="sarvam_stt", user_id=user_id)
        return {
            **state,
            "user_text": "",
            "agent_text": "You're sending voice messages too fast. Please wait a moment.",
        }

    start = time.time()
    text = transcribe_speech(audio_b64=audio_b64, language_code="en-IN")
    latency_ms = int((time.time() - start) * 1000)

    log("stt_call", latency_ms=latency_ms, transcribed_length=len(text))

    return {**state, "user_text": text}


async def generate_audio(state: AgentState) -> AgentState:
    """TTS node — converts agent_text to speech via Sarvam bulbul:v1."""
    agent_text = state.get("agent_text", "")
    if not agent_text:
        return state

    user_id = state["user_id"]

    if not _has_real_key(SARVAM_API_KEY):
        log("tts_skipped", reason="missing_api_key", user_id=user_id)
        return {**state, "agent_audio_b64": None}

    # Strip markdown for TTS
    clean_text = (
        agent_text
        .replace("**", "")
        .replace("*", "")
        .replace("✅", "")
        .replace("❌", "")
        .replace("📖", "")
        .replace("🧠", "")
        .replace("✏️", "")
        .replace("🇮🇳", "")
        .replace("⭐", "")
    )
    # Trim to 500 chars — TTS APIs have practical limits
    clean_text = clean_text[:500]

    if not check_rate_limit(user_id, "sarvam_tts"):
        log("rate_limit_hit", api="sarvam_tts", user_id=user_id)
        return state  # return text-only, no audio

    start = time.time()
    try:
        audio_b64 = synthesize_pronunciation(
            text=clean_text,
            language_code="en-IN",
            speaker="shubh",
        )
    except Exception as exc:
        log("tts_failed_text_only", error=str(exc), text_length=len(clean_text))
        return {**state, "agent_audio_b64": None}
    latency_ms = int((time.time() - start) * 1000)

    log("tts_call", latency_ms=latency_ms, text_length=len(clean_text))

    return {**state, "agent_audio_b64": audio_b64}
