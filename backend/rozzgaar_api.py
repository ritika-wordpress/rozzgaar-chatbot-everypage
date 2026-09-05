"""
rozzgaar_api.py
----------------
Thin wrapper around the REAL Rozzgaar API (from your Postman collection).
Every function here just calls rozzgaar.in/apis and returns the parsed
JSON `data`, or raises ValueError with a human-readable message on failure.

No business logic lives here — main.py and llm.py decide WHEN to call
these; this file only knows HOW to call them.
"""

import os
import requests

BASE_URL = os.getenv("ROZZGAAR_BASE_URL", "https://rozzgaar.in/apis").rstrip("/")
OPEN_KEY = os.getenv("ROZZGAAR_OPEN_KEY", "")
TIMEOUT = 15


def _request(method, path, token=None, json_body=None, params=None):
    """
    Every Rozzgaar endpoint needs a Bearer token: either the shared public
    `open_key` (for register/login/course-browsing) or a real user
    `access_token` (for anything under /user, /reviews, /quiz, /payment).
    """
    bearer = token or OPEN_KEY
    headers = {"Authorization": f"Bearer {bearer}"}
    if json_body is not None:
        headers["Content-Type"] = "application/json"

    try:
        resp = requests.request(
            method, f"{BASE_URL}{path}",
            headers=headers, json=json_body, params=params, timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        raise ValueError(f"Could not reach Rozzgaar servers: {e}")

    try:
        body = resp.json()
    except ValueError:
        raise ValueError("Rozzgaar server returned an unexpected response.")

    if resp.status_code >= 400 or body.get("status") == "error":
        # Surface the API's own message when it has one — these are
        # written to be shown to end users (e.g. "Invalid email or password").
        msg = body.get("message") or f"Request failed (status {resp.status_code})."
        raise ValueError(msg)

    return body.get("data", {})


# --- Auth ---------------------------------------------------------------

def register_start(salutation, name, mobile, email, password, state, district, referral_code=""):
    return _request("POST", "/auth/register", json_body={
        "salutation": salutation, "name": name, "mobile": mobile, "email": email,
        "password": password, "state": state, "district": district,
        "referral_code": referral_code,
    })


def verify_otp(verification_id, otp):
    return _request("POST", "/auth/verify-otp", json_body={
        "verification_id": verification_id, "otp": otp,
    })


def resend_otp(verification_id):
    return _request("POST", "/auth/resend-otp", json_body={"verification_id": verification_id})


def login(identifier_field, identifier_value, password):
    """identifier_field is either 'email' or 'mobile'."""
    return _request("POST", "/auth/login", json_body={
        identifier_field: identifier_value, "password": password,
    })


def forgot_password(identifier):
    return _request("POST", "/auth/forgot-password", json_body={"identifier": identifier})


# --- Public course/site info ---------------------------------------------

def list_states():
    return _request("GET", "/misc/states")


def list_districts(state):
    return _request("GET", "/misc/districts", params={"state": state})


def list_courses(search=None, page=1, limit=12):
    params = {"page": page, "limit": limit}
    if search:
        params["search"] = search
    return _request("GET", "/courses", params=params)


def course_detail(slug):
    return _request("GET", f"/courses/{slug}")


def list_bundles():
    return _request("GET", "/courses/bundles")


def contact_form(name, mobile, email, subject, message):
    return _request("POST", "/misc/contact", json_body={
        "name": name, "mobile": mobile, "email": email,
        "subject": subject, "message": message,
    })


# --- Logged-in user info (needs a real access token) ---------------------

def my_profile(token):
    return _request("GET", "/user/profile", token=token)


def my_enrollments(token):
    return _request("GET", "/user/enrollments", token=token)


def enroll_in_course(token, slug):
    """
    UNUSED — kept for reference only.

    There is no "free enroll" endpoint: enrollment only actually happens
    once the user pays on the real checkout page
    (rozzgaar.in/applicant/course-payment?type=course&id=<slug>). main.py
    sends users there directly and confirms enrollment afterwards via
    my_enrollments() instead of calling this function.
    """
    return _request("POST", f"/courses/{slug}/enroll", token=token)
