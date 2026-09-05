"""
lang_utils.py
-------------
Detects which language a piece of text is in, using `langdetect` — a free,
offline, no-API-call library (no rate limit, no internet needed).

Used to tell the browser which VOICE to speak the reply in. The chatbot
only ever replies in English or Hindi (the LLM prompts enforce that) —
this module just labels which of the two so voice output matches it, with
zero manual selection anywhere.
"""

from langdetect import detect, DetectorFactory, LangDetectException

DetectorFactory.seed = 0

# The assistant only ever replies in English or Hindi, so these are the
# only two voices that should ever be selected. Anything langdetect
# reports outside these two (misfires on short/mixed text, mostly) falls
# back to the default voice rather than picking an unsupported language.
_VOICE_MAP = {
    "en": "en-IN",
    "hi": "hi-IN",
}

DEFAULT_VOICE = "en-IN"


def detect_voice_lang(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return DEFAULT_VOICE
    try:
        code = detect(text)
    except LangDetectException:
        return DEFAULT_VOICE
    return _VOICE_MAP.get(code, DEFAULT_VOICE)
