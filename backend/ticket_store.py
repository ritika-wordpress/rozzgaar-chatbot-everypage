"""
ticket_store.py
----------------
Short-lived, single-use "handoff tickets" used to move a logged-in user's
session from the chatbot's origin (chatbot.rozzgaar.in) to the main site's
origin (rozzgaar.in) via a full page navigation.

Why this exists: a browser will never let JS on one origin write to
localStorage on another origin. So instead of handing the access_token to
the browser directly, /chat hands it a short random *ticket*. The frontend
sends the browser to rozzgaar.in/chatbot-login.php?ticket=..., and that PHP
page calls back into this backend server-to-server (carrying a shared
secret) to redeem the ticket for the real token — see
POST /internal/redeem-ticket in main.py.

Tickets are:
  - random and unguessable (secrets.token_urlsafe)
  - single-use — redeeming one deletes it immediately
  - short-lived — expire after TICKET_TTL_SECONDS even if never redeemed

Same caveat as session_store.py: plain in-memory dict, fine for one
process, resets on restart, won't work across multiple workers/processes
without moving to something shared like Redis.
"""

import secrets
import threading
import time

TICKET_TTL_SECONDS = 120  # plenty of time for a redirect + one HTTP round trip

_lock = threading.Lock()
_tickets: dict[str, tuple[float, dict]] = {}  # ticket -> (expires_at, payload)


def issue(payload: dict) -> str:
    """Create a new ticket wrapping `payload` (e.g. {"access_token": ..., "user": {...}})."""
    ticket = secrets.token_urlsafe(32)
    with _lock:
        _prune_expired()
        _tickets[ticket] = (time.time() + TICKET_TTL_SECONDS, payload)
    return ticket


def redeem(ticket: str) -> dict | None:
    """
    Return the payload for `ticket` and delete it (single-use), or None if
    the ticket is unknown, already used, or expired.
    """
    with _lock:
        entry = _tickets.pop(ticket, None)
    if entry is None:
        return None
    expires_at, payload = entry
    if time.time() > expires_at:
        return None
    return payload


def _prune_expired():
    """Called while already holding _lock. Keeps the dict from growing forever."""
    now = time.time()
    expired = [t for t, (expires_at, _) in _tickets.items() if now > expires_at]
    for t in expired:
        del _tickets[t]