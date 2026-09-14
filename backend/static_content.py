"""
static_content.py
------------------
Two jobs, both grounded in real content crawled straight off rozzgaar.in's
own STATIC pages (home, about, contact, privacy policy, terms, refund
policy) rather than any API:

1. Fallback for "Explore" when the real course/bundle API is unreachable —
   see main.py._handle_site_overview(). Rather than a flat "couldn't fetch"
   error, this crawls the site's static pages and hands the raw visible
   text to the LLM to summarize.
2. General Q&A for anything asked about Rozzgaar that isn't a specific
   course/bundle lookup or an account action — company info, certifying
   bodies, contact details, policies, etc. — see
   main.py._handle_site_question(). The LLM answers ONLY from this crawled
   text, so a wrong/missing answer just means "not on the site" rather than
   a hallucinated fact.

This never replaces the API: whenever rozzgaar_api.py's course/bundle calls
succeed, main.py uses that real, live data as before.

Crawled text is cached in memory for CACHE_TTL_SECONDS so a burst of
questions (or a stretch of API outages) doesn't mean re-crawling rozzgaar.in
on every single message. If a fresh crawl fails but a previous (stale) copy
exists, the stale copy is served instead of failing outright — old real
info still beats none.
"""

import os
import time

import requests
from bs4 import BeautifulSoup

# Pages crawled for two purposes: (1) an Explore fallback when the live
# course/bundle API is down, and (2) general site_question answers (see
# main.py._handle_site_question) for anything asked about Rozzgaar that
# isn't a specific course/bundle lookup or account action — company info,
# certifying bodies, contact details, and site policies.
STATIC_PAGES = {
    "home": "https://rozzgaar.in/",
    "about": "https://rozzgaar.in/about",
    "contact": "https://rozzgaar.in/contact",
    "privacy_policy": "https://rozzgaar.in/privacy-policy",
    "terms": "https://rozzgaar.in/terms",
    "refund_policy": "https://rozzgaar.in/refund-policy",
}

TIMEOUT = 10
CACHE_TTL_SECONDS = int(os.getenv("STATIC_CONTENT_CACHE_TTL", str(6 * 60 * 60)))  # 6 hours
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RozzgaarAssistant/1.0; +https://rozzgaar.in)"}

# Module-level cache — same lifetime as the process, same simplicity as
# session_store.py's in-memory approach (see its own note about swapping to
# Redis if this ever runs with more than one worker).
_cache = {"text": None, "fetched_at": 0.0}


def _extract_visible_text(html: str) -> str:
    """Strip scripts/styles and return deduplicated visible text, line by
    line. Deduplication matters here because the same nav/footer/WhatsApp
    widget markup repeats on every page crawled — without it, 80% of the
    text handed to the LLM would just be repeated boilerplate."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    lines = [ln.strip() for ln in soup.get_text(separator="\n").splitlines()]
    lines = [ln for ln in lines if ln]

    seen = set()
    deduped = []
    for ln in lines:
        key = ln.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ln)
    return "\n".join(deduped)


def _crawl() -> str:
    chunks = []
    for label, url in STATIC_PAGES.items():
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException:
            continue  # one page failing shouldn't sink the whole crawl
        chunks.append(f"--- {label} page ({url}) ---\n{_extract_visible_text(resp.text)}")

    if not chunks:
        raise ValueError("Could not reach rozzgaar.in to read its static page content.")
    return "\n\n".join(chunks)


def get_static_site_text(force_refresh: bool = False) -> str:
    """
    Returns crawled, deduplicated visible text from rozzgaar.in's home/about/
    contact pages, cached for CACHE_TTL_SECONDS.

    Raises ValueError only if there is truly nothing to give: no usable
    cache from an earlier successful crawl, AND the site is unreachable
    right now.
    """
    now = time.time()
    is_fresh = _cache["text"] is not None and (now - _cache["fetched_at"]) < CACHE_TTL_SECONDS
    if is_fresh and not force_refresh:
        return _cache["text"]

    try:
        text = _crawl()
    except ValueError:
        if _cache["text"] is not None:
            return _cache["text"]  # serve stale over nothing
        raise

    _cache["text"] = text
    _cache["fetched_at"] = now
    return text