"""
Intake Agent — SihaLink (Google ADK)
Accepts clinical intake from three sources:
  1. Web forms     — structured JSON from the Angular frontend
  2. Telegram      — text messages and audio from CHVs via the bot
  3. Agent-to-agent — JSON calls from other SihaLink agents

All text/audio input is routed through the Multilingual Language Agent first,
which detects the language, translates to English, and extracts clinical keywords
before clinical extraction and triage classification.

Progress is logged at every step so the caller always knows what is happening.

Supported languages: Dholuo, Swahili, Kikuyu, Somali, Luhya, Kamba,
                     Mijikenda, Meru, Turkana, Kalenjin, English
"""

import os
import json
import base64
import asyncio
import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Literal

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.agents.run_config import RunConfig
from google.adk.agents.live_request_queue import LiveRequestQueue, LiveRequest
from google.genai import types as genai_types

from .language_agent import interpret_multilingual_input, get_clarification_prompt

logger = logging.getLogger("SihaLink-Intake")

# ---------------------------------------------------------------------------
# WHO IDSR Syndrome Categories
# ---------------------------------------------------------------------------
IDSR_SYNDROMES = [
    # ── Core WHO IDSR categories ──────────────────────────────────────────────
    "acute_watery_diarrhea", "acute_bloody_diarrhea", "acute_febrile_illness",
    "acute_respiratory_infection", "acute_rash_with_fever", "malnutrition_severe",
    "neonatal_tetanus", "meningitis", "viral_hemorrhagic_fever",
    "cholera", "measles",
    # ── Additional high-priority diseases ────────────────────────────────────
    "malaria", "tuberculosis", "pneumonia", "typhoid", "dengue",
    "yellow_fever", "ebola", "covid_19", "poliomyelitis", "hiv_aids",
    "unknown",
]


# ---------------------------------------------------------------------------
# Intake source enum — used in logs and returned metadata
# ---------------------------------------------------------------------------
class IntakeSource(str, Enum):
    WEB_FORM  = "web_form"
    TELEGRAM  = "telegram"
    AGENT     = "agent"
    AUDIO     = "audio"


# ---------------------------------------------------------------------------
# Progress logger — emits structured log lines the frontend/Telegram can stream
# ---------------------------------------------------------------------------

import concurrent.futures

_log_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

def _log(session_id: str, step: str, detail: str, level: str = "INFO") -> None:
    """Emit a structured progress log line visible to callers."""
    icons = {
        "INFO":    "🔵",
        "SUCCESS": "✅",
        "WARNING": "⚠️",
        "ERROR":   "❌",
    }
    icon = icons.get(level, "🔵")
    logger.info("[%s] %s [%s] %s", session_id[:8], icon, step, detail)
    
    try:
        from agents.data.agent import insert_agent_log
        _log_executor.submit(
            insert_agent_log, "Intake Agent", step, detail, level, session_id
        )
    except Exception as exc:
        logger.debug("Background log persist failed: %s", exc)


# ---------------------------------------------------------------------------
# Tool: extract from web form (structured input — fastest path)
# ---------------------------------------------------------------------------

def extract_from_form(form_data: dict, session_id: str) -> dict:
    """
    Extract clinical data from a structured web form submission.

    The form provides pre-filled fields (age, sex, symptoms checkboxes,
    vital signs, free-text chief complaint). The language agent normalises
    any free-text fields that may be in a local language before extraction.

    Args:
        form_data:  Dict from the Angular frontend with keys:
                    chief_complaint, symptoms (list), age_value, age_unit,
                    sex, temperature_c, respiratory_rate, duration_days,
                    language_hint (optional).
        session_id: Unique encounter session ID.

    Returns:
        Standard clinical extraction dict.
    """
    _log(session_id, "FORM_INTAKE", "📋 Received web form submission")
    start = time.time()

    chief_complaint = form_data.get("chief_complaint", "")
    language_hint   = form_data.get("language_hint")

    # Run language agent on the free-text chief complaint if present
    translation = None
    if chief_complaint:
        _log(session_id, "LANGUAGE", f"🌍 Detecting language of chief complaint...")
        translation = interpret_multilingual_input(
            chief_complaint,
            source_language=language_hint,
        )
        detected_lang = translation.get("detected_language", "unknown")
        confidence    = translation.get("confidence", 0)
        _log(session_id, "LANGUAGE",
             f"Detected: {detected_lang} ({confidence:.0%} confidence)", "SUCCESS")

        if translation.get("needs_clarification"):
            q = translation.get("clarification_question", "")
            _log(session_id, "LANGUAGE", f"Clarification needed: {q}", "WARNING")

    # Build normalised description from form fields + translated complaint
    translated_complaint = (
        translation["english_translation"] if translation else chief_complaint
    )
    symptoms_list = form_data.get("symptoms", [])
    description = (
        f"Chief complaint: {translated_complaint}. "
        f"Symptoms: {', '.join(symptoms_list) if symptoms_list else 'none listed'}. "
        f"Duration: {form_data.get('duration_days', '?')} days. "
        f"Patient Contacts: {form_data.get('patient_contacts', 'none listed')}."
    )

    _log(session_id, "EXTRACTION", "🧠 Running clinical extraction on form data...")
    result = _extract_from_text(description, session_id)

    # Overlay structured form fields — these are more reliable than LLM extraction
    if form_data.get("age_value"):
        result["age"] = {
            "value": form_data["age_value"],
            "unit":  form_data.get("age_unit", "years"),
        }
    if form_data.get("sex"):
        result["sex"] = form_data["sex"]
    if form_data.get("temperature_c"):
        result.setdefault("vital_signs", {})["temperature_c"] = form_data["temperature_c"]
    if form_data.get("respiratory_rate"):
        result.setdefault("vital_signs", {})["respiratory_rate"] = form_data["respiratory_rate"]
    if form_data.get("duration_days"):
        result["duration_days"] = form_data["duration_days"]

    result["source"]             = IntakeSource.WEB_FORM
    result["session_id"]         = session_id
    result["processing_ms"]      = round((time.time() - start) * 1000)
    result["detected_language"]  = translation["detected_language"] if translation else "English"
    result["original_complaint"] = chief_complaint

    _log(session_id, "EXTRACTION",
         f"Syndrome: {result.get('syndrome')} | Triage: {result.get('triage_color')} "
         f"| Confidence: {result.get('confidence', 0):.0%}", "SUCCESS")
    _log(session_id, "FORM_INTAKE",
         f"✅ Form intake complete in {result['processing_ms']}ms", "SUCCESS")
    return result


