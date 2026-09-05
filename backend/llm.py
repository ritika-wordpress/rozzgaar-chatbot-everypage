"""
llm.py
------
Talks to THREE free LLM options, in order, so no single provider's limit
can fully stop the bot: Groq -> Hugging Face Inference API -> local Ollama.
See the top of each _call_* function for setup notes.

On top of that generic dispatcher, this file has the Rozzgaar-specific
logic:
  - classify_intent(): figures out what the user wants (greeting, register,
    login, asking about a course, etc.) and auto-detects/replies in
    whatever language they used — no language ever needs to be configured.
  - flow_step(): used DURING a register/login conversation to validate the
    user's last answer (handling typos/informal input) and phrase the next
    question, both in one call, in the user's own language.
  - summarize_courses(): turns raw course-list API results into a short,
    human, plain-language answer.
"""

import os
import re
import json
import requests
from groq import Groq
from groq import RateLimitError, APIStatusError

# ---------------------------------------------------------------------------
# Tier 1: Groq
# ---------------------------------------------------------------------------
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY")) if os.getenv("GROQ_API_KEY") else None

GROQ_MODEL_CHAIN = [
    os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
    "llama-3.3-70b-versatile",
    "gemma2-9b-it",
]


def _call_groq(messages, temperature, json_mode):
    if groq_client is None:
        return None
    kwargs = dict(messages=messages, temperature=temperature)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    for model in GROQ_MODEL_CHAIN:
        try:
            resp = groq_client.chat.completions.create(model=model, **kwargs)
            return resp.choices[0].message.content.strip()
        except RateLimitError as e:
            print(f"[llm] groq/{model}: RATE LIMITED — {e}")
        except APIStatusError as e:
            print(f"[llm] groq/{model}: API error (status {e.status_code}) — {e}")
        except Exception as e:
            print(f"[llm] groq/{model}: unexpected error — {type(e).__name__}: {e}")
    return None


# ---------------------------------------------------------------------------
# Tier 2: Hugging Face Inference API (free, separate quota from Groq)
# ---------------------------------------------------------------------------
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
HF_MODEL = os.getenv("HF_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")


def _messages_to_prompt(messages):
    parts = []
    for m in messages:
        if m["role"] == "system":
            parts.append(f"[SYSTEM]\n{m['content']}")
        elif m["role"] == "user":
            parts.append(f"[USER]\n{m['content']}")
    parts.append("[ASSISTANT]\n")
    return "\n\n".join(parts)


