"""
session_store.py
----------------
Tracks, per conversation (per browser tab), where a user is in a
register/login/forgot-password flow, and their access token once logged in.

Each flow now walks through fields one at a time using three sub-modes:
  "ask"     - waiting for the user's raw answer to `step`.
  "confirm" - the raw answer was valid; waiting for yes/no on whether
              `pending_value` is correct before it's committed.
  "review"  - every field has been asked + confirmed; showing the full
              summary and waiting for a final go-ahead (or a request to
              change a specific field) before actually calling the API.

While any of the above is active, the user can ask to stop at any time.
Doing so does NOT cancel immediately — `pending_cancel` is set to True and
the user is asked to confirm; a "no" clears it and re-asks the exact same
field/step they were on (mode/step/collected/pending_value are left
untouched while pending_cancel is set), a "yes" actually resets the flow.

This is a plain in-memory dict — simplest thing that works for one
FastAPI process. It resets if the server restarts, and won't work
correctly if you run multiple server processes/workers behind a load
balancer (each would have its own separate memory). If you outgrow that,
swap this for Redis — the get/set/clear functions below are the only
places that would need to change.
"""

import threading

_lock = threading.Lock()
_sessions = {}


def _blank_flow_fields() -> dict:
    return {
        "flow": None,                  # None | "register" | "login" | "forgot_password"
        "mode": None,                  # None | "ask" | "confirm" | "review"
        "step": None,                  # current field name being collected/confirmed
        "collected": {},               # answers already confirmed in the current flow
        "pending_value": None,         # a just-validated value awaiting yes/no confirmation
        "editing_from_review": False,  # True if we jumped back to fix one field from "review"
        "pending_cancel": False,       # True while waiting on yes/no to a stop/cancel request
    }


def get_session(session_id: str) -> dict:
    with _lock:
        if session_id not in _sessions:
            _sessions[session_id] = {
                **_blank_flow_fields(),
                "token": None,  # access_token once logged in
                "user": None,   # full user dict from the login API response
                "name": None,   # logged-in user's name, for a friendly greeting
                "pending_enroll_slug": None,  # course/bundle slug they clicked
                                               # "Enroll" on before logging in —
                                               # sent to payment automatically
                                               # right after login.
                "pending_enroll_kind": None,   # "course" | "bundle" — which
                                                # checkout URL type pending_enroll_slug needs.
                "pending_payment_slug": None,  # course/bundle slug the user was just
                                                # sent to the payment page for —
                                                # cleared once payment is
                                                # confirmed (or they leave it).
                "pending_payment_kind": None,  # "course" | "bundle" for pending_payment_slug.
            }
        return _sessions[session_id]


def reset_flow(session_id: str):
    with _lock:
        if session_id in _sessions:
            _sessions[session_id].update(_blank_flow_fields())


def logout(session_id: str):
    """
    Forget this session's login entirely — clears the access token, the
    logged-in user's data, and any in-progress flow. Without this, a
    session that has ever logged in stays logged in forever (the dict
    never expires on its own), so anyone reusing that browser tab keeps
    landing on the previous user's dashboard with no way back to a
    guest state from inside the chat.
    """
    with _lock:
        if session_id in _sessions:
            _sessions[session_id].update({
                **_blank_flow_fields(),
                "token": None,
                "user": None,
                "name": None,
                "pending_enroll_slug": None,
                "pending_enroll_kind": None,
                "pending_payment_slug": None,
                "pending_payment_kind": None,
            })