# ---------------------------------------------------------------------------
# Tool: extract from Telegram (text message or audio note from a CHV)
# ---------------------------------------------------------------------------

def extract_from_telegram(
    message_text: Optional[str],
    audio_base64: Optional[str],
    chw_id: str,
    session_id: str,
    telegram_language_hint: Optional[str] = None,
) -> dict:
    """
    Extract clinical data from a Telegram message sent by a CHV.

    Handles:
    - Plain text messages (any Kenyan language or English)
    - Voice notes (base64-encoded audio, transcribed then translated)
    - Mixed messages (text + caption on a voice note)

    Args:
        message_text:           Raw text message from the CHV, or None.
        audio_base64:           Base64 WAV/OGG voice note, or None.
        chw_id:                 Telegram user ID or CHW registry ID.
        session_id:             Unique encounter session ID.
        telegram_language_hint: Language preference stored in CHW profile.

    Returns:
        Standard clinical extraction dict with source='telegram'.
    """
    _log(session_id, "TELEGRAM_INTAKE",
         f"📱 Received Telegram message from CHW {chw_id[:12]}")
    start = time.time()

    # ── Step 1: get raw text (from voice note or direct text) ──────────────
    if audio_base64:
        _log(session_id, "AUDIO", "🎙️ Voice note detected — transcribing audio...")
        raw_text = _transcribe_audio(audio_base64, session_id)
        if not raw_text:
            _log(session_id, "AUDIO", "Transcription empty — falling back to audio extraction", "WARNING")
            result = _extract_from_audio(audio_base64, session_id)
            result["source"]    = IntakeSource.TELEGRAM
            result["chw_id"]    = chw_id
            result["session_id"] = session_id
            result["processing_ms"] = round((time.time() - start) * 1000)
            return result
        _log(session_id, "AUDIO", f"Transcript: '{raw_text[:80]}...'", "SUCCESS")
        # Append any accompanying caption
        if message_text:
            raw_text = f"{raw_text} {message_text}"
    elif message_text:
        raw_text = message_text
        _log(session_id, "TELEGRAM_INTAKE", f"Text message: '{raw_text[:80]}'")
    else:
        _log(session_id, "TELEGRAM_INTAKE", "Empty message received", "WARNING")
        return {
            "error": "empty_message",
            "source": IntakeSource.TELEGRAM,
            "chw_id": chw_id,
            "session_id": session_id,
        }

    # ── Step 2: language detection + translation ───────────────────────────
    _log(session_id, "LANGUAGE", f"🌍 Detecting language...")
    translation = interpret_multilingual_input(
        raw_text,
        source_language=telegram_language_hint,
        context=f"Telegram message from CHW {chw_id}",
    )
    detected_lang = translation.get("detected_language", "unknown")
    confidence    = translation.get("confidence", 0)
    _log(session_id, "LANGUAGE",
         f"Detected: {detected_lang} ({confidence:.0%} confidence)", "SUCCESS")

    if translation.get("needs_clarification"):
        question = translation.get("clarification_question", "")
        _log(session_id, "LANGUAGE",
             f"Asking clarification in {detected_lang}: {question}", "WARNING")

    english_text = translation.get("english_translation", raw_text)

    # ── Step 3: clinical extraction on English text ────────────────────────
    _log(session_id, "EXTRACTION", "🧠 Running clinical extraction...")
    result = _extract_from_text(english_text, session_id)

    result["source"]              = IntakeSource.TELEGRAM
    result["chw_id"]              = chw_id
    result["session_id"]          = session_id
    result["detected_language"]   = detected_lang
    result["original_text"]       = raw_text
    result["english_translation"] = english_text
    result["processing_ms"]       = round((time.time() - start) * 1000)

    if translation.get("needs_clarification"):
        result["clarification_needed"]   = True
        result["clarification_question"] = translation.get("clarification_question")

    _log(session_id, "EXTRACTION",
         f"Syndrome: {result.get('syndrome')} | Triage: {result.get('triage_color')} "
         f"| Confidence: {result.get('confidence', 0):.0%}", "SUCCESS")
    _log(session_id, "TELEGRAM_INTAKE",
         f"✅ Telegram intake complete in {result['processing_ms']}ms", "SUCCESS")
    return result