def _call_huggingface(messages, temperature, json_mode):
    if not HF_API_TOKEN:
        return None
    try:
        resp = requests.post(
            f"https://api-inference.huggingface.co/models/{HF_MODEL}",
            headers={"Authorization": f"Bearer {HF_API_TOKEN}"},
            json={
                "inputs": _messages_to_prompt(messages),
                "parameters": {
                    "temperature": max(temperature, 0.01),
                    "max_new_tokens": 512,
                    "return_full_text": False,
                },
            },
            timeout=40,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            print(f"[llm] huggingface/{HF_MODEL}: {data['error']}")
            return None
        if isinstance(data, list) and data and "generated_text" in data[0]:
            return data[0]["generated_text"].strip()
        return None
    except Exception as e:
        print(f"[llm] huggingface/{HF_MODEL}: unexpected error — {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------------
# Tier 3: Ollama — local, free, no rate limit at all
# ---------------------------------------------------------------------------
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")


def _call_ollama(messages, json_mode):
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": OLLAMA_MODEL, "messages": messages, "stream": False,
                  "format": "json" if json_mode else None},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    except Exception as e:
        print(f"[llm] ollama: not available — {e}")
        return None


def _extract_json(text: str):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _chat(messages, temperature=0.2, json_mode=False):
    result = _call_groq(messages, temperature, json_mode)
    if result:
        return result
    print("[llm] Groq exhausted, trying Hugging Face...")
    result = _call_huggingface(messages, temperature, json_mode)
    if result:
        return result
    print("[llm] Hugging Face unavailable, trying local Ollama...")
    result = _call_ollama(messages, json_mode)
    if result:
        return result
    raise RuntimeError("All configured free providers (Groq, Hugging Face, Ollama) are unavailable right now.")


def _parse_json_reply(raw, fallback_type="unclear", fallback_reply="Sorry, could you say that again?"):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        parsed = _extract_json(raw)
        if parsed:
            return parsed
        return {"type": fallback_type, "reply": fallback_reply}


def _lang_instruction(forced_lang: str | None = None) -> str:
    """
    Builds the language-handling instruction for a system prompt. If the
    user picked a language at the frontend's language gate, that choice is
    forced for the rest of the session — no auto-detection, no drifting
    into the other language even if the user types in it. Otherwise, fall
    back to auto-detecting Hindi/Hinglish vs. English per message.
    """
    if forced_lang == "en":
        return (
            "The user has chosen ENGLISH for this session. Always reply in English only, "
            "no matter what language they type in."
        )
    if forced_lang == "hi":
        return (
            "The user has chosen HINDI for this session. Always reply in Hindi (Devanagari "
            "script) only, no matter what language they type in."
        )
    return (
        "Detect whether their message is closer to Hindi/Hinglish or English, and reply in "
        "exactly that one language. If their message is in some other language, reply in "
        "simple English."
    )


# ---------------------------------------------------------------------------
# Rozzgaar-specific: top-level intent classification
# ---------------------------------------------------------------------------
def classify_intent(user_message: str, forced_lang: str | None = None) -> dict:
    """
    Figures out what the user wants on Rozzgaar's site, understanding typos
    and informal phrasing, and auto-detecting/replying in whatever language
    (Hindi, English, Hinglish, etc.) the user wrote in — nothing is ever
    configured manually.

    Returns JSON with one of these shapes:
      {"type": "greeting",        "reply": "..."}
      {"type": "about_bot",       "reply": "..."}
      {"type": "register",        "reply": "..."}   # reply optionally acknowledges before flow starts
      {"type": "login",           "reply": "..."}
      {"type": "forgot_password", "reply": "..."}
      {"type": "course_info",     "search_term": "<short keyword or empty string for 'show all'>"}
      {"type": "bundle_info",     "reply": "..."}
      {"type": "unclear",         "reply": "..."}
    """
    system = (
        "You are the assistant on Rozzgaar (rozzgaar.in) — a website that sells short "
        "online skill/certification courses (e.g. Instagram Marketing, Entrepreneur "
        "Development Program) to ordinary people across India, including many who don't "
        "read/write well and write with typos, broken grammar, or in Hindi/Hinglish. "
        "This assistant supports ONLY two languages: English and Hindi (Hindi may be "
        "written in Devanagari script or in romanized Hinglish — treat both as Hindi). "
        f"{_lang_instruction(forced_lang)} Never mix in a third language, and never ask "
        "them to pick a language.\n\n"
        "First, understand their real intent past any typos (e.g. 'mujhe naukri k liye "
        "course krna h' means they want to browse/enroll in a course). Then classify into "
        "EXACTLY one type:\n"
        '- "greeting": hi/hello/namaste/thanks/bye/small talk, no real request.\n'
        '- "about_bot": asking what this is, who runs Rozzgaar, what the bot can do.\n'
        '- "register": wants to create a new account / sign up.\n'
        '- "login": wants to log into an existing account.\n'
        '- "forgot_password": forgot their password / can\'t log in / wants to reset it.\n'
        '- "course_info": asking about individual courses, prices, duration, what\'s '
        "available, a specific course by name, certificates — anything about single-course "
        "site content.\n"
        '- "bundle_info": asking specifically about course BUNDLES / combo packs / package '
        "deals (multiple courses sold together) rather than a single course.\n"
        '- "unclear": you genuinely cannot tell what they want.\n\n'
        "Respond with JSON ONLY, no other text, no markdown fences:\n"
        '- greeting/about_bot/unclear: {"type": "...", '
        '"reply": "<short warm 1-3 sentence reply in English or Hindi, matching the user>"}\n'
        '- forgot_password: {"type": "forgot_password", "reply": "<briefly reassure them, then '
        'ask for their registered email address or mobile number, in English or Hindi>"}\n'
        '- register: {"type": "register", "reply": "<briefly welcome them, then ask for their '
        'title/salutation — Mr, Mrs, Ms, or Dr — to begin signup, in English or Hindi>"}\n'
        '- login: {"type": "login", "reply": "<briefly welcome them back, then ask for their '
        'registered email address or mobile number, in English or Hindi>"}\n'
        '- course_info: {"type": "course_info", "search_term": "<a short keyword to search '
        "courses with (e.g. 'instagram', 'marketing', 'entrepreneur'), or an empty string "
        'if they just want to see what\'s available in general>"}\n'
        '- bundle_info: {"type": "bundle_info", "reply": "<short acknowledgement that you\'re '
        'pulling up the bundles, in English or Hindi>"}'
    )
    raw = _chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user_message}],
        temperature=0, json_mode=True,
    )
    return _parse_json_reply(raw)


