"""
main.py
-------
FastAPI backend for the Rozzgaar assistant.

Endpoints:
  POST /chat       - the conversation itself
  POST /tts/speak  - text -> MP3 speech (Microsoft Edge neural TTS, free, no API key)
  GET  /health

Every /chat request must include a `session_id` (the frontend generates one
UUID per browser tab and reuses it for the whole conversation) — this is how
the bot remembers "we're 3 questions into registering this person" between
messages, since HTTP itself is stateless.

Registration/login/forgot-password are all walked field-by-field, tracked
in session_store as `mode`:
  1. "ask"    — ask for the field, validate/clean whatever they typed, then
                commit it immediately and move straight to the next field
                (no per-field "is that right?" step for any flow).
  2. "review" — once every field for the flow is collected, show the full
                form back to them and ask for one go-ahead (or let them
                name a specific field to fix) before the real
                register/login/forgot-password API call is made. This is
                the only confirmation step in the whole flow.

Every /chat response also includes a `form` object describing the exact
registration/login form and how much of it is filled in so far, so the
frontend can render the actual form UI (not just chat bubbles) and keep it
in sync with the conversation. On a successful login, the response also
sets `redirect`, telling the frontend to hand the user off to the other
(page-reading) assistant now that they're authenticated.

Language is 100% automatic throughout — see llm.py and lang_utils.py.

Run it with:
    uvicorn main:app --reload --port 8000
"""

from dotenv import load_dotenv
load_dotenv()

import os
import re

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

import llm
import lang_utils
import session_store
import ticket_store
import rozzgaar_api
import static_content
import tts

# Shared secret between this backend and rozzgaar.in's chatbot-login.php.
# Must be the EXACT SAME value as CHATBOT_INTERNAL_SECRET in that PHP file.
# Set it in backend/.env as INTERNAL_HANDOFF_SECRET=<a long random string>.
INTERNAL_HANDOFF_SECRET = os.getenv("INTERNAL_HANDOFF_SECRET", "")