# ---------------------------------------------------------------------------
# Tool: extract from agent-to-agent call (pre-structured JSON)
# ---------------------------------------------------------------------------

def extract_from_agent(
    agent_payload: dict,
    source_agent: str,
    session_id: str,
) -> dict:
    """
    Process a clinical intake payload sent by another SihaLink agent.

    The calling agent may send:
    - A partially-filled clinical JSON (e.g., surveillance agent forwarding a case)
    - Raw text in any language
    - A pre-extracted dict that needs triage classification only

    Args:
        agent_payload:  Dict from the calling agent. May contain:
                        text (str), audio_base64 (str), extracted (dict),
                        language (str), context (str).
        source_agent:   Name of the calling agent (e.g., 'surveillance_agent').
        session_id:     Unique encounter session ID.

    Returns:
        Standard clinical extraction dict with source='agent'.
    """
    _log(session_id, "AGENT_INTAKE",
         f"🤖 Received intake from agent: {source_agent}")
    start = time.time()

    # ── Case 1: already-extracted clinical dict — just validate + triage ──
    if "extracted" in agent_payload and isinstance(agent_payload["extracted"], dict):
        _log(session_id, "AGENT_INTAKE", "Pre-extracted data received — validating triage...")
        result = dict(agent_payload["extracted"])
        result = _ensure_triage(result, session_id)
        result["source"]        = IntakeSource.AGENT
        result["source_agent"]  = source_agent
        result["session_id"]    = session_id
        result["processing_ms"] = round((time.time() - start) * 1000)
        _log(session_id, "AGENT_INTAKE",
             f"✅ Agent intake validated: triage={result.get('triage_color')}", "SUCCESS")
        return result

    # ── Case 2: raw text from another agent ───────────────────────────────
    raw_text = agent_payload.get("text", "")
    audio_b64 = agent_payload.get("audio_base64", "")
    language_hint = agent_payload.get("language")
    context = agent_payload.get("context", f"Forwarded by {source_agent}")

    if audio_b64 and not raw_text:
        _log(session_id, "AUDIO", "🎙️ Audio payload from agent — transcribing...")
        raw_text = _transcribe_audio(audio_b64, session_id) or ""

    if not raw_text:
        _log(session_id, "AGENT_INTAKE", "Empty payload from agent", "WARNING")
        return {
            "error": "empty_payload",
            "source": IntakeSource.AGENT,
            "source_agent": source_agent,
            "session_id": session_id,
        }

    # ── Language detection + translation ──────────────────────────────────
    _log(session_id, "LANGUAGE", "🌍 Detecting language of agent payload...")
    translation = interpret_multilingual_input(raw_text, language_hint, context)
    detected_lang = translation.get("detected_language", "unknown")
    _log(session_id, "LANGUAGE",
         f"Detected: {detected_lang} ({translation.get('confidence', 0):.0%})", "SUCCESS")

    english_text = translation.get("english_translation", raw_text)

    # ── Clinical extraction ────────────────────────────────────────────────
    _log(session_id, "EXTRACTION", "🧠 Running clinical extraction on agent payload...")
    result = _extract_from_text(english_text, session_id)

    result["source"]              = IntakeSource.AGENT
    result["source_agent"]        = source_agent
    result["session_id"]          = session_id
    result["detected_language"]   = detected_lang
    result["original_text"]       = raw_text
    result["english_translation"] = english_text
    result["processing_ms"]       = round((time.time() - start) * 1000)

    _log(session_id, "EXTRACTION",
         f"Syndrome: {result.get('syndrome')} | Triage: {result.get('triage_color')} "
         f"| Confidence: {result.get('confidence', 0):.0%}", "SUCCESS")
    _log(session_id, "AGENT_INTAKE",
         f"✅ Agent intake complete in {result['processing_ms']}ms", "SUCCESS")
    return result


