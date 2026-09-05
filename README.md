# Rozzgaar Assistant

A chatbot built specifically for rozzgaar.in — handles greetings/FAQ,
answers course questions using your real course-listing API, and walks
users through actual registration (with OTP) and login, using your real
`/auth/*` endpoints from the Postman collection. Works in text or voice,
in Hindi, English, or mixed — automatically, with no language switch
anywhere in the UI.

**Stack:** FastAPI (Python) backend, plain HTML/CSS/JS frontend, three
free LLM tiers (Groq → Hugging Face → local Ollama) for language
understanding. No paid services.

## How it works

1. **No active flow:** the LLM classifies what the user wants — greeting,
   "what are you", register, login, forgot password, or a course
   question — understanding typos and any language automatically.
2. **Course questions** call your real `GET /courses` endpoint (with a
   search keyword the LLM extracts) and the results are summarized in
   plain language, in the user's own language.
3. **Register** walks through salutation → name → mobile → email →
   password → state → district, one question at a time, validating and
   cleaning each answer (e.g. spoken-style phone numbers, typos) before
   moving on. Once all fields are collected it shows a summary and asks
   for one final go-ahead, then calls your real `POST /auth/register`.
   (Note: this build does **not** do an OTP step — `verify_otp`/
   `resend_otp` exist in `rozzgaar_api.py` but aren't wired into the flow.
   If your `/auth/register` actually requires OTP verification server-side,
   that step still needs to be added.)
