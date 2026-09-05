"""
tts.py
------
Turns bot replies into speech using Microsoft Edge's free neural
text-to-speech (the `edge-tts` package) — no API key needed, and it
sounds far better/more consistent across devices than the browser's
built-in speechSynthesis, which is what the frontend used to rely on.

`lang_utils.detect_voice_lang()` labels every reply "en-IN" or "hi-IN"
(the bot only ever replies in English or Hindi) — this module maps that
to one fixed Edge neural voice per language and streams back MP3 bytes.

Voice choice: en-IN-NeerjaNeural / hi-IN-SwaraNeural — Edge's female Indian-
English/Hindi neural voices, kept as a matched pair (same gender/persona)
so switching between the two languages doesn't also switch the
"character" of the voice.
"""

import io
import re
import unicodedata
import edge_tts

VOICE_BY_LOCALE = {
    "en-IN": "en-IN-NeerjaNeural",
    "hi-IN": "hi-IN-SwaraNeural",
}
DEFAULT_VOICE = VOICE_BY_LOCALE["en-IN"]


def pick_voice(lang: str, override: str | None = None) -> str:
    if override:
        return override
    return VOICE_BY_LOCALE.get(lang, DEFAULT_VOICE)


# "Special characters" we don't want spoken aloud (e.g. Edge TTS reading
# "**" as "asterisk asterisk" or "#" as "hash"), while still keeping every
# language's letters — including combining marks, so Hindi conjuncts like
# "न्यवाद" (which rely on the virama) aren't broken apart — plus digits,
# whitespace, and basic sentence punctuation so pacing still sounds natural.
_SPEAKABLE_PUNCTUATION = set(".,?!:;'\"()-")
_MD_HEADER_BULLET_RE = re.compile(r"(?m)^\s{0,3}(#{1,6}|[-*+]|\d+\.)\s+")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")  # [text](url) -> text
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")


def _keep_char(ch: str) -> bool:
    if ch.isspace() or ch in _SPEAKABLE_PUNCTUATION:
        return True
    category = unicodedata.category(ch)
    # L* = letters, M* = combining marks, Nd = decimal digits
    return category[0] in ("L", "M") or category == "Nd"


def clean_for_speech(text: str) -> str:
    """Strips markdown formatting and other special characters from `text`
    so only plain, readable words/sentences get sent to the TTS engine."""
    if not text:
        return ""
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _MD_HEADER_BULLET_RE.sub("", text)
    text = "".join(ch if _keep_char(ch) else " " for ch in text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    return text.strip()


async def synthesize_speech(text: str, lang: str = "en-IN", voice: str | None = None) -> bytes:
    """Returns MP3 audio bytes for `text`, spoken in a voice matching `lang`
    (e.g. 'hi-IN', 'en-IN' — same locale codes lang_utils.detect_voice_lang
    returns), or an explicit Edge voice name via `voice`."""
    text = clean_for_speech((text or "").strip())
    if not text:
        return b""
    selected_voice = pick_voice(lang, voice)
    communicator = edge_tts.Communicate(text, selected_voice)
    buffer = io.BytesIO()
    async for chunk in communicator.stream():
        if chunk["type"] == "audio":
            buffer.write(chunk["data"])
    return buffer.getvalue()