# ---------------------------------------------------------------------------
# Tool: extract from raw audio (original path — still supported for live sessions)
# ---------------------------------------------------------------------------

def extract_clinical_data(audio_base64: str, session_id: str) -> dict:
    """
    Extract structured clinical data from a base64-encoded audio recording.
    Supports multilingual input — audio is transcribed, translated, then extracted.

    Args:
        audio_base64: Base64-encoded WAV or WebM audio from the CHV recording.
        session_id:   Unique encounter session identifier.

    Returns:
        Standard clinical extraction dict.
    """
    _log(session_id, "AUDIO_INTAKE", "🎙️ Processing audio recording...")
    start = time.time()

    if not audio_base64:
        _log(session_id, "AUDIO_INTAKE", "No audio provided — using mock extraction", "WARNING")
        return _mock_extraction()

    try:
        audio_bytes = base64.b64decode(audio_base64)
    except Exception:
        _log(session_id, "AUDIO_INTAKE", "Invalid base64 audio data", "ERROR")
        return _mock_extraction()

    if not audio_bytes:
        _log(session_id, "AUDIO_INTAKE", "Empty audio buffer", "WARNING")
        return _mock_extraction()

    if not os.getenv("GEMINI_API_KEY"):
        _log(session_id, "AUDIO_INTAKE", "GEMINI_API_KEY not set — using mock extraction", "WARNING")
        return _mock_extraction()

    result = _extract_from_audio(audio_base64, session_id)
    result["source"]        = IntakeSource.AUDIO
    result["session_id"]    = session_id
    result["processing_ms"] = round((time.time() - start) * 1000)

    _log(session_id, "AUDIO_INTAKE",
         f"✅ Audio intake complete in {result['processing_ms']}ms | "
         f"Triage: {result.get('triage_color')}", "SUCCESS")
    return result


# ---------------------------------------------------------------------------
# Tool: clarify extraction (called when confidence < 0.7)
# ---------------------------------------------------------------------------

def clarify_extraction(
    original_extraction: dict,
    clarification_answer: str,
    session_id: str = "unknown",
) -> dict:
    """
    Refine a previous clinical extraction using a CHV clarification answer.
    The answer may be in any supported Kenyan language — it is translated first.

    Args:
        original_extraction:  The dict from a previous extraction call.
        clarification_answer: The CHV's spoken or typed answer in any language.
        session_id:           Session identifier for logging.

    Returns:
        Updated clinical extraction dict with clarification_needed = False.
    """
    _log(session_id, "CLARIFY", f"🔄 Clarifying extraction — answer: '{clarification_answer[:60]}'")

    # Translate the answer if it is not English
    translation = interpret_multilingual_input(clarification_answer)
    english_answer = translation.get("english_translation", clarification_answer)
    if translation.get("detected_language", "English") != "English":
        _log(session_id, "CLARIFY",
             f"Translated from {translation['detected_language']}: '{english_answer[:60]}'")

    question = original_extraction.get("clarification_question", "")
    prompt = (
        f"Given the original clinical description and the clarification answer below, "
        f"update the clinical extraction. Return ONLY valid JSON in the same format.\n\n"
        f"Original extraction: {json.dumps(original_extraction)}\n"
        f"Clarification question asked: {question}\n"
        f"CHV answer (English): {english_answer}"
    )

    try:
        from google import genai
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw = getattr(resp, "text", str(resp))
        updated = _parse_clinical_json(raw)
        updated["clarification_needed"]   = False
        updated["clarification_question"] = None
        updated["clarification_answer"]   = english_answer
        _log(session_id, "CLARIFY",
             f"✅ Clarified — syndrome: {updated.get('syndrome')} | "
             f"triage: {updated.get('triage_color')}", "SUCCESS")
        return updated
    except Exception as exc:
        _log(session_id, "CLARIFY", f"Clarification LLM call failed: {exc}", "ERROR")
        original_extraction["clarification_needed"]   = False
        original_extraction["clarification_question"] = None
        return original_extraction


# ---------------------------------------------------------------------------
# Tool: get triage guidance (spoken feedback to CHV in their language)
# ---------------------------------------------------------------------------