4. **Login** asks for email/mobile + password, then calls your real
   `POST /auth/login`. The returned `access_token` is kept server-side in
   the session (never sent to the browser) for the rest of that
   conversation, in case you want to extend this later (e.g. "what
   courses am I enrolled in").
5. **Language is 100% automatic** end to end — see the section below.
6. At any point during register/login, the user can type "cancel" (or
   "ruko"/"rehne do") to back out.

## 1. Get a free Groq API key (already set up for you)

Your `.env` already has a working Groq key and the Rozzgaar API's `open_key`
filled in (found in your own site's page source, where it's already used
client-side — so it's meant to be embedded like this, not a private
secret). If you ever rotate it, update `ROZZGAAR_OPEN_KEY` in `.env`.

## 2. Backend setup

```bash
cd backend
python -m venv venv
source venv/bin/activate      # on Windows: venv\Scripts\activate
pip install -r requirements.txt

uvicorn main:app --reload --port 8000
```

Visit http://localhost:8000/health — you should see `{"status": "ok"}`.

## 3. Frontend setup

```bash
cd frontend
python -m http.server 5500
```

Visit http://localhost:5500. If your backend runs somewhere other than
`http://localhost:8000`, update `API_URL` at the top of `frontend/script.js`.

## Rate limits — spread across 3 free tiers

Same approach as before: Groq first (3 model fallbacks), then Hugging
Face (separate free quota — add `HF_API_TOKEN` in `.env` to enable it),
then a local Ollama model if installed (genuinely no rate limit, since it
runs on your own machine). See the comments at the top of `llm.py` for
setup details on each.

## Multi-language: fully automatic

- The LLM detects whatever language/script the user types in and replies
  in that same language — nothing is configured anywhere.
- Every reply is also spoken aloud automatically (`lang_utils.py` detects
  the reply's language offline, no API call, and the frontend picks a
  matching voice) — tap 🔊 to mute.
- Voice INPUT (the mic button) has to be given a language up front by the
  browser (there's no free "auto-detect while listening"), so it silently
  adopts whatever language was last detected in the conversation — no
  dropdown, no manual choice.

## Security notes

- **Password handling:** while the bot is asking for a password (register
  or login), the input box switches to a masked password field, and the
  user's own message is displayed as dots in the chat — the actual
  password is still sent to the backend to complete the request, but
  never shown on screen or spoken aloud.
- **Access tokens** from login live server-side in `session_store.py`
  for the rest of the conversation. The one exception: right when a
  login succeeds (`redirect: "dashboard"`), the token is also sent to
  the browser once, because the real rozzgaar.in site itself checks
  `localStorage["rzg_token"]` client-side to decide whether a browser
  is logged in — without handing it over at that moment, "Go to my
  dashboard" would land on an unauthenticated `/applicant/` page. It's
  never sent back down on any other response.
- **Session storage is in-memory** — simplest thing that works for one
  server process. It resets on restart and won't work correctly across
  multiple server workers/instances. If you deploy with more than one
  worker, swap `session_store.py` for Redis (the `get_session`/
  `reset_flow` functions are the only things that would need to change).
- The Rozzgaar API's own error messages (e.g. "Invalid email or
  password", "Email already registered") are shown directly to the user —
  they're already written to be user-facing, per your API's design.

## What's NOT built yet (intentionally, to keep this focused)

A few natural next steps if you want them later:
- OTP verification during registration (see the note above)
- The live form-panel UI the backend already prepares data for (`form` on
  every `/chat` response) — no frontend code renders it yet, so it's
  currently unused
- "My certificates"
- Passing unanswered questions to the real Contact Form API
- Resend-OTP handling (API endpoint already wrapped in
  `rozzgaar_api.resend_otp`, not wired in — depends on OTP being added first)

Just say the word and I'll add any of these.

## Update: real voice output, a visible form, and a handoff to the page-reader assistant

Three things changed on top of everything above:

1. **Edge TTS instead of the browser's built-in voice.** `backend/tts.py`
   wraps the free `edge-tts` package (same one the page-reader project
   uses) and exposes it as `POST /tts/speak` (`{"text": "...", "lang":
   "hi-IN"}` → MP3 bytes). `frontend/script.js` now calls this endpoint to
   speak every bot reply, and only falls back to the browser's
   `speechSynthesis` if that call fails (e.g. offline). Run `pip install
   -r requirements.txt` again to pick up `edge-tts`.

2. **Every `/chat` response includes a `form` object** (`{flow, mode,
   fields: [{name, label, value, status}]}`) describing exactly where the
   user is in registration/login — which fields are done, which one is
   active. This is ready for a frontend form-panel UI, but no such panel
   is wired up in `script.js` yet — the conversation itself (chat bubbles)
   is currently the only UI for this.

3. **A successful login offers a hand-off to the page-reading assistant,
   without forcing it.** Once login succeeds, the response includes
   `"redirect": "dashboard"` (plus `user_name`), and the frontend shows a
   tappable "Go to my dashboard →" link rather than auto-navigating away —
   this widget can live on any page of the site, so a login shouldn't yank
   the user off whatever they were reading. That link points at
   `frontend/dashboard.html`, which embeds the *other* chatbot from
   `rozgaar-page-reader` (pointed at `http://127.0.0.1:8001` by default —
   change `API_BASE` in `dashboard.html` if that backend runs elsewhere).
   That's the assistant that can read/summarize whatever page the user is
   on and answer questions about it, by text or voice — this is a stand-in
   dashboard page just so it has real content to read; swap it for the
   real `/applicant/` dashboard whenever this ships.

To try it end-to-end you need **both** backends running at once:
```
# terminal 1 — this project
cd backend && uvicorn main:app --reload --port 8000

# terminal 2 — the page-reader project
cd rozgaar-page-reader/.../rozzgaar-chatbot && uvicorn app.main:app --reload --port 8001
```
then open `frontend/index.html`, register or log in, and you'll land on
`dashboard.html` talking to the second assistant.

## Update: enroll → real checkout, password-prompt safety, sticky menu buttons

Four bugs were fixed on top of everything above:

1. **Enrolling in a course now actually works.** There never was a "free
   enroll" API — enrollment only happens after payment. Clicking "Enroll"
   on a course card now sends the user straight to the real checkout page
   (`rozzgaar.in/applicant/course-payment?type=course&id=<slug>`), opened
   in a new tab (with a tappable fallback link in the chat too, in case
   the browser blocks the popup). A "✅ I've completed payment" button then
   re-checks the user's real `/user/enrollments` and reports success, or
   that it's not confirmed yet — with a small animated status badge either
   way, and an automatic re-check if the user just tabs back into the
   window after paying. If the user wasn't logged in when they clicked
   Enroll, they're taken through login first, then sent to checkout
   automatically, same as before.

2. **Password prompts are now fixed, canned bilingual text — never
   LLM-phrased.** Asking a model to generate "ask the user for their
   password" could occasionally get misread by the model's own safety
   filter as a phishing-style request and refused outright (this is what
   was happening, especially in Hindi). Every point where the bot asks for
   a password (new password during registration, existing password during
   login, including the "you already have an account, just log in"
   shortcut) now uses fixed text from `CANNED_MESSAGES` in `main.py`
   instead — sidesteps the refusal risk entirely, and is more predictable
   for low-literacy users besides.

3. **Menu buttons (Login / Register / Explore / Enrollments) always win,**
   even over a stale in-progress flow. Previously, if a user clicked
   Register, refreshed the page (the session persists across a refresh by
   design), and then clicked "Explore Courses", that click was silently
   swallowed as an answer to whatever registration field was last being
   asked. Now these four fixed menu commands reset any active flow first.

4. **Yes/No steps got tappable buttons, and the menu reappears after a
   flow ends.** The "are you sure you want to cancel?" and "would you like
   to log in now?" steps now show quick-reply buttons instead of expecting
   the user to type "yes"/"no" by hand, and cancelling (or otherwise
   finishing) a flow brings the Login/Register/Explore menu back instead
   of leaving the user with no obvious next step.

Also, the user and bot chat bubbles are now visually identical (both
white) other than which side they sit on — previously the user's bubble
was a different color, which read as inconsistent.

`frontend/dashboard.html` was intentionally left untouched in this pass.