app = FastAPI(title="Rozzgaar Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

REGISTER_FIELDS = ["salutation", "name", "mobile", "email", "password", "state", "district"]
LOGIN_FIELDS = ["identifier", "login_password"]
FORGOT_FIELDS = ["identifier"]

FIELD_ORDER = {"register": REGISTER_FIELDS, "login": LOGIN_FIELDS, "forgot_password": FORGOT_FIELDS}

# Labels shown on the live form UI (kept in English/short — the actual
# chat conversation is what's fully auto-translated, this is just a label).
FIELD_LABELS = {
    "salutation": "Title",
    "name": "Full Name",
    "mobile": "Mobile Number",
    "email": "Email Address",
    "password": "Password",
    "state": "State",
    "district": "District",
    "identifier": "Email or Mobile",
    "login_password": "Password",
}

MASKED_FIELDS = {"password", "login_password"}

# Title/State/District are offered as a tappable, choosable list alongside
# the normal text box — not instead of it. Typing still works (free text
# still goes through llm.flow_step's validation, same as ever); this just
# gives low-literacy / mobile users something to pick from instead of
# having to spell out a state or district by hand.
SALUTATION_OPTIONS = [
    {"value": "Mr", "label": "Mr"},
    {"value": "Mrs", "label": "Mrs"},
    {"value": "Ms", "label": "Ms"},
    {"value": "Dr", "label": "Dr"},
]


def _options_from_api_list(data) -> list[dict] | None:
    """Normalize whatever shape the real Rozzgaar API hands back for a
    states/districts list (a plain list of strings, or a list of
    {"name"/"state"/"district": ...} objects) into a flat
    [{"value", "label"}, ...] the frontend picker can render directly."""
    if not data:
        return None
    options = []
    for item in data:
        if isinstance(item, str):
            label = item
            value = item
        elif isinstance(item, dict):
            label = (
                item.get("name") or item.get("state") or
                item.get("district") or item.get("label") or item.get("title")
            )
            value = item.get("value", label)
        else:
            continue
        if label:
            options.append({"value": value, "label": label})
    return options or None


# Small in-memory cache so re-asking (an invalid district, a page that
# re-renders the same step, etc.) doesn't hit the real Rozzgaar API again
# for a list that basically never changes within a session.
_states_cache: list[dict] | None = None
_districts_cache: dict[str, list[dict] | None] = {}


# Fields answered via a real, API-backed picker list rather than free
# typing (salutation is a fixed list; state/district come live from
# rozzgaar.in's own /misc/states and /misc/districts). These get matched
# directly against that real list — see _match_picker_option — instead of
# being sent to the generic LLM validator in llm.flow_step, which has no
# idea what the actual state/district names are and can wrongly accept or
# reject a perfectly valid tap.
PICKER_FIELDS = {"salutation", "state", "district"}


def _match_picker_option(message: str, options: list[dict]) -> str | None:
    """Case/whitespace-tolerant match of the user's message (a tap sends
    the option's value/label verbatim; a typed answer might differ in
    case) against the real options list. Returns the canonical value to
    store, or None if it matches nothing on the list."""
    text = (message or "").strip().lower()
    if not text:
        return None
    for opt in options:
        value, label = str(opt.get("value", "")), str(opt.get("label", ""))
        if value.strip().lower() == text or label.strip().lower() == text:
            return opt.get("value") or opt.get("label")
    return None


def _field_options(field: str | None, state: dict) -> list[dict] | None:
    """Fixed/looked-up choices for the field currently being asked, or None
    for any field with no such list (free typing is the only way to answer
    those, same as before)."""
    global _states_cache

    if field == "salutation":
        return SALUTATION_OPTIONS

    if field == "state":
        if _states_cache is None:
            try:
                _states_cache = _options_from_api_list(rozzgaar_api.list_states())
            except ValueError:
                return None  # Real API unreachable — fall back to free typing.
        return _states_cache

    if field == "district":
        state_value = (state.get("collected") or {}).get("state")
        if not state_value:
            return None
        if state_value not in _districts_cache:
            try:
                _districts_cache[state_value] = _options_from_api_list(
                    rozzgaar_api.list_districts(state_value)
                )
            except ValueError:
                return None
        return _districts_cache[state_value]

    return None

# Buttons shown after a greeting / when we're not sure what the user wants —
# these send a fixed, plain message exactly as if the user had typed it, so
# they go through the normal intent classification below.
GUEST_QUICK_REPLIES = [
    {"label": "🔑 Login", "message": "login"},
    {"label": "📝 Register", "message": "register"},
    {"label": "📚 Explore", "message": "explore rozzgaar"},
    {"label": "🎁 Bundles", "message": "show me all bundles"},
]
LOGGED_IN_QUICK_REPLIES = [
    {"label": "📚 Explore", "message": "explore rozzgaar"},
    {"label": "🎁 Bundles", "message": "show me all bundles"},
    {"label": "🎓 Enrollments", "message": "show my enrollments"},
    {"label": "🚪 Logout", "message": "logout"},
]

# Fixed marker for the "Logout" button — never something a real user would
# type. Without this, a session that has ever logged in stays logged in
# forever (session_store never expires it on its own), so reopening the
# widget in the same tab — or a different person using the same browser —
# always lands on the previous user's dashboard with no way back to guest
# state. See session_store.logout().
LOGOUT_COMMAND = "logout"

# Yes/No buttons for the couple of spots that ask a plain yes/no question —
# low-literacy users shouldn't have to type "yes"/"no" (or "haan"/"nahi")
# by hand when a tap will do.
YES_NO_LOGIN_NOW = [
    {"label": "✅ Yes, log me in", "message": "yes"},
    {"label": "Not now", "message": "no"},
]
YES_NO_CANCEL = [
    {"label": "🛑 Yes, stop", "message": "yes"},
    {"label": "↩️ No, continue", "message": "no"},
]

# A course/bundle "Enroll" button sends this exact marker (never something a
# real user would type), so it's handled directly rather than through the
# LLM intent classifier — see the top of /chat. The slug is prefixed with
# its kind ("course" or "bundle") so the right checkout URL (?type=...) gets
# built — see _send_to_payment().
ENROLL_MARKER = "__enroll__"

# There is no "free enroll" API — enrolling only actually happens once the
# user pays on the real Rozzgaar checkout page. Clicking "Enroll" sends them
# there; "I've completed payment" re-checks their real enrollments to see if
# it went through.
PAYMENT_URL_TEMPLATE = "https://rozzgaar.in/applicant/course-payment?type={kind}&id={slug}"
ENROLL_CHECK_MARKER = "__enroll_check__"

PAYMENT_QUICK_REPLIES = [
    {"label": "✅ I've completed payment", "message": ENROLL_CHECK_MARKER},
]

# Fixed quick-reply / menu commands. These are exact button labels' `message`
# values — never something a real user free-types — so clicking one of them
# ALWAYS wins over whatever flow happens to still be active in this session
# (e.g. a stale registration left over from before a page refresh), instead
# of being silently swallowed as an answer to whatever field was last asked.
MENU_COMMANDS = {
    "login", "register", "explore rozzgaar", "show me all courses", "show me all bundles",
    "show my enrollments", "about rozzgaar", "contact rozzgaar", "verify certificate",
}

# Password prompts are NEVER phrased by the LLM. Asking a model to generate
# "ask the user for their password" can (rarely, especially in Hindi) get
# misread by the model's own safety filter as a phishing-style request and
# refused outright — which is exactly what was happening. Fixed bilingual
# text sidesteps that risk entirely and is also more predictable for
# low-literacy users.
CANNED_MESSAGES = {
    "ask_new_password": {
        "en": "Got it. Now please set a password for your account (at least 6 characters).",
        "hi": "ठीक है। अब कृपया अपने खाते के लिए एक पासवर्ड बनाएं (कम से कम 6 अक्षर)।",
    },
    "ask_login_password": {
        "en": "Thanks. Now please enter your account password to log in.",
        "hi": "धन्यवाद। अब लॉगिन करने के लिए कृपया अपना पासवर्ड डालें।",
    },
    "duplicate_account_ask_password": {
        "en": "That's already registered — no need to sign up again, just log in. Please enter your account password.",
        "hi": "यह पहले से रजिस्टर्ड है — दोबारा साइन अप करने की जरूरत नहीं, बस लॉगिन कर लीजिए। कृपया अपना पासवर्ड डालें।",
    },
}


def _canned(key: str, forced_lang: str | None) -> str:
    return CANNED_MESSAGES[key].get(forced_lang or "en", CANNED_MESSAGES[key]["en"])

CANCEL_WORDS = {
    # English
    "cancel", "stop", "exit", "quit", "abort", "nevermind", "never mind", "forget it",
    "leave it", "skip this", "not now", "stop it", "stop this", "cancel this",
    "cancel it", "don't want this", "dont want this", "i don't want to continue",
    "i dont want to continue", "don't want to continue", "dont want to continue",
    # Hinglish (romanized Hindi)
    "band karo", "band kro", "band kardo", "band kar do", "ruko", "ruk jao", "rukja",
    "rehne do", "rehne do isse", "chhodo", "chodo", "chhod do", "chod do", "chhodo isse",
    "bas karo", "bas kro", "cancel karo", "exit karo", "quit karo", "close karo",
    "mat karo", "nahi karna", "nahin karna", "nahi karna hai", "nahin karna hai",
    "mujhe nahi karna", "mujhe nahin karna", "rukiye", "rok do", "rok dijiye",
    "cancel kar do", "cancel kardo", "cancel kijiye", "radd karo", "raddh karo",
    # Hindi (Devanagari)
    "रोको", "रुको", "रुक जाओ", "बंद करो", "बन्द करो", "रहने दो", "छोड़ो", "छोड़ दो",
    "बस करो", "मत करो", "नहीं करना", "नहीं करना है", "मुझे नहीं करना", "रद्द करो",
    "रद करो", "कैंसिल करो", "कैंसल करो",
}


class ChatRequest(BaseModel):
    message: str
    # No default here on purpose: session_id used to default to "default"
    # when missing, which would silently merge every such caller into one
    # shared in-memory session — including its access token — and could
    # show one guest another guest's logged-in state. Now a missing
    # session_id is rejected by FastAPI's validation instead.
    session_id: str
    lang: str | None = None  # "en" | "hi" — the language the user picked at the frontend's
                              # language gate. Once set for a session it's forced for every
                              # reply, overriding per-message auto-detection.


class ChatResponse(BaseModel):
    reply: str
    lang: str = "en-IN"                # auto-detected language of `reply` — used for voice output
    awaiting_field: str | None = None  # e.g. "password", "confirm_email", "review_confirm"
    form: dict | None = None           # live registration/login form state for the UI, or None
    redirect: str | None = None        # e.g. "dashboard" once login succeeds
    user_name: str | None = None       # logged-in user's name, sent alongside a "dashboard" redirect
    logged_in: bool = False            # whether this session currently has a real access_token
    quick_replies: list[dict] | None = None  # [{"label": "...", "message": "..."}] buttons to show
    field_options: list[dict] | None = None  # [{"value": "...", "label": "..."}] choosable list for
                                              # the field named in awaiting_field (e.g. Title/State/
                                              # District) — shown alongside, not instead of, the text box
    courses: list[dict] | None = None  # [{"slug", "title", "price"}] cards to show, with an Enroll button
    payment_url: str | None = None     # real Rozzgaar checkout URL to send the user to right now
    handoff_ticket: str | None = None  # one-time ticket for rozzgaar.in/chatbot-login.php, sent
                                        # alongside redirect="dashboard" — see ticket_store.py


class TTSRequest(BaseModel):
    text: str
    lang: str = "en-IN"


class RedeemTicketRequest(BaseModel):
    ticket: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/internal/redeem-ticket")
def redeem_ticket(body: RedeemTicketRequest, x_internal_secret: str | None = Header(None)):
    """
    Server-to-server only — called by rozzgaar.in's chatbot-login.php, never by a
    browser. Redeems a one-time handoff ticket for the real access_token +
    user payload. Requires the shared secret in the X-Internal-Secret header.
    """
    if not INTERNAL_HANDOFF_SECRET or x_internal_secret != INTERNAL_HANDOFF_SECRET:
        raise HTTPException(status_code=403, detail="forbidden")

    payload = ticket_store.redeem(body.ticket)
    if payload is None:
        raise HTTPException(status_code=404, detail="invalid or expired ticket")

    return payload


@app.get("/misc/states")
def misc_states():
    try:
        data = rozzgaar_api.list_states()
        return {"status": "success", "data": data}
    except ValueError as e:
        return {"status": "error", "message": str(e)}


@app.get("/misc/districts")
def misc_districts(state: str):
    try:
        data = rozzgaar_api.list_districts(state)
        return {"status": "success", "data": data}
    except ValueError as e:
        return {"status": "error", "message": str(e)}


@app.post("/tts/speak")
async def tts_speak(req: TTSRequest):
    audio = await tts.synthesize_speech(req.text, req.lang)
    return Response(content=audio, media_type="audio/mpeg")


def _is_cancel(message: str) -> bool:
    text = message.strip().lower()
    if text in CANCEL_WORDS:
        return True
    # Also catch it wrapped in a short phrase, e.g. "please stop", "I want to exit".
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in CANCEL_WORDS)