def get_triage_guidance(triage_color: str, syndrome: str, language: str) -> str:
    """
    Return spoken triage guidance for the CHV in the detected language.
    Used by the TTS layer to give the CHV immediate verbal feedback.

    Args:
        triage_color: GREEN, YELLOW, or RED.
        syndrome:     WHO IDSR syndrome category.
        language:     Detected language name (e.g., 'Swahili', 'Dholuo').

    Returns:
        Short guidance string for TTS playback in the CHV's language.
    """
    guidance: Dict[str, Dict[str, str]] = {
        "RED": {
            "English":   f"URGENT: {syndrome} detected. Immediate referral required. Activate emergency protocol.",
            "Swahili":   f"HARAKA SANA: {syndrome} imegunduliwa. Mpeleke hospitali SASA HIVI. Piga simu ya dharura.",
            "Dholuo":    f"DHIER AHINYA: {syndrome} oonekni. Ter e osiptal saa ni. Luong ambulans.",
            "Kikuyu":    f"HARAKA: {syndrome} ndetikiririo. Mwingirie hospitali sasa hivi.",
            "Somali":    f"DEGDEG: {syndrome} la ogaaday. U gudbi isbitaalka hadda. Wac xaaladda deg-degga ah.",
            "Luhya":     f"HARAKA: {syndrome} inaonekana. Mpeleke hospitali sasa hivi.",
            "Kamba":     f"NIINGII: {syndrome} nionekee. Mwingirie hospitali kwau.",
            "Kalenjin":  f"AMOGIO: {syndrome} iboisiet. Tii hospital saa ana.",
            "Turkana":   f"NGIDUN: {syndrome} akinekini. Apunukin hospital awata.",
            "Meru":      f"HARAKA: {syndrome} yonikanirio. Mwingiririe hospitali riu.",
            "Mijikenda": f"HARAKA: {syndrome} imeonekana. Mpeleke hospitali haraka.",
        },
        "YELLOW": {
            "English":   f"URGENT: {syndrome} detected. Referral recommended within 2 hours.",
            "Swahili":   f"MUHIMU: {syndrome} imegunduliwa. Peleka hospitali ndani ya masaa 2.",
            "Dholuo":    f"BEDO DHIER: {syndrome} oonekni. Ter e osiptal e saa 2.",
            "Kikuyu":    f"THIMU: {syndrome} ndetikiririo. Mwingirie hospitali ndani ya saa 2.",
            "Somali":    f"MUHIIM: {syndrome} la ogaaday. U gudbi isbitaalka 2 saac gudahood.",
            "Luhya":     f"MUHIMU: {syndrome} inaonekana. Mpeleke hospitali masaa 2.",
            "Kamba":     f"NIINGII: {syndrome} nionekee. Mwingirie hospitali maa elewa 2.",
            "Kalenjin":  f"SIRINIK: {syndrome} iboisiet. Tii hospital saa 2.",
            "Turkana":   f"NGIDUN: {syndrome} akinekini. Apunukin hospital awata 2.",
            "Meru":      f"THIMU: {syndrome} yonikanirio. Mwingiririe hospitali saa 2.",
            "Mijikenda": f"MUHIMU: {syndrome} imeonekana. Mpeleke hospitali masaa 2.",
        },
        "GREEN": {
            "English":   f"Routine: {syndrome} recorded. Monitor and follow up in 48 hours.",
            "Swahili":   f"KAWAIDA: {syndrome} imerekodiwa. Fuatilia baada ya masaa 48.",
            "Dholuo":    f"MABER: {syndrome} ondiki. Rit e saa 48.",
            "Kikuyu":    f"KAWAIDA: {syndrome} niandikirio. Rekia na umuone thutha wa saa 48.",
            "Somali":    f"CAADI: {syndrome} la diiwaan geliyay. La soco 48 saacadood kadib.",
            "Luhya":     f"KAWAIDA: {syndrome} imerekodiwa. Fuatilia baada ya masaa 48.",
            "Kamba":     f"KAWAIDA: {syndrome} nionekee. Angalia na umwone baada ya saa 48.",
            "Kalenjin":  f"KASARTA: {syndrome} iboisiet. Ngo ile saa 48.",
            "Turkana":   f"KAWAIDA: {syndrome} akinekini. Apunukin awata 48.",
            "Meru":      f"KAWAIDA: {syndrome} yonikanirio. Angalia thutha wa saa 48.",
            "Mijikenda": f"KAWAIDA: {syndrome} imerekodiwa. Fuatilia baada ya masaa 48.",
        },
    }
    lang_map = guidance.get(triage_color, guidance["GREEN"])
    return lang_map.get(language, lang_map["English"])


# ---------------------------------------------------------------------------
# ADK root_agent
# ---------------------------------------------------------------------------

