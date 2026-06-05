"""
SihaLink Multilingual Language Agent
Interprets clinical intake text/audio from Kenyan languages and normalises
it to English clinical JSON before the Intake Agent processes it.

Supported languages:
  - Dholuo (Luo)        — Western Kenya, Nyanza
  - Swahili / Kiswahili — National language, widely spoken
  - Kikuyu              — Central Kenya
  - Somali              — North Eastern Kenya
  - Luhya               — Western Kenya
  - Kamba               — Eastern Kenya
  - Mijikenda           — Coast region
  - Meru                — Mt. Kenya region
  - Turkana             — Turkana County
  - Kalenjin            — Rift Valley
  - English             — pass-through

All output is normalised to English so downstream agents need no language logic.
Code-switching (mixing languages mid-sentence) is explicitly handled.
"""

import json
import logging
import os
from typing import Any, Dict, Optional

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

logger = logging.getLogger("SihaLink-LanguageAgent")

# ---------------------------------------------------------------------------
# Supported language registry
# ---------------------------------------------------------------------------

SUPPORTED_LANGUAGES: Dict[str, Dict[str, str]] = {
    "dholuo":    {"name": "Dholuo",    "region": "Nyanza/Western", "iso": "luo"},
    "swahili":   {"name": "Swahili",   "region": "National",       "iso": "swa"},
    "kikuyu":    {"name": "Kikuyu",    "region": "Central",        "iso": "kik"},
    "somali":    {"name": "Somali",    "region": "North Eastern",  "iso": "som"},
    "luhya":     {"name": "Luhya",     "region": "Western",        "iso": "luy"},
    "kamba":     {"name": "Kamba",     "region": "Eastern",        "iso": "kam"},
    "mijikenda": {"name": "Mijikenda", "region": "Coast",          "iso": "nyf"},
    "meru":      {"name": "Meru",      "region": "Mt. Kenya",      "iso": "mer"},
    "turkana":   {"name": "Turkana",   "region": "Turkana",        "iso": "tuv"},
    "kalenjin":  {"name": "Kalenjin",  "region": "Rift Valley",    "iso": "kln"},
    "english":   {"name": "English",   "region": "National",       "iso": "eng"},
}

# Common symptom translations used for rapid keyword detection
# before calling the LLM (fast path for simple cases)
SYMPTOM_KEYWORDS: Dict[str, Dict[str, str]] = {
    "fever": {
        "dholuo":    "homa",
        "swahili":   "homa",
        "kikuyu":    "homa",
        "somali":    "qandho",
        "luhya":     "omusujwa",
        "kamba":     "musua",
        "mijikenda": "homa",
        "meru":      "homa",
        "turkana":   "ekwom",
        "kalenjin":  "chepkoros",
    },
    "diarrhea": {
        "dholuo":    "ratiro",
        "swahili":   "kuhara",
        "kikuyu":    "kuhara",
        "somali":    "xanuun calool",
        "luhya":     "okuhara",
        "kamba":     "kuhara",
        "mijikenda": "kuhara",
        "meru":      "kuhara",
        "turkana":   "achom",
        "kalenjin":  "kipsergit",
    },
    "vomiting": {
        "dholuo":    "yuak",
        "swahili":   "kutapika",
        "kikuyu":    "gutapika",
        "somali":    "maroodi",
        "luhya":     "okutapika",
        "kamba":     "kutapika",
        "mijikenda": "kutapika",
        "meru":      "gutapika",
        "turkana":   "akiru",
        "kalenjin":  "kipsergitiet",
    },
    "cough": {
        "dholuo":    "porto",
        "swahili":   "kukohoa",
        "kikuyu":    "gukohora",
        "somali":    "qufac",
        "luhya":     "okukohola",
        "kamba":     "kukoa",
        "mijikenda": "kukohoa",
        "meru":      "gukohora",
        "turkana":   "akoona",
        "kalenjin":  "kipsargei",
    },
    "malnutrition": {
        "dholuo":    "kech",
        "swahili":   "utapiamlo",
        "kikuyu":    "njara",
        "somali":    "gaajoonaanta",
        "luhya":     "inzala",
        "kamba":     "nzala",
        "mijikenda": "njaa",
        "meru":      "njara",
        "turkana":   "ekikirr",
        "kalenjin":  "koito",
    },
}


# ---------------------------------------------------------------------------
# Core translation + normalisation function
# ---------------------------------------------------------------------------