def _should_cancel(message: str) -> bool:
    """
    _is_cancel() is a cheap, instant check against a fixed word/phrase list —
    but people phrase "I want to stop" in far more ways than any fixed list
    can cover (especially in Hindi/Hinglish). If the fast check doesn't
    match, fall back to asking the LLM specifically whether THIS message
    means stop/cancel, rather than silently feeding it into normal field
    validation and confusing the user.
    """
    if _is_cancel(message):
        return True
    try:
        return llm.detect_stop_intent(message)
    except RuntimeError:
        # every LLM provider is down right now — fall back to keyword-only.
        return False


def _mask(field: str, value) -> str:
    if field in MASKED_FIELDS:
        return "•" * min(len(str(value)), 10)
    return str(value)


def _awaiting(field: str, mode: str) -> str:
    if mode == "confirm":
        return f"confirm_{field}"
    if mode == "review":
        return "review_confirm"
    if field in MASKED_FIELDS:
        return "password"
    return field


def build_form(state: dict) -> dict | None:
    """Live snapshot of the registration/login form for the frontend to
    render as an actual form (not just chat text) — which fields are done,
    which one is active right now, and what's still pending."""
    flow = state.get("flow")
    if flow not in ("register", "login"):
        return None
    order = FIELD_ORDER[flow]
    collected = state["collected"]
    fields = []
    for f in order:
        if f in collected:
            status, value = "done", _mask(f, collected[f])
        elif f == state.get("step") and state.get("mode") in ("ask", "confirm"):
            status = "active"
            value = _mask(f, state["pending_value"]) if state.get("mode") == "confirm" and state.get("pending_value") is not None else None
        else:
            status, value = "pending", None
        fields.append({"name": f, "label": FIELD_LABELS.get(f, f), "value": value, "status": status})
    return {"flow": flow, "mode": state.get("mode"), "fields": fields}


# ---------------------------------------------------------------------------
# Finalizing a flow once every field has been confirmed
# ---------------------------------------------------------------------------
DUPLICATE_ACCOUNT_HINTS = (
    "already registered", "already exists", "already exist", "already taken",
    "already in use", "already have an account", "already associated",
)


def _finalize_register(session_id: str, state: dict, message: str):
    forced_lang = state.get("forced_lang")
    collected = state["collected"]
    try:
        data = rozzgaar_api.register_start(
            salutation=collected["salutation"], name=collected["name"],
            mobile=collected["mobile"], email=collected["email"],
            password=collected["password"], state=collected["state"],
            district=collected["district"],
        )
    except ValueError as e:
        err_text = str(e)
        if any(hint in err_text.lower() for hint in DUPLICATE_ACCOUNT_HINTS):
            # They already have an account on this mobile/email. Rather than
            # dead-ending on an error, drop them straight into the login
            # flow — with the identifier already filled in — and show the
            # login form.
            use_email = "email" in err_text.lower() and "mobile" not in err_text.lower()
            identifier = (collected.get("email") if use_email else collected.get("mobile")) \
                or collected.get("mobile") or collected.get("email")
            state["flow"], state["mode"], state["step"] = "login", "ask", "login_password"
            state["collected"] = {"identifier": identifier}
            state["pending_value"], state["editing_from_review"] = None, False
            reply = _canned("duplicate_account_ask_password", forced_lang)
            return reply, _awaiting("login_password", "ask"), None
        session_store.reset_flow(session_id)
        return err_text, None, None

    identifier = collected.get("mobile") or collected.get("email")
    state["flow"], state["mode"], state["step"] = "post_register", "login_prompt", None
    state["collected"] = {"identifier": identifier}
    state["pending_value"], state["editing_from_review"] = None, False
    reply = llm.phrase_message(
        "Tell the user, clearly and warmly: 'Your registration is successful!' Then ask "
        "if they'd like to log in now.",
        context=message, forced_lang=forced_lang,
    )
    return reply, "post_register_login", None


def _finalize_login(session_id: str, state: dict, message: str):
    forced_lang = state.get("forced_lang")
    collected = state["collected"]
    identifier = collected["identifier"]
    field = "email" if "@" in identifier else "mobile"
    try:
        data = rozzgaar_api.login(field, identifier, collected["login_password"])
    except ValueError as e:
        session_store.reset_flow(session_id)
        reply = llm.phrase_message(
            f"Tell the user login failed with this reason: '{e}'. Gently ask if they'd like "
            "to try again, or if they'd like help resetting their password instead.",
            context=message, forced_lang=forced_lang,
        )
        return reply, None, None

    state["token"] = data.get("access_token")
    state["user"] = data.get("user") or {}
    user_name = state["user"].get("name")
    state["name"] = user_name
    pending_slug = state.get("pending_enroll_slug")
    pending_kind = state.get("pending_enroll_kind", "course")
    state["pending_enroll_slug"] = None
    state["pending_enroll_kind"] = None
    session_store.reset_flow(session_id)
    name_hint = f" Their name is {user_name}." if user_name else ""

    if pending_slug:
        # They clicked "Enroll" before logging in — now that they're in,
        # send them on to the real checkout page to finish it.
        name_suffix = f", {user_name}" if user_name else ""
        welcome = {
            "en": f"Welcome back{name_suffix}! ",
            "hi": f"वापसी पर स्वागत है{name_suffix}! ",
        }.get(forced_lang or "en")
        reply, quick_replies, payment_url = _send_to_payment(
            state, pending_slug, forced_lang, message, kind=pending_kind, welcome_hint=welcome,
        )
        state["_extra"] = {"quick_replies": quick_replies, "payment_url": payment_url}
        return reply, None, None

    reply = llm.phrase_message(
        f"Warmly welcome the user back — login succeeded.{name_hint} Tell them you're now "
        "taking them to their dashboard assistant.",
        context=message, forced_lang=forced_lang,
    )
    return reply, None, "dashboard"