# ---------------------------------------------------------------------------
# Rozzgaar-specific: guided field collection for register/login flows
# ---------------------------------------------------------------------------
FIELD_PROMPTS = {
    "salutation": "their title/salutation (Mr, Mrs, Ms, or Dr)",
    "name": "their full name",
    "mobile": "their 10-digit Indian mobile number",
    "email": "their email address",
    "password": "a password they'd like to set (at least 6 characters)",
    "state": "which Indian state they live in",
    "district": "which district (within their state) they live in",
    "identifier": "their registered email address OR mobile number (either works to log in)",
    "login_password": "their account password",
}


def flow_step(field_name: str, collected: dict, user_message: str, forced_lang: str | None = None) -> dict:
    """
    ONE call that both validates the user's answer for `field_name` (fixing
    for typos/informal input — e.g. spoken-out digits, spaces in phone
    numbers, Devanagari numerals) AND phrases the next question — in
    whatever language the user is using. This is used turn-by-turn while
    walking through registration or login.

    Returns:
      {"valid": true,  "value": "<cleaned value>", "message": "<next question, or a short confirmation, in user's language>"}
      {"valid": false, "value": null, "message": "<gentle error + re-ask, in user's language>"}
    """
    field_desc = FIELD_PROMPTS.get(field_name, field_name)
    system = (
        "You are helping an ordinary person (who may not read/write well, and may write in "
        "Hindi, English, or Hinglish) fill in one field of a form on Rozzgaar, a "
        "skills-course website. This assistant supports ONLY English and Hindi (Hindi may "
        f"be Devanagari script or romanized Hinglish — treat both as Hindi). {_lang_instruction(forced_lang)}\n\n"
        f"You are currently collecting: {field_desc}.\n"
        "Look at their latest message and decide if it contains a valid answer for THIS "
        "field specifically (ignore typos/spacing/spoken-style numbers — e.g. '9 8 7 6...' "
        "or Devanagari digits count as a valid mobile number, just clean it up to plain "
        "digits). If it's a mobile number, it must be exactly 10 digits. If it's an email, "
        "it must look like a real email address. If it's a password, it must be at least 6 "
        "characters (never repeat the password back in your reply, just confirm you got it). "
        "If invalid, gently explain what's wrong and ask again, in their language.\n\n"
        'Respond with JSON ONLY: {"valid": true/false, "value": "<cleaned value or null>", '
        '"message": "<short friendly message: either a brief confirmation + the NEXT thing '
        "you'll need (don't invent what's next — just acknowledge), or a gentle re-ask if "
        'invalid — in English or Hindi, matching the user>"}'
    )
    user = f"Already collected so far: {json.dumps(collected, ensure_ascii=False)}\nTheir latest message: {user_message}"
    raw = _chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0, json_mode=True,
    )
    parsed = _parse_json_reply(raw, fallback_type=None, fallback_reply=None)
    if "valid" not in parsed:
        return {"valid": False, "value": None, "message": "Sorry, could you say that again?"}
    return parsed