def interpret_multilingual_input(
    text: str,
    source_language: Optional[str] = None,
    context: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Detect the language of clinical text and normalise it to English.

    Handles:
    - Pure Kenyan language input
    - Code-switching (e.g., Dholuo + Swahili + English in the same sentence)
    - Abbreviations and local clinical terminology
    - Telegram message format (informal, short sentences)

    Args:
        text:            Raw input text from any source (form, Telegram, agent).
        source_language: Optional hint — if caller already knows the language.
        context:         Optional surrounding context (e.g., previous message).

    Returns:
        dict with:
          detected_language: str
          confidence: float (0-1)
          english_translation: str (normalised English clinical description)
          original_text: str
          clinical_keywords: list[str] (extracted symptom keywords in English)
          needs_clarification: bool
          clarification_question: str | None (in detected language)
    """
    if not text or not text.strip():
        return {
            "detected_language": "unknown",
            "confidence": 0.0,
            "english_translation": "",
            "original_text": text,
            "clinical_keywords": [],
            "needs_clarification": True,
            "clarification_question": "Please describe the patient's symptoms.",
        }

    # Fast path: already English
    text_lower = text.lower()
    if source_language == "english" or _is_predominantly_english(text_lower):
        logger.info("[LanguageAgent] Input is English — passing through directly")
        return {
            "detected_language": "English",
            "confidence": 0.99,
            "english_translation": text,
            "original_text": text,
            "clinical_keywords": _extract_english_keywords(text_lower),
            "needs_clarification": False,
            "clarification_question": None,
        }

    # LLM path: interpret and translate
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("[LanguageAgent] GEMINI_API_KEY not set — using keyword fallback")
        return _keyword_fallback(text, source_language)

    try:
        from google import genai
        client = genai.Client(api_key=api_key)

        prompt = _build_translation_prompt(text, source_language, context)
        logger.info("[LanguageAgent] 🌍 Translating input (hint: %s)...", source_language or "auto-detect")

        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw = getattr(resp, "text", str(resp))
        result = _parse_translation_json(raw)
        result["original_text"] = text

        logger.info(
            "[LanguageAgent] ✅ Detected: %s (%.0f%% confidence) → '%s'",
            result.get("detected_language", "?"),
            result.get("confidence", 0) * 100,
            result.get("english_translation", "")[:80],
        )
        return result

    except Exception as exc:
        logger.error("[LanguageAgent] Translation failed: %s", exc)
        return _keyword_fallback(text, source_language)


def detect_language(text: str) -> str:
    """
    Quick language detection without full translation.
    Returns the language name (e.g., 'Dholuo', 'Swahili').
    """
    result = interpret_multilingual_input(text)
    return result.get("detected_language", "unknown")


def get_clarification_prompt(question_english: str, target_language: str) -> str:
    """
    Translate a clarification question from English to the target language.
    Used to ask follow-up questions to CHVs in their native language.

    Args:
        question_english: The clarification question in English.
        target_language:  Target language name (e.g., 'Dholuo').

    Returns:
        Translated question string, or original English if translation fails.
    """
    lang_lower = target_language.lower()
    if lang_lower == "english":
        return question_english

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return question_english

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = (
            f"Translate this clinical question to {target_language}. "
            f"Keep it simple, short, and appropriate for a community health worker.\n"
            f"Return ONLY the translated text, no explanation.\n\n"
            f"Question: {question_english}"
        )
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        translated = getattr(resp, "text", question_english).strip()
        logger.info("[LanguageAgent] 🗣️ Translated question to %s: '%s'", target_language, translated[:60])
        return translated
    except Exception as exc:
        logger.warning("[LanguageAgent] Question translation failed: %s", exc)
        return question_english


# ---------------------------------------------------------------------------
# ADK root_agent
# ---------------------------------------------------------------------------

root_agent = LlmAgent(
    name="language_agent",
    model="gemini-flash-latest",
    description=(
        "SihaLink Multilingual Language Agent. "
        "Detects and translates clinical intake from 10 Kenyan languages "
        "(Dholuo, Swahili, Kikuyu, Somali, Luhya, Kamba, Mijikenda, Meru, Turkana, Kalenjin) "
        "and English, including code-switching. "
        "Normalises all input to English clinical JSON for downstream agents."
    ),
    instruction=f"""You are the SihaLink Language Agent — a clinical interpreter for Kenya.

YOUR ROLE:
- Detect the language of incoming clinical text (may be a mix of languages)
- Translate and normalise it to English clinical terminology
- Identify clinical keywords (symptoms, syndromes, danger signs)
- Ask clarifying questions in the CHV's own language when input is unclear

SUPPORTED LANGUAGES:
{json.dumps({v['name']: v['region'] for v in SUPPORTED_LANGUAGES.values()}, indent=2)}

KENYAN CLINICAL CONTEXT:
- CHVs (Community Health Volunteers) report using informal language
- Common presentations: malaria, cholera, acute watery diarrhea, malnutrition,
  respiratory infections, measles — prioritise these in keyword extraction
- Danger signs require urgent escalation: convulsions, unconscious, unable to feed,
  severe dehydration, respiratory distress, hemorrhage
- Code-switching is normal — a single message may contain 3 languages

WORKFLOW:
1. Call interpret_multilingual_input with the raw text
2. If confidence < 0.7, call get_clarification_prompt to ask in CHV's language
3. Return normalised English output with detected language and confidence

CRITICAL: Never lose clinical information in translation. When uncertain,
include the original text alongside the translation.
""",
    tools=[interpret_multilingual_input, detect_language, get_clarification_prompt],
    generate_content_config=genai_types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=512,
    ),
)

APP_NAME = "sihalink_language"
_session_service = InMemorySessionService()
_runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=_session_service,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_translation_prompt(
    text: str,
    source_language: Optional[str],
    context: Optional[str],
) -> str:
    lang_hint = f"The input is likely in {source_language}. " if source_language else ""
    ctx_hint = f"\nPrevious context: {context}" if context else ""
    supported = ", ".join(v["name"] for v in SUPPORTED_LANGUAGES.values())

    return f"""You are a clinical language interpreter for Community Health Volunteers in Kenya.
{lang_hint}Detect the language and translate the following clinical input to English.
Supported languages: {supported}. Handle code-switching naturally.{ctx_hint}

Input: "{text}"

Return ONLY valid JSON, no markdown:
{{
  "detected_language": "language name",
  "confidence": 0.0-1.0,
  "english_translation": "full English translation preserving all clinical details",
  "clinical_keywords": ["keyword1", "keyword2"],
  "needs_clarification": false,
  "clarification_question": null
}}

If needs_clarification is true, write the clarification_question in the detected language.
Preserve ALL clinical details — never omit symptoms, duration, or severity in translation.
"""


def _parse_translation_json(raw: str) -> Dict[str, Any]:
    """Parse LLM translation response."""
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start >= 0 and end > start:
            clean = clean[start:end]
        return json.loads(clean)
    except Exception as exc:
        logger.warning("[LanguageAgent] JSON parse failed: %s | raw: %.100s", exc, raw)
        return {
            "detected_language": "unknown",
            "confidence": 0.3,
            "english_translation": raw[:500],
            "clinical_keywords": [],
            "needs_clarification": False,
            "clarification_question": None,
        }


def _is_predominantly_english(text: str) -> bool:
    """Heuristic: check if most words are common English words."""
    english_common = {
        "the", "patient", "child", "has", "with", "and", "for", "days",
        "fever", "cough", "diarrhea", "vomiting", "year", "old", "male",
        "female", "symptoms", "since", "ago", "complaining", "severe",
        "mild", "moderate", "urgent", "refer", "he", "she", "is", "are",
    }
    words = set(text.lower().split())
    overlap = words & english_common
    return len(overlap) >= 3


def _extract_english_keywords(text: str) -> list:
    """Extract clinical keywords from English text."""
    clinical_terms = [
        "fever", "diarrhea", "vomiting", "cough", "malnutrition",
        "dehydration", "convulsions", "unconscious", "rash", "bleeding",
        "respiratory", "distress", "jaundice", "swelling", "pain",
        "weakness", "fatigue", "headache", "neck stiffness", "cholera",
        "measles", "malaria", "pneumonia", "sepsis",
    ]
    return [term for term in clinical_terms if term in text]


def _keyword_fallback(text: str, source_language: Optional[str]) -> Dict[str, Any]:
    """Fallback when API is unavailable — match known symptom keywords."""
    text_lower = text.lower()
    detected_lang = "unknown"
    found_keywords = []

    for symptom, lang_map in SYMPTOM_KEYWORDS.items():
        for lang, keyword in lang_map.items():
            if keyword in text_lower:
                found_keywords.append(symptom)
                if detected_lang == "unknown":
                    detected_lang = SUPPORTED_LANGUAGES.get(lang, {}).get("name", lang)

    if source_language and source_language.lower() in SUPPORTED_LANGUAGES:
        detected_lang = SUPPORTED_LANGUAGES[source_language.lower()]["name"]

    logger.warning(
        "[LanguageAgent] Keyword fallback — detected: %s, keywords: %s",
        detected_lang, found_keywords,
    )

    return {
        "detected_language": detected_lang,
        "confidence": 0.5 if found_keywords else 0.2,
        "english_translation": text,  # return original — can't translate without LLM
        "original_text": text,
        "clinical_keywords": found_keywords,
        "needs_clarification": len(found_keywords) == 0,
        "clarification_question": (
            "Can you describe the patient's symptoms in more detail?"
            if len(found_keywords) == 0 else None
        ),
    }