def _finalize_forgot_password(session_id: str, state: dict, message: str):
    forced_lang = state.get("forced_lang")
    identifier = state["collected"]["identifier"]
    try:
        rozzgaar_api.forgot_password(identifier)
    except ValueError:
        pass  # the real API intentionally always returns a generic success-shaped message
    session_store.reset_flow(session_id)
    reply = llm.phrase_message(
        "Tell the user that if an account exists with those details, a password reset link "
        "has been sent to their email, valid for 5 minutes.",
        context=message, forced_lang=forced_lang,
    )
    return reply, None, None


_FINALIZERS = {
    "register": _finalize_register,
    "login": _finalize_login,
    "forgot_password": _finalize_forgot_password,
}


def _build_review_message(state: dict, message: str) -> str:
    forced_lang = state.get("forced_lang")
    flow = state["flow"]
    order = FIELD_ORDER[flow]
    collected = state["collected"]
    lines = [f"- {FIELD_LABELS.get(f, f)}: {_mask(f, collected.get(f, ''))}" for f in order]
    summary = "\n".join(lines)
    verb = {"register": "create your account", "login": "log you in",
            "forgot_password": "send the reset link"}[flow]
    intro = llm.phrase_message(
        "Tell the user you've got all the details (don't list them yourself, a summary is "
        f"shown separately) and ask them to check it below, then reply 'yes' to {verb}, or "
        "tell you what to change.",
        context=message, forced_lang=forced_lang,
    )
    return f"{intro}\n\n{summary}"


def _advance_after_field(session_id: str, state: dict, message: str):
    forced_lang = state.get("forced_lang")
    flow, step = state["flow"], state["step"]
    order = FIELD_ORDER[flow]

    if state.get("editing_from_review"):
        # District is scoped to state (the picker list itself comes from
        # /misc/districts?state=...), so a district picked under the OLD
        # state no longer makes sense once state changes here. Don't just
        # bounce back to the review screen with a stale district — make
        # the user re-pick district for the new state first, then return
        # to review once that's done.
        if flow == "register" and step == "state":
            state["mode"], state["step"] = "ask", "district"
            reply = llm.phrase_message(
                "Acknowledge the state change, then ask again for "
                f"{llm.FIELD_PROMPTS.get('district', 'district')}, since it needs to match the new state.",
                context=message, forced_lang=forced_lang,
            )
            return reply, _awaiting("district", "ask"), None
        state["editing_from_review"] = False
        state["mode"], state["step"] = "review", None
        return _build_review_message(state, message), "review_confirm", None

    idx = order.index(step)
    if idx + 1 < len(order):
        next_field = order[idx + 1]
        state["mode"], state["step"] = "ask", next_field
        if next_field in MASKED_FIELDS:
            # Fixed canned text — never LLM-phrased, see CANNED_MESSAGES.
            key = "ask_new_password" if next_field == "password" else "ask_login_password"
            reply = _canned(key, forced_lang)
        else:
            reply = llm.phrase_message(
                f"Briefly acknowledge you got that, then ask for {llm.FIELD_PROMPTS.get(next_field, next_field)}.",
                context=message, forced_lang=forced_lang,
            )
        return reply, _awaiting(next_field, "ask"), None

    if flow == "login":
        # Login has no review/confirm screen at all — once both fields
        # (identifier + password) are in, log straight in.
        return _finalize_login(session_id, state, message)

    state["mode"], state["step"] = "review", None
    return _build_review_message(state, message), "review_confirm", None


def _reask_current(state: dict, message: str):
    """
    Used after the user is asked "are you sure you want to stop?" and says
    no (or anything that isn't a clear yes) — picks back up exactly where
    they left off and re-asks for that same field/step, the same way it's
    normally asked during registration/login, without losing any progress.
    """
    forced_lang = state.get("forced_lang")
    flow, mode, step = state["flow"], state["mode"], state["step"]

    if flow == "post_register" and mode == "login_prompt":
        reply = llm.phrase_message(
            "Continuing where we left off — ask again if the user would like to log in now.",
            context=message, forced_lang=forced_lang,
        )
        return reply, "post_register_login", None


    if mode == "review":
        return _build_review_message(state, message), "review_confirm", None

    if mode == "confirm":
        reply = llm.phrase_message(
            f"Continuing where we left off — ask again if the value they gave for "
            f"{llm.FIELD_PROMPTS.get(step, step)} is correct (yes, or no to fix it). "
            "Never repeat a password back.",
            context=message, forced_lang=forced_lang,
        )
        return reply, _awaiting(step, "confirm"), None

    # mode == "ask" (or anything unexpected — safest default)
    if step in MASKED_FIELDS:
        key = "ask_new_password" if step == "password" else "ask_login_password"
        reply = _canned(key, forced_lang)
    else:
        reply = llm.phrase_message(
            f"Continuing where we left off — ask again for {llm.FIELD_PROMPTS.get(step, step)}.",
            context=message, forced_lang=forced_lang,
        )
    return reply, _awaiting(step, "ask"), None


def _normalize_email_input(value: str) -> str:
    """Normalize typed/spoken email input deterministically.

    Email is treated as English input regardless of the selected chat language.
    Speech recognition may return phrases such as ``name dot test at gmail dot
    com``; those phrases are converted before validation/API submission.
    """
    value = (value or "").strip().lower()

    value = re.sub(r"\b(?:at the rate|at rate|at sign|at the rate sign|at)\b", "@", value)
    value = re.sub(r"\b(?:dot|period|full stop)\b", ".", value)
    value = re.sub(r"\b(?:underscore|under score)\b", "_", value)
    value = re.sub(r"\b(?:dash|hyphen)\b", "-", value)
    value = re.sub(r"\b(?:plus)\b", "+", value)

    # Speech recognition inserts spaces between words/symbol names. Email
    # addresses themselves must not contain whitespace.
    value = re.sub(r"\s+", "", value)

    value = re.sub(r"\.+@", "@", value)
    value = re.sub(r"@\.+", "@", value)
    value = re.sub(r"\.{2,}", ".", value)
    value = re.sub(r"^[@.]+|[@.]+$", "", value)
    return value


def _is_valid_email(value: str) -> bool:
    return bool(re.fullmatch(
        r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
        r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+",
        value,
    ))


def _email_error_message(forced_lang: str | None) -> str:
    if forced_lang == "hi":
        return "कृपया सही ईमेल पता दर्ज करें, जैसे name@example.com।"
    return "Please enter a valid email address, for example name@example.com."