root_agent = LlmAgent(
    name="intake_agent",
    model="gemini-flash-latest",
    description=(
        "SihaLink Intake Agent. Accepts clinical intake from web forms, Telegram, "
        "and other agents. Routes all input through the Multilingual Language Agent "
        "to support Dholuo, Swahili, Kikuyu, Somali, Luhya, Kamba, Mijikenda, Meru, "
        "Turkana, Kalenjin, and English. Extracts WHO IDSR clinical data and "
        "assigns triage classification (RED/YELLOW/GREEN)."
    ),
    instruction="""You are the SihaLink Intake Agent — the clinical data extraction brain.

INPUT SOURCES (use the matching tool for each):
  1. Web form     → call extract_from_form(form_data, session_id)
  2. Telegram     → call extract_from_telegram(message_text, audio_base64, chw_id, session_id)
  3. Agent call   → call extract_from_agent(agent_payload, source_agent, session_id)
  4. Raw audio    → call extract_clinical_data(audio_base64, session_id)

WORKFLOW FOR EVERY INTAKE:
1. Select the right extraction tool based on the source
2. If confidence < 0.7, call clarify_extraction with the CHV's response
3. Always call get_triage_guidance to generate spoken feedback in the CHV's language
4. Return the complete extraction result — never drop fields

TRIAGE RULES:
- RED   (immediate): unconscious, convulsions, unable to drink/breastfeed,
  severe dehydration, respiratory distress, severe malnutrition, hemorrhage, VHF
- YELLOW (urgent 2h): moderate dehydration, fever >38.5°C, fast breathing,
  severe vomiting, bloody diarrhea, rash with fever
- GREEN  (routine):  mild symptoms, no danger signs

LANGUAGE RULES:
- The Language Agent handles all translation — you receive English text
- If detected_language is not English, use get_triage_guidance with that language
- Never ask the CHV to repeat in English — translate instead

CRITICAL: This is a health emergency system. Be concise. Log every step.
Never ask more than one clarification question. Default to YELLOW if uncertain.
""",
    tools=[
        extract_from_form,
        extract_from_telegram,
        extract_from_agent,
        extract_clinical_data,
        clarify_extraction,
        get_triage_guidance,
    ],
    generate_content_config=genai_types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=512,
    ),
)

# ---------------------------------------------------------------------------
# RunConfig with TTS (SpeechConfig)
# ---------------------------------------------------------------------------

def build_run_config(voice_name: str = "Aoede") -> RunConfig:
    """Build RunConfig with TTS enabled. Aoede is clear and calm for medical comms."""
    voice_config = genai_types.VoiceConfig(
        prebuilt_voice_config=genai_types.PrebuiltVoiceConfigDict(
            voice_name=voice_name
        )
    )
    speech_config = genai_types.SpeechConfig(voice_config=voice_config)
    return RunConfig(speech_config=speech_config)


# ---------------------------------------------------------------------------
# Live session runner (Gemini Live API — bidirectional audio)
# ---------------------------------------------------------------------------

APP_NAME = "sihalink_intake"
_session_service = InMemorySessionService()
_runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=_session_service,
)


async def run_live_session(
    session_id: str,
    audio_chunks: asyncio.Queue,
    response_queue: asyncio.Queue,
    voice_name: str = "Aoede",
) -> None:
    """
    Run a bidirectional Gemini Live API session for real-time CHV interaction.

    Args:
        session_id:     Unique session ID.
        audio_chunks:   asyncio.Queue of raw PCM audio bytes from the CHV microphone.
        response_queue: asyncio.Queue where audio/text responses are placed.
        voice_name:     TTS voice (default Aoede).
    """
    _log(session_id, "LIVE_SESSION", f"🔴 Starting live session (voice: {voice_name})")

    await _session_service.create_session(
        app_name=APP_NAME,
        user_id=session_id,
        session_id=session_id,
    )

    live_request_queue = LiveRequestQueue()
    run_config = build_run_config(voice_name)

    async def _feed_audio() -> None:
        chunk_count = 0
        while True:
            chunk = await audio_chunks.get()
            if chunk is None:
                live_request_queue.send_realtime(LiveRequest(close=True))
                _log(session_id, "LIVE_SESSION",
                     f"🎙️ Audio feed closed ({chunk_count} chunks sent)")
                break
            live_request_queue.send_realtime(
                LiveRequest(
                    blob=genai_types.Blob(
                        mime_type="audio/pcm;rate=16000",
                        data=chunk,
                    )
                )
            )
            chunk_count += 1

    async def _consume_events() -> None:
        event_count = 0
        async for event in _runner.run_live(
            user_id=session_id,
            session_id=session_id,
            live_request_queue=live_request_queue,
            run_config=run_config,
        ):
            event_count += 1
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.inline_data and part.inline_data.mime_type.startswith("audio/"):
                        await response_queue.put(part.inline_data.data)
                    elif part.text:
                        _log(session_id, "LIVE_SESSION", f"Agent: {part.text[:80]}")
                        await response_queue.put({"text": part.text})
            if event.is_final_response():
                _log(session_id, "LIVE_SESSION",
                     f"✅ Live session complete ({event_count} events)", "SUCCESS")
                await response_queue.put(None)
                break

    await asyncio.gather(_feed_audio(), _consume_events())


# ---------------------------------------------------------------------------
# IntakeAgent class wrapper (used by Orchestrator and state machine)
# ---------------------------------------------------------------------------