_YES_WORDS = {
    "yes", "y", "yeah", "yep", "yup", "correct", "confirm", "confirmed", "ok", "okay",
    "right", "sure", "ha", "haan", "han", "haa", "ji", "ji haan", "ji han", "theek",
    "thik", "theek hai", "thik hai", "sahi", "sahi hai", "sahi h", "bilkul", "haanji",
}
_NO_WORDS = {
    "no", "n", "nah", "nope", "nahi", "nahin", "na", "galat", "wrong", "incorrect",
    "galat hai", "not correct", "no wrong",
}


def interpret_confirmation(message: str, valid_fields: list, field_labels: dict, context: str = "") -> dict:
    """
    Used at a "is this correct?" (single field) or "here's everything —
    shall I go ahead?" (review) step. Figures out whether the user's reply
    means: everything's fine ("yes"), something's wrong but they didn't say
    what ("no"), or they named exactly which field to change ("edit").
    Auto-detects language/typos/Hinglish; a handful of very common
    yes/no words are matched directly (cheap + instant), everything else
    falls back to the LLM.

    Returns: {"decision": "yes"|"no"|"edit", "field": "<one of valid_fields, or null>"}
    """
    text = message.strip().lower()
    if text in _YES_WORDS:
        return {"decision": "yes", "field": None}
    if text in _NO_WORDS:
        return {"decision": "no", "field": None}

    labels_desc = ", ".join(f"'{f}' ({field_labels.get(f, f)})" for f in valid_fields)
    system = (
        "The user is being asked to confirm one or more details they just gave in a "
        "signup/login chat flow on Rozzgaar (a skills-course website). Figure out what "
        "their reply means. Auto-detect their language/script (Hindi/English/Hinglish/any "
        "script, typos ok) — you don't need to reply in it, just classify.\n\n"
        "Classify into exactly one of:\n"
        '- "yes": they confirm everything is correct / go ahead.\n'
        '- "no": they say something is wrong, but did NOT name which field.\n'
        '- "edit": they specifically named which field to change. The only valid fields '
        f"are: {labels_desc}.\n\n"
        'Respond with JSON ONLY: {"decision": "yes"|"no"|"edit", '
        f'"field": "<one of [{", ".join(valid_fields)}], or null if decision is not edit>"}}'
    )
    raw = _chat(
        [{"role": "system", "content": system}, {"role": "user", "content": message}],
        temperature=0, json_mode=True,
    )
    parsed = _parse_json_reply(raw, fallback_type=None, fallback_reply=None)
    if "decision" not in parsed or parsed["decision"] not in ("yes", "no", "edit"):
        return {"decision": "no", "field": None}
    if parsed.get("field") not in valid_fields:
        parsed["field"] = None
    if parsed["decision"] == "edit" and not parsed["field"]:
        parsed["decision"] = "no"
    return parsed


def detect_stop_intent(message: str) -> bool:
    """
    Fallback check for whether the user wants to stop/cancel the
    signup/login/forgot-password flow they're currently in — used when the
    fast hard-coded keyword list (CANCEL_WORDS in main.py) doesn't match, so
    less common English/Hindi/Hinglish phrasings ("I don't want to continue
    with this", "isko rehne do abhi", "mujhe nahi karna", "band kar do
    please") are still caught instead of being fed into field validation.

    Returns True/False only — no reply text is generated here.
    """
    text = message.strip()
    if not text:
        return False
    system = (
        "The user is in the middle of a step-by-step signup/login/forgot-password chat "
        "flow on Rozzgaar, a skills-course website. They may write in English, Hindi "
        "(Devanagari), or Hinglish (romanized Hindi), with typos or broken grammar. Decide "
        "ONLY whether their latest message is them wanting to STOP/CANCEL/EXIT the flow "
        "entirely (e.g. 'stop', 'cancel this', 'ruk jao', 'band karo', 'rehne do', 'mujhe "
        "nahi karna ab', 'I don't want to continue', 'chhod do isko') — as opposed to them "
        "just answering the current question (a name, number, email, password, state, "
        "'yes'/'no', an OTP, etc.), even if that answer is unusual, invalid, or typo'd.\n\n"
        'Respond with JSON ONLY: {"stop": true or false}'
    )
    raw = _chat(
        [{"role": "system", "content": system}, {"role": "user", "content": text}],
        temperature=0, json_mode=True,
    )
    parsed = _parse_json_reply(raw, fallback_type=None, fallback_reply=None)
    return bool(parsed.get("stop") is True)