def _continue_flow(session_id: str, state: dict, message: str):
    forced_lang = state.get("forced_lang")
    # Already asked "are you sure you want to stop?" — this message is the
    # answer to THAT, not a normal field answer.
    if state.get("pending_cancel"):
        verdict = llm.interpret_confirmation(message, [], {}, context=message)
        if verdict["decision"] == "yes":
            session_store.reset_flow(session_id)
            reply = llm.phrase_message(
                "Let the user know their signup/login was cancelled, and ask what else you can help with.",
                context=message, forced_lang=forced_lang,
            )
            return reply, None, None
        # Anything other than a clear "yes" (a "no", or anything unclear)
        # means: don't cancel — pick back up on the same field as before.
        state["pending_cancel"] = False
        return _reask_current(state, message)

    if _should_cancel(message):
        state["pending_cancel"] = True
        reply = llm.phrase_message(
            "Ask the user to confirm they really want to stop this signup/login process now "
            "— let them know anything entered so far will be lost. Ask them to reply yes to "
            "stop, or no to keep going where they left off.",
            context=message, forced_lang=forced_lang,
        )
        return reply, "cancel_confirm", None

    flow, mode, step = state["flow"], state["mode"], state["step"]

    # Right after a successful registration: confirmation was already given,
    # now waiting on yes/no for "would you like to log in now?".
    if flow == "post_register" and mode == "login_prompt":
        verdict = llm.interpret_confirmation(message, [], {}, context=message)
        identifier = state["collected"].get("identifier")
        if verdict["decision"] == "yes":
            state["flow"], state["mode"], state["step"] = "login", "ask", "login_password"
            state["collected"] = {"identifier": identifier}
            state["pending_value"], state["editing_from_review"] = None, False
            reply = llm.phrase_message(
                "Great — ask the user for their account password to log in now.",
                context=message, forced_lang=forced_lang,
            )
            return reply, _awaiting("login_password", "ask"), None
        session_store.reset_flow(session_id)
        reply = llm.phrase_message(
            "Let the user know that's fine, they can log in anytime, and ask what else you "
            "can help with.",
            context=message, forced_lang=forced_lang,
        )
        return reply, None, None

    if mode == "ask":
        if step in MASKED_FIELDS:
            # Passwords are NEVER routed through the LLM "cleanup" step — an
            # LLM asked to normalize/clean text can silently alter characters
            # (trim what it thinks is a stray space, "fix" a typo, etc.),
            # which then no longer matches the password on the real account
            # and login fails even though the user typed it correctly. We
            # validate and store it exactly as sent.
            pwd = message
            if not pwd:
                reply = llm.phrase_message(
                    "Tell the user their password can't be empty, and ask them to try again.",
                    context=message, forced_lang=forced_lang,
                )
                return reply, _awaiting(step, "ask"), None
            if step == "password" and len(pwd) < 6:
                # Only enforce the 6-char minimum when they're SETTING a new
                # password during registration — not when they're typing an
                # existing account's password to log in.
                reply = llm.phrase_message(
                    "Tell the user their password needs to be at least 6 characters, and ask them to try again.",
                    context=message, forced_lang=forced_lang,
                )
                return reply, _awaiting(step, "ask"), None

            # No per-field confirmation for any flow — commit straight away
            # and move to the next field. Register still gets one combined
            # confirmation at the end via the review screen, so nothing
            # here goes unchecked.
            state["collected"][step] = pwd
            state["pending_value"] = None
            return _advance_after_field(session_id, state, message)

        # Salutation/state/district are answered from a real, API-backed
        # picker list — matched directly against that list rather than
        # guessed by the generic LLM validator (see PICKER_FIELDS above).
        if step in PICKER_FIELDS:
            options = _field_options(step, state)
            if options:
                matched = _match_picker_option(message, options)
                if matched is None:
                    reply = llm.phrase_message(
                        f"Tell the user that's not one of the choices shown and ask them "
                        f"again for {llm.FIELD_PROMPTS.get(step, step)}, picking from the list.",
                        context=message, forced_lang=forced_lang,
                    )
                    return reply, _awaiting(step, "ask"), None
                state["collected"][step] = matched
                state["pending_value"] = None
                return _advance_after_field(session_id, state, message)
            # Real list unreachable right now — fall through to the
            # generic LLM validator below so free typing still works.

        # Email addresses are handled deterministically, not by the LLM.
        # Speech recognition often produces "name dot test at gmail dot com".
        if step in ("email", "identifier"):
            normalized = _normalize_email_input(message)
            if "@" in normalized:
                if not _is_valid_email(normalized):
                    reply = _email_error_message(forced_lang)
                    return reply, _awaiting(step, "ask"), None
                message = normalized
            elif step == "email":
                reply = _email_error_message(forced_lang)
                return reply, _awaiting(step, "ask"), None

        result = llm.flow_step(step, state["collected"], message, forced_lang=forced_lang)
        if not result.get("valid"):
            return result.get("message", "Please try again."), _awaiting(step, "ask"), None

        # No per-field confirmation for any flow — commit straight away and
        # move to the next field. Register still gets one combined
        # confirmation at the end via the review screen in
        # _advance_after_field, so nothing here goes unchecked.
        state["collected"][step] = result["value"]
        state["pending_value"] = None
        return _advance_after_field(session_id, state, message)

    if mode == "confirm":
        verdict = llm.interpret_confirmation(message, [step], FIELD_LABELS, context=message)
        if verdict["decision"] == "yes":
            state["collected"][step] = state["pending_value"]
            state["pending_value"] = None
            return _advance_after_field(session_id, state, message)
        state["mode"], state["pending_value"] = "ask", None
        reply = llm.phrase_message(
            f"Apologize briefly and ask the user again for {llm.FIELD_PROMPTS.get(step, step)}.",
            context=message, forced_lang=forced_lang,
        )
        return reply, _awaiting(step, "ask"), None

    if mode == "review":
        order = FIELD_ORDER[flow]
        verdict = llm.interpret_confirmation(message, order, FIELD_LABELS, context=message)
        if verdict["decision"] == "yes":
            return _FINALIZERS[flow](session_id, state, message)
        if verdict["decision"] == "edit" and verdict.get("field"):
            field = verdict["field"]
            state["mode"], state["step"], state["editing_from_review"] = "ask", field, True
            reply = llm.phrase_message(
                f"Ask the user again for {llm.FIELD_PROMPTS.get(field, field)}, since they want to correct it.",
                context=message, forced_lang=forced_lang,
            )
            return reply, _awaiting(field, "ask"), None
        reply = llm.phrase_message(
            "Ask the user which specific detail they'd like to correct (name it), or to say "
            "'yes' if everything is actually fine after all.",
            context=message, forced_lang=forced_lang,
        )
        return reply, "review_confirm", None

    # Shouldn't happen, but fail safe rather than crash.
    session_store.reset_flow(session_id)
    return "Let's start over — what would you like to do?", None, None


def _item_cards(items: list, kind: str = "course") -> list[dict]:
    """Trim raw API course/bundle rows down to just what the 'Enroll' card
    needs. `kind` ("course" or "bundle") travels with each card so the
    frontend's Enroll button can tell _send_to_payment() which checkout
    URL type to build.

    Every item returned by the API (up to the page size already fetched)
    becomes its own tappable card — "Explore"/"Bundles" is meant to
    surface every option on offer, not a truncated preview of it."""
    cards = []
    for c in items:
        if not isinstance(c, dict):
            continue
        slug = c.get("slug") or c.get("id")
        if not slug:
            continue
        cards.append({
            "slug": str(slug),
            "title": c.get("title") or c.get("name") or "Course",
            "price": c.get("price") or c.get("fee") or "",
            "kind": kind,
        })
    return cards