class IntakeAgent:
    """
    Public interface for the Intake Agent. Used by the Orchestrator state machine
    and FastAPI route handlers. All methods emit progress logs.
    """

    async def process_audio(self, audio_b64: str) -> Dict[str, Any]:
        """Extract clinical data from base64 audio."""
        session_id = f"audio-{int(time.time())}"
        return extract_clinical_data(audio_b64, session_id)

    async def process_form(
        self, form_data: Dict[str, Any], session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Extract clinical data from a web form submission."""
        sid = session_id or f"form-{int(time.time())}"
        return extract_from_form(form_data, sid)

    async def process_telegram(
        self,
        message_text: Optional[str],
        audio_b64: Optional[str],
        chw_id: str,
        session_id: Optional[str] = None,
        language_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Extract clinical data from a Telegram message."""
        sid = session_id or f"tg-{int(time.time())}"
        return extract_from_telegram(
            message_text, audio_b64, chw_id, sid, language_hint
        )

    async def process_from_agent(
        self,
        payload: Dict[str, Any],
        source_agent: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process an intake payload from another agent."""
        sid = session_id or f"agent-{int(time.time())}"
        return extract_from_agent(payload, source_agent, sid)

    async def clarify(
        self,
        original_extraction: Dict[str, Any],
        clarification_answer: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Refine extraction with a CHV clarification answer (any language)."""
        sid = session_id or original_extraction.get("session_id", "unknown")
        return clarify_extraction(original_extraction, clarification_answer, sid)

    async def process_with_clarification(
        self,
        audio_b64: str,
        clarification_answers: Optional[List[str]] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Full multi-turn flow: extract audio → clarify up to 2 rounds."""
        sid = session_id or f"audio-{int(time.time())}"
        result = extract_clinical_data(audio_b64, sid)
        if not clarification_answers:
            return result
        rounds = 0
        for answer in clarification_answers:
            if not result.get("clarification_needed") or rounds >= 2:
                break
            result = clarify_extraction(result, answer, sid)
            rounds += 1
        return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_from_text(english_text: str, session_id: str) -> Dict[str, Any]:
    """
    Run clinical extraction on a normalised English text description.
    This is the shared extraction core used by all three source paths.
    """
    if not english_text.strip():
        return _mock_extraction()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        _log(session_id, "EXTRACTION", "GEMINI_API_KEY not set — using mock", "WARNING")
        return _mock_extraction()

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = _build_text_extraction_prompt(english_text)
        _log(session_id, "EXTRACTION", "Calling Gemini for clinical extraction...")
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw = getattr(resp, "text", str(resp))
        result = _parse_clinical_json(raw)
        _log(session_id, "EXTRACTION",
             f"Raw extraction: syndrome={result.get('syndrome')} "
             f"confidence={result.get('confidence', 0):.0%}")
        return result
    except Exception as exc:
        _log(session_id, "EXTRACTION", f"Gemini call failed: {exc}", "ERROR")
        return {"error": "extraction_failed", "details": str(exc)}


def _extract_from_audio(audio_base64: str, session_id: str) -> Dict[str, Any]:
    """
    Direct audio extraction — sends audio bytes to Gemini multimodal.
    Falls back to mock if API key not set.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return _mock_extraction()

    try:
        audio_bytes = base64.b64decode(audio_base64)
        from google import genai
        from google.genai import types as genai_t
        client = genai.Client(api_key=api_key)
        prompt = _build_audio_extraction_prompt()
        _log(session_id, "EXTRACTION", "Calling Gemini multimodal for audio extraction...")
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                prompt,
                genai_t.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
            ],
        )
        raw = getattr(resp, "text", str(resp))
        return _parse_clinical_json(raw)
    except Exception as exc:
        _log(session_id, "EXTRACTION", f"Audio extraction failed: {exc}", "ERROR")
        return {"error": "extraction_failed", "details": str(exc)}


def _transcribe_audio(audio_base64: str, session_id: str) -> Optional[str]:
    """
    Transcribe audio to text using Gemini multimodal.
    Returns the transcript string, or None on failure.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        audio_bytes = base64.b64decode(audio_base64)
        from google import genai
        from google.genai import types as genai_t
        client = genai.Client(api_key=api_key)
        prompt = (
            "Transcribe this audio recording from a Community Health Volunteer in Kenya. "
            "The audio may be in Dholuo, Swahili, Kikuyu, Somali, Luhya, Kamba, Mijikenda, "
            "Meru, Turkana, Kalenjin, or English. Output only the transcript text, "
            "preserving the original language. No translation, no explanation."
        )
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                prompt,
                genai_t.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
            ],
        )
        transcript = getattr(resp, "text", "").strip()
        _log(session_id, "AUDIO", f"Transcript ({len(transcript)} chars): '{transcript[:60]}'")
        return transcript if transcript else None
    except Exception as exc:
        _log(session_id, "AUDIO", f"Transcription failed: {exc}", "ERROR")
        return None


def _ensure_triage(result: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    """Ensure triage_color is set. Infer from severity if missing."""
    if result.get("triage_color") in ("RED", "YELLOW", "GREEN"):
        return result
    severity = result.get("severity", "mild")
    danger   = result.get("danger_signs", [])
    if danger or severity == "severe":
        result["triage_color"] = "RED"
    elif severity == "moderate":
        result["triage_color"] = "YELLOW"
    else:
        result["triage_color"] = "GREEN"
    _log(session_id, "TRIAGE",
         f"Inferred triage: {result['triage_color']} (severity={severity})", "WARNING")
    return result


def _build_text_extraction_prompt(english_text: str) -> str:
    return f"""You are a clinical data extraction assistant for community health workers in Kenya.
Extract structured clinical data from the description below (already in English).

MAP SYMPTOMS to one of these WHO IDSR syndrome categories:
{json.dumps(IDSR_SYNDROMES, indent=2)}

TRIAGE RULES:
- RED: unconscious, convulsions, unable to drink/breastfeed, severe dehydration,
  respiratory distress, severe malnutrition, hemorrhage, suspected VHF
- YELLOW: moderate dehydration, fever >38.5°C, fast breathing, severe vomiting,
  bloody diarrhea, rash with fever
- GREEN: mild symptoms, no danger signs

Clinical description: "{english_text}"

Return ONLY valid JSON, no markdown:
{{
  "syndrome": "one IDSR category",
  "primary_symptoms": ["symptom1", "symptom2"],
  "severity": "mild|moderate|severe",
  "triage_color": "GREEN|YELLOW|RED",
  "chief_complaint": "brief English description",
  "age": {{"value": 0, "unit": "days|months|years"}},
  "sex": "male|female|unknown",
  "duration_days": 0,
  "vital_signs": {{"temperature_c": 0, "respiratory_rate": 0}},
  "danger_signs": [],
  "patient_contacts": [{{"name": "string", "relation": "string"}}],
  "confidence": 0.0,
  "clarification_needed": false,
  "clarification_question": null
}}
"""


def _build_audio_extraction_prompt() -> str:
    return f"""You are a clinical data extraction assistant for community health workers in Kenya.
Extract structured clinical data from the audio recording.
The audio may be in Dholuo, Swahili, Kikuyu, Somali, Luhya, Kamba, Mijikenda,
Meru, Turkana, Kalenjin, or English (handle code-switching).

MAP SYMPTOMS to one of these WHO IDSR syndrome categories:
{json.dumps(IDSR_SYNDROMES, indent=2)}

TRIAGE RULES:
- RED: unconscious, convulsions, unable to drink/breastfeed, severe dehydration,
  respiratory distress, severe malnutrition, hemorrhage, suspected VHF
- YELLOW: moderate dehydration, fever >38.5°C, fast breathing, severe vomiting,
  bloody diarrhea, rash with fever
- GREEN: mild symptoms, no danger signs

Return ONLY valid JSON, no markdown:
{{
  "language": "detected language",
  "syndrome": "one IDSR category",
  "primary_symptoms": ["symptom1"],
  "severity": "mild|moderate|severe",
  "triage_color": "GREEN|YELLOW|RED",
  "chief_complaint": "brief English description",
  "age": {{"value": 0, "unit": "years"}},
  "sex": "male|female|unknown",
  "duration_days": 0,
  "vital_signs": {{"temperature_c": 0, "respiratory_rate": 0}},
  "danger_signs": [],
  "confidence": 0.0,
  "clarification_needed": false,
  "clarification_question": null
}}

If confidence < 0.7, set clarification_needed=true and write the clarification_question
in the detected language.
"""


def _parse_clinical_json(raw_text: str) -> Dict[str, Any]:
    """Strip markdown fences and parse clinical JSON."""
    try:
        clean = raw_text.replace("```json", "").replace("```", "").strip()
        start = clean.find("{")
        end   = clean.rfind("}") + 1
        if start >= 0 and end > start:
            clean = clean[start:end]
        return json.loads(clean)
    except Exception as exc:
        logger.warning("JSON parse failed: %s | raw: %.200s", exc, raw_text)
        return {"error": "parse_failed", "raw": raw_text[:500]}


def _mock_extraction() -> Dict[str, Any]:
    """Realistic mock for dev/testing when GEMINI_API_KEY is not set."""
    return {
        "language": "Swahili",
        "syndrome": "acute_watery_diarrhea",
        "primary_symptoms": ["watery_diarrhea", "vomiting", "dehydration"],
        "severity": "moderate",
        "triage_color": "YELLOW",
        "chief_complaint": "Child with watery diarrhea and vomiting for 2 days",
        "age": {"value": 2, "unit": "years"},
        "sex": "male",
        "duration_days": 2,
        "vital_signs": {"temperature_c": 38.2, "respiratory_rate": 28},
        "danger_signs": [],
        "patient_contacts": [],
        "confidence": 0.85,
        "clarification_needed": False,
        "clarification_question": None,
        "source": IntakeSource.AUDIO,
        "_mock": True,
    }