def phrase_message(intent_description: str, context: str = "", forced_lang: str | None = None) -> str:
    """
    General-purpose: ask the LLM to phrase ONE short message for a specific
    situation (e.g. 'ask the user for their name to start registration',
    or 'tell the user registration succeeded, ask them to log in now').
    Matches the forced session language if set, otherwise auto-detects the
    language of the ORIGINAL user message passed in `context`.
    """
    system = (
        "You write short, warm, simple messages (1-2 sentences) for a chatbot on Rozzgaar, "
        "a skills-course website, for users who may not read/write well. This assistant "
        "supports ONLY English and Hindi (Devanagari or romanized Hinglish both count as "
        f"Hindi). {_lang_instruction(forced_lang)} No jargon."
    )
    user = f"User's message (match this language): {context}\n\nWrite this message: {intent_description}"
    return _chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.4,
    )


def summarize_site_overview(
    user_message: str, courses: list, bundles: list, forced_lang: str | None = None
) -> str:
    """"Explore" should read like a quick bird's-eye tour of the whole site,
    not a course listing — one short summary folding in courses, bundles,
    AND (mentioned, not fetched — there's no API for this, it's just how
    Rozzgaar works) that a quiz/certificate follows each course."""
    system = (
        "You give a short, high-level overview of what Rozzgaar (rozzgaar.in) offers, to "
        "someone who just tapped 'Explore' and doesn't yet know what's on the site. This "
        "assistant supports ONLY English and Hindi (Devanagari or romanized Hinglish both "
        f"count as Hindi). {_lang_instruction(forced_lang)}\n\n"
        "Rozzgaar sells short online skill/certification courses, sold both individually "
        "and as bundles (combo packs that group a few courses together at one price); "
        "after finishing a course, learners take a quiz and can earn a verifiable "
        "certificate.\n\n"
        "Using the real course/bundle data given below, write ONE SHORT, warm, "
        "conversational SUMMARY (3-5 sentences) that gives a bird's-eye feel for the site: "
        "roughly how many courses are on offer and name 2-3 real ones, mention that bundles "
        "exist as a cheaper combo option, and mention certificates are earned after a quiz. "
        "Do NOT list every course/bundle or dump raw data — this is a tour, not a "
        "catalogue. If the data is empty, say so plainly and point them to rozzgaar.in."
    )
    data_preview = json.dumps(
        {"courses": courses[:20], "bundles": bundles[:10]}, default=str
    )
    user = f"User's message: \"{user_message}\"\nSite data: {data_preview}\n\nWrite the overview summary now."
    return _chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.4,
    )


def summarize_courses(user_message: str, courses: list, forced_lang: str | None = None) -> str:
    """Turns raw course-list API rows into one short, human, plain-language answer."""
    system = (
        "You explain course listings from Rozzgaar to an ordinary person who may not "
        "read/write well. This assistant supports ONLY English and Hindi (Devanagari or "
        f"romanized Hinglish both count as Hindi). {_lang_instruction(forced_lang)} Write a "
        "SHORT, clear, conversational summary (2-5 sentences) "
        "answering their question directly, mentioning real course names/prices from the "
        "data. No jargon, no raw JSON. If there are no results, say so plainly and suggest "
        "browsing all courses instead."
    )
    data_preview = json.dumps(courses[:20], default=str)
    user = f"User's question: \"{user_message}\"\nCourse data (up to 20 shown): {data_preview}\n\nWrite the summary now."
    return _chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.3,
    )