def _handle_course_info(search_term: str, message: str, forced_lang: str | None = None):
    try:
        data = rozzgaar_api.list_courses(search=search_term or None)
    except ValueError:
        return "Sorry, I couldn't fetch course information right now. Please check rozzgaar.in/courses directly, or try again shortly.", []

    # defensive extraction — be tolerant of the exact response shape
    if isinstance(data, dict):
        courses = data.get("courses") or data.get("items") or []
    elif isinstance(data, list):
        courses = data
    else:
        courses = []

    reply = llm.summarize_courses(message, courses, forced_lang=forced_lang)
    return reply, _item_cards(courses, kind="course")


def _handle_site_overview(message: str, forced_lang: str | None = None):
    """"Explore" is meant to answer "what all is on Rozzgaar" at a glance —
    not just courses. Pulls both courses AND bundles and has the LLM fold
    them into ONE short overview (not a full catalogue dump), with a small
    tappable preview of a few real items so the user can act immediately."""
    try:
        course_data = rozzgaar_api.list_courses()
    except ValueError:
        course_data = None

    try:
        bundle_data = rozzgaar_api.list_bundles()
    except ValueError:
        bundle_data = None

    def _extract(data, key):
        if isinstance(data, dict):
            return data.get(key) or data.get("items") or []
        if isinstance(data, list):
            return data
        return []

    courses = _extract(course_data, "courses")
    bundles = _extract(bundle_data, "bundles")

    if not courses and not bundles:
        # The real course/bundle API is down (or genuinely returned nothing)
        # — fall back to crawling rozzgaar.in's own static pages (home/
        # about/contact) so Explore still says something real instead of a
        # flat "couldn't fetch" error. See static_content.py.
        try:
            static_text = static_content.get_static_site_text()
        except ValueError:
            return (
                "Sorry, I couldn't fetch site information right now. Please check rozzgaar.in "
                "directly, or try again shortly."
            ), []
        reply = llm.summarize_static_overview(message, static_text, forced_lang=forced_lang)
        return reply, []

    reply = llm.summarize_site_overview(message, courses, bundles, forced_lang=forced_lang)
    # "Explore" is just a short spoken/written summary of the site now —
    # no tappable course/bundle cards underneath. The user can still type
    # "all courses" / "all bundles" (or tap those dedicated buttons) to
    # get the full, card-based list.
    return reply, []


def _handle_site_question(message: str, forced_lang: str | None = None):
    """Catch-all for real questions about Rozzgaar that aren't a specific
    course/bundle lookup or an account action — company info, certifying
    bodies, contact details, policies, and anything else genuinely unclear
    that might still be answerable from the site. Answers ONLY from text
    crawled directly off rozzgaar.in (see static_content.py) — never
    invented, so a wrong/missing answer just means "not on the site"."""
    try:
        site_text = static_content.get_static_site_text()
    except ValueError:
        return (
            "Sorry, I couldn't check rozzgaar.in for that right now. Please try again "
            "shortly, or check the site directly."
        ), []
    reply = llm.answer_from_site(message, site_text, forced_lang=forced_lang)
    return reply, []


# A certificate number looks like RZG-CERT-XXXXXXXX, but users may type it
# bare, paste it with surrounding text ("please verify RZG-CERT-12345678"),
# or (via voice) with odd spacing/casing — pull out the hyphenated
# alphanumeric token rather than assuming the whole message is the number.
CERTIFICATE_NUMBER_PATTERN = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+){1,4}")


def _extract_certificate_number(text: str) -> str:
    match = CERTIFICATE_NUMBER_PATTERN.search(text or "")
    return (match.group(0) if match else (text or "").strip()).upper()


def _handle_verify_certificate(message: str, certificate_number: str, forced_lang: str | None = None):
    """Looks up a certificate number against the real, public /quiz/verify
    endpoint (open_key only, no login needed — same as course browsing).
    This is a real per-certificate lookup, never guessed from static site
    text, since only the API actually knows if a given number is genuine."""
    try:
        data = rozzgaar_api.verify_certificate(certificate_number)
    except ValueError as e:
        # The API's own message (e.g. "Certificate not found") is already
        # written to be user-facing — same pattern as login/register errors.
        reply = llm.phrase_message(
            f"Tell the user the certificate number '{certificate_number}' could not be "
            f"verified, for this reason: '{e}'. Ask them to double check the number printed "
            "at the bottom of the certificate (or from the QR code) and try again.",
            context=message, forced_lang=forced_lang,
        )
        return reply, []
    reply = llm.summarize_certificate_verification(message, data, forced_lang=forced_lang)
    return reply, []


def _handle_bundle_info(message: str, forced_lang: str | None = None):
    """Bundles are combo/package deals across multiple courses — a separate
    API (`/courses/bundles`, no search param) from regular course listing."""
    try:
        data = rozzgaar_api.list_bundles()
    except ValueError:
        return "Sorry, I couldn't fetch bundle information right now. Please check rozzgaar.in directly, or try again shortly.", []

    if isinstance(data, dict):
        bundles = data.get("bundles") or data.get("items") or []
    elif isinstance(data, list):
        bundles = data
    else:
        bundles = []

    reply = llm.summarize_courses(message, bundles, forced_lang=forced_lang)
    return reply, _item_cards(bundles, kind="bundle")


def _start_flow(state: dict, flow: str):
    order = FIELD_ORDER[flow]
    state["flow"], state["mode"], state["step"] = flow, "ask", order[0]
    state["collected"], state["pending_value"], state["editing_from_review"] = {}, None, False


def _send_to_payment(state: dict, slug: str, forced_lang: str | None, message: str, kind: str = "course", welcome_hint: str = ""):
    """
    Sends the user to the real checkout page for a course or bundle instead
    of calling a "free enroll" API that doesn't exist. Returns (reply,
    quick_replies, payment_url) — enrollment itself only happens once they
    actually pay on that page; "I've completed payment" (ENROLL_CHECK_MARKER)
    is how we find out whether it went through.
    """
    state["pending_payment_slug"] = slug
    state["pending_payment_kind"] = kind
    url = PAYMENT_URL_TEMPLATE.format(kind=kind, slug=slug)
    text = {
        "en": f"{welcome_hint}I've opened the payment page for this {kind} in a new tab. "
              "Please complete the payment there, then come back and tap the button below.",
        "hi": f"{welcome_hint}मैंने इस {'बंडल' if kind == 'bundle' else 'कोर्स'} के लिए पेमेंट पेज एक नए टैब में खोल दिया है। "
              "कृपया वहां पेमेंट पूरा करें, फिर वापस आकर नीचे दिया गया बटन दबाएं।",
    }.get(forced_lang or "en")
    return text, PAYMENT_QUICK_REPLIES, url


def _check_payment(state: dict, forced_lang: str | None):
    """Re-checks the user's real enrollments to see if a pending payment for
    `state['pending_payment_slug']` has actually gone through yet."""
    slug = state.get("pending_payment_slug")
    kind = state.get("pending_payment_kind", "course")
    if not slug:
        text = {
            "en": "I don't have a payment in progress to check right now. Would you like to explore courses?",
            "hi": "अभी जाँचने के लिए कोई पेमेंट प्रगति में नहीं है। क्या आप कोर्स देखना चाहेंगे?",
        }.get(forced_lang or "en")
        return text, LOGGED_IN_QUICK_REPLIES, None

    try:
        data = rozzgaar_api.my_enrollments(state["token"])
        enrollments = data if isinstance(data, list) else (data.get("enrollments", []) if isinstance(data, dict) else [])
    except ValueError:
        enrollments = None

    def _matches(e):
        if not isinstance(e, dict):
            return False
        course = e.get("course") if isinstance(e.get("course"), dict) else e
        return str(course.get("slug") or course.get("id") or "") == str(slug)

    if enrollments is not None and any(_matches(e) for e in enrollments):
        state["pending_payment_slug"] = None
        state["pending_payment_kind"] = None
        text = {
            "en": "✅ Payment confirmed — you're now enrolled! You can start learning anytime from your dashboard.",
            "hi": "✅ पेमेंट कन्फर्म हो गया — आप अब एनरोल हो चुके हैं! आप कभी भी अपने डैशबोर्ड से पढ़ाई शुरू कर सकते हैं।",
        }.get(forced_lang or "en")
        return text, LOGGED_IN_QUICK_REPLIES, None

    text = {
        "en": "⚠️ I don't see the payment confirmed yet — it may still be processing, or it may not have gone through. "
              "You can check again in a moment, or try the payment page once more.",
        "hi": "⚠️ अभी पेमेंट कन्फर्म नहीं दिख रहा — हो सकता है यह अभी प्रोसेस हो रहा हो, या पूरा न हुआ हो। "
              "थोड़ी देर में फिर से जाँच लें, या पेमेंट पेज दोबारा खोलें।",
    }.get(forced_lang or "en")
    url = PAYMENT_URL_TEMPLATE.format(kind=kind, slug=slug)
    return text, PAYMENT_QUICK_REPLIES, url


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    message = req.message.strip()
    if not message:
        return ChatResponse(reply="Please type something and I'll help you out.")

    state = session_store.get_session(req.session_id)
    redirect = None
    course_cards = None
    quick_replies = None

    # The frontend sends `lang` (the choice made at its language gate) on
    # every request. Store it on the session the first time it arrives, and
    # keep it for the rest of the conversation — every reply from here on
    # is forced into this language, no matter what script/language the user
    # actually types in on later turns.
    if req.lang in ("en", "hi"):
        state["forced_lang"] = req.lang
    forced_lang = state.get("forced_lang")
    logged_in = bool(state.get("token"))
    payment_url = None
    awaiting = None

    try:
        # --- Menu buttons (Login / Register / Explore / Enrollments) always
        # win, even if a flow is still active from before a page refresh —
        # e.g. clicking Register, refreshing, then clicking "Explore
        # Courses" should show courses, not silently be swallowed as an
        # answer to whatever field registration was last asking for.
        if message.strip().lower() in MENU_COMMANDS:
            session_store.reset_flow(req.session_id)

        # --- Logout — clears the access token from this session so the
        # chat stops treating this tab as that logged-in user. Checked
        # before anything else, same as the other fixed menu commands.
        if message.strip().lower() == LOGOUT_COMMAND:
            session_store.logout(req.session_id)
            logged_in = False
            reply = llm.phrase_message(
                "Tell the user they've been logged out, and ask what they'd like to do next.",
                context=message, forced_lang=forced_lang,
            )
            quick_replies = GUEST_QUICK_REPLIES

        # --- "I've completed payment" — check it directly, before anything
        # else, since it's a fixed button marker, not free text.
        elif message.strip() == ENROLL_CHECK_MARKER:
            reply, quick_replies, payment_url = _check_payment(state, forced_lang)

        # --- "Enroll" button on a course/bundle card — handled directly,
        # before anything else, since this is a fixed marker never typed by
        # a real user, not something to run through intent classification.
        # Marker format is "__enroll__<kind>:<slug>" (kind is "course" or
        # "bundle"); fall back to "course" if an older-format marker with
        # no ":" ever arrives, so this doesn't hard-fail either way.
        elif not state["flow"] and message.startswith(ENROLL_MARKER):
            raw = message[len(ENROLL_MARKER):]
            kind, sep, slug = raw.partition(":")
            if not sep:
                kind, slug = "course", raw
            if logged_in:
                reply, quick_replies, payment_url = _send_to_payment(state, slug, forced_lang, message, kind=kind)
            else:
                # Remember which course/bundle they wanted, log them in
                # first, then _finalize_login sends them on to payment
                # automatically.
                state["pending_enroll_slug"] = slug
                state["pending_enroll_kind"] = kind
                _start_flow(state, "login")
                reply = llm.phrase_message(
                    "Tell the user they'll need to log in first to enroll — ask for their "
                    "registered email address or mobile number.",
                    context=message, forced_lang=forced_lang,
                )
                awaiting = _awaiting("identifier", "ask")

        # --- We already asked "what's your certificate number?" — this
        # message is the answer to THAT, not a new request, so it's handled
        # directly rather than through intent classification (which would
        # otherwise have no idea a certificate number was expected).
        elif not state["flow"] and state.get("awaiting_certificate_number"):
            state["awaiting_certificate_number"] = False
            cert_number = _extract_certificate_number(message)
            reply, course_cards = _handle_verify_certificate(message, cert_number, forced_lang=forced_lang)
            quick_replies = LOGGED_IN_QUICK_REPLIES if logged_in else GUEST_QUICK_REPLIES

        elif state["flow"]:
            reply, awaiting, redirect = _continue_flow(req.session_id, state, message)
            logged_in = bool(state.get("token"))
            extra = state.pop("_extra", None) or {}
            if extra:
                quick_replies = extra.get("quick_replies")
                payment_url = extra.get("payment_url")
            # A couple of steps are plain yes/no questions — attach tappable
            # buttons so low-literacy users don't have to type "yes"/"no".
            elif awaiting == "cancel_confirm":
                quick_replies = YES_NO_CANCEL
            elif awaiting == "post_register_login":
                quick_replies = YES_NO_LOGIN_NOW
            elif awaiting is None and not state["flow"] and redirect != "dashboard":
                # The flow just ended (cancelled, or finished) with nothing
                # else in progress — show the normal menu again instead of
                # leaving the user with no obvious next step.
                quick_replies = LOGGED_IN_QUICK_REPLIES if logged_in else GUEST_QUICK_REPLIES

        else:
            # A couple of fixed quick-reply messages are matched directly
            # rather than via the LLM classifier, since they're precise
            # button labels, not free text a user typed.
            if message.strip().lower() == "explore rozzgaar":
                # No buttons of any kind on this reply — Login/Register/
                # Explore are already sticky at the top of the widget, so
                # repeating them (or a course/bundle card row) here would
                # just be redundant. The overview reply itself (in words)
                # already points the user at courses, bundles, and
                # everything else on the site; from here they can just
                # type what they want ("all courses", "verify my
                # certificate", "contact details"...) and the classifier
                # below routes it, the same as if they'd typed it unprompted.
                reply, course_cards = _handle_site_overview(message, forced_lang=forced_lang)
                quick_replies = []
                awaiting = None

            elif message.strip().lower() == "show me all courses":
                reply, course_cards = _handle_course_info("", message, forced_lang=forced_lang)
                quick_replies = LOGGED_IN_QUICK_REPLIES if logged_in else GUEST_QUICK_REPLIES
                awaiting = None

            elif message.strip().lower() == "show me all bundles":
                reply, course_cards = _handle_bundle_info(message, forced_lang=forced_lang)
                quick_replies = LOGGED_IN_QUICK_REPLIES if logged_in else GUEST_QUICK_REPLIES
                awaiting = None

            elif message.strip().lower() == "about rozzgaar":
                reply, course_cards = _handle_site_question(
                    "Tell me about Rozzgaar — what it is, who runs it, and what it offers.",
                    forced_lang=forced_lang,
                )
                quick_replies = LOGGED_IN_QUICK_REPLIES if logged_in else GUEST_QUICK_REPLIES
                awaiting = None

            elif message.strip().lower() == "contact rozzgaar":
                reply, course_cards = _handle_site_question(
                    "What are Rozzgaar's contact details — email, address, and office hours?",
                    forced_lang=forced_lang,
                )
                quick_replies = LOGGED_IN_QUICK_REPLIES if logged_in else GUEST_QUICK_REPLIES
                awaiting = None

            elif message.strip().lower() == "verify certificate":
                state["awaiting_certificate_number"] = True
                reply = llm.phrase_message(
                    "Ask the user for their certificate number, which is printed at the "
                    "bottom of their Rozzgaar certificate (or found by scanning its QR code).",
                    context=message, forced_lang=forced_lang,
                )
                awaiting = "certificate_number"
                quick_replies = LOGGED_IN_QUICK_REPLIES if logged_in else GUEST_QUICK_REPLIES

            elif message.strip().lower() == "show my enrollments":
                if not logged_in:
                    _start_flow(state, "login")
                    reply = llm.phrase_message(
                        "Tell the user they'll need to log in first to see their enrollments — "
                        "ask for their registered email address or mobile number.",
                        context=message, forced_lang=forced_lang,
                    )
                    awaiting = _awaiting("identifier", "ask")
                else:
                    try:
                        data = rozzgaar_api.my_enrollments(state["token"])
                        enrollments = data if isinstance(data, list) else data.get("enrollments", [])
                    except ValueError:
                        enrollments = None
                    if enrollments is None:
                        reply = "Sorry, I couldn't fetch your enrollments right now. Please try again shortly."
                    elif not enrollments:
                        reply = llm.phrase_message(
                            "Tell the user they aren't enrolled in any course yet, and ask if "
                            "they'd like to explore courses.",
                            context=message, forced_lang=forced_lang,
                        )
                    else:
                        reply = llm.summarize_courses(message, enrollments, forced_lang=forced_lang)
                    quick_replies = LOGGED_IN_QUICK_REPLIES
                    awaiting = None
            else:
                route = llm.classify_intent(message, forced_lang=forced_lang)
                kind = route.get("type", "unclear")

                if kind in ("greeting", "about_bot"):
                    reply, awaiting = route.get("reply", "Could you say that again?"), None
                    quick_replies = LOGGED_IN_QUICK_REPLIES if logged_in else GUEST_QUICK_REPLIES

                elif kind == "register":
                    _start_flow(state, "register")
                    reply, awaiting = route.get("reply", "Let's get you registered — what's your title (Mr/Mrs/Ms/Dr)?"), _awaiting("salutation", "ask")

                elif kind == "login":
                    _start_flow(state, "login")
                    reply, awaiting = route.get("reply", "Sure — what's your registered email or mobile number?"), _awaiting("identifier", "ask")

                elif kind == "forgot_password":
                    _start_flow(state, "forgot_password")
                    reply, awaiting = route.get("reply", "No problem — what's your registered email or mobile number?"), _awaiting("identifier", "ask")

                elif kind == "course_info":
                    reply, course_cards = _handle_course_info(route.get("search_term", ""), message, forced_lang=forced_lang)
                    awaiting = None

                elif kind == "bundle_info":
                    reply, course_cards = _handle_bundle_info(message, forced_lang=forced_lang)
                    awaiting = None

                elif kind == "verify_certificate":
                    cert_number = _extract_certificate_number(route.get("certificate_number", "") or "")
                    if cert_number:
                        reply, course_cards = _handle_verify_certificate(message, cert_number, forced_lang=forced_lang)
                        awaiting = None
                    else:
                        state["awaiting_certificate_number"] = True
                        reply = llm.phrase_message(
                            "Ask the user for their certificate number, which is printed at "
                            "the bottom of their Rozzgaar certificate (or found by scanning "
                            "its QR code).",
                            context=message, forced_lang=forced_lang,
                        )
                        awaiting = "certificate_number"

                else:
                    # "site_question" (a real question about Rozzgaar that isn't a
                    # course/bundle lookup or account action) and "unclear" (anything
                    # the classifier couldn't place at all) both fall back to the same
                    # handler: try to answer using real content crawled straight off
                    # rozzgaar.in, rather than an immediate "I don't understand" — see
                    # _handle_site_question().
                    reply, course_cards = _handle_site_question(message, forced_lang=forced_lang)
                    awaiting = None
                    quick_replies = LOGGED_IN_QUICK_REPLIES if logged_in else GUEST_QUICK_REPLIES

        # Voice language: if the user picked a language at the gate, use
        # that directly rather than re-detecting from the reply text (which
        # can misfire on short or mixed replies). Falls back to auto-detect
        # only if no choice has been made yet.
        voice_lang = {"en": "en-IN", "hi": "hi-IN"}.get(forced_lang) or lang_utils.detect_voice_lang(reply)

        handoff_ticket = None
        if state.get("token") and (redirect == "dashboard" or payment_url):
            # Same handoff used for "go to dashboard" — also needed before
            # sending the user to ANY real rozzgaar.in page that requires
            # them to be logged in (like course-payment), since a token
            # living only in this backend's session never logs the user's
            # actual browser into rozzgaar.in by itself.
            handoff_ticket = ticket_store.issue({
                "access_token": state["token"],
                "user": state.get("user") or {"name": state.get("name")},
            })

        return ChatResponse(
            reply=reply,
            lang=voice_lang,
            awaiting_field=awaiting,
            form=build_form(state),
            redirect=redirect,
            user_name=state.get("name") if redirect == "dashboard" else None,
            logged_in=bool(state.get("token")),
            quick_replies=quick_replies,
            field_options=_field_options(awaiting, state),
            courses=course_cards,
            payment_url=payment_url,
            handoff_ticket=handoff_ticket,
        )

    except RuntimeError:
        # every model (Groq + Hugging Face + local Ollama fallback) was unavailable
        return ChatResponse(reply="I'm getting too many requests right now — please try again in a minute.")