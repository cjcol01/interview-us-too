import contextvars
import json
import logging
import logging.handlers
import os
import sys
import time
from datetime import datetime
from typing import Optional
from urllib.parse import unquote, urlparse

logger = logging.getLogger("app")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _stream_handler = logging.StreamHandler(sys.stdout)
    _stream_handler.setFormatter(_formatter)
    logger.addHandler(_stream_handler)

    # Also persist to a rotating file so tracebacks survive past terminal scrollback and
    # process restarts — admin_health's "Recent errors" section reads this back. Lives in
    # DATA_DIR (the same configurable, outside-the-repo location as the DB — see DB_DATA_DIR
    # in config.py) rather than the repo itself.
    try:
        from database import DATA_DIR
        _log_filename = "test_app.log" if os.getenv("TESTING") == "1" else "app.log"
        _file_handler = logging.handlers.RotatingFileHandler(
            os.path.join(DATA_DIR, _log_filename), maxBytes=5 * 1024 * 1024, backupCount=3,
        )
        _file_handler.setFormatter(_formatter)
        logger.addHandler(_file_handler)
    except Exception:
        pass  # file logging is a nice-to-have — stdout logging above still works either way
    logger.propagate = False

_ph = None

# posthog-js's cookie (ph_<project_key>_posthog) parsed for the current request — see
# bind_browser_context(). Lets server-side events carry the browser's $session_id (so they
# show up inside the matching session replay) and lets pre-login events be attributed to the
# browser's anonymous distinct id instead of being dropped. Middleware-bound, so it is per
# request and reset on the way out; contextvars propagate into run_in_threadpool.
_browser_ctx: contextvars.ContextVar = contextvars.ContextVar("ph_browser_ctx", default=None)
# posthog-js rotates the session id after 30 minutes of inactivity; a stale one would pin
# server events to a replay that no longer exists.
_SESSION_STALE_MS = 30 * 60 * 1000
_ATTRIBUTION_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid")
# Name of posthog-js's persistence cookie for this project (ph_<project_key>_posthog), or
# None when analytics are off. Module-level so tests can point it at a fixture cookie.
_COOKIE_NAME: Optional[str] = None


def _init():
    global _ph, _COOKIE_NAME
    # TESTING is checked before the key so a stray key in the environment can never make the
    # suite (or any TESTING=1 process) write into the production project.
    if os.getenv("TESTING") == "1":
        logger.info("PostHog analytics disabled (TESTING=1)")
        return
    key = os.getenv("POSTHOG_API_KEY")
    if not key:
        logger.info("PostHog analytics disabled (no POSTHOG_API_KEY)")
        return
    _COOKIE_NAME = f"ph_{key}_posthog"
    try:
        from posthog import Posthog
        host = os.getenv("POSTHOG_HOST", "https://eu.i.posthog.com")
        _ph = Posthog(project_api_key=key, host=host)
        logger.info("PostHog analytics enabled (host=%s)", host)
    except ImportError:
        logger.warning("posthog package not installed — analytics disabled")


_init()


# ---------------------------------------------------------------------------
# Browser context (posthog-js cookie → per-request contextvar)
# ---------------------------------------------------------------------------

def cookie_name() -> Optional[str]:
    return _COOKIE_NAME


def bind_browser_context(cookie_value: Optional[str]):
    """Parses posthog-js's persistence cookie into the request context and returns the
    ContextVar token for reset(). The cookie is URL-encoded JSON; the fields we use are
    `distinct_id` and `$sesid` = [lastActivityMs, sessionId, sessionStartMs]. Anything
    malformed just yields no context — analytics must never break a request."""
    ctx = None
    if cookie_value:
        try:
            data = json.loads(unquote(cookie_value))
            if isinstance(data, dict):
                ctx = {}
                did = data.get("distinct_id")
                if isinstance(did, str) and did:
                    ctx["distinct_id"] = did
                sesid = data.get("$sesid") or []
                if isinstance(sesid, list) and len(sesid) >= 2 and sesid[1]:
                    now_ms = int(time.time() * 1000)
                    if now_ms - int(sesid[0]) < _SESSION_STALE_MS:
                        ctx["$session_id"] = str(sesid[1])
                if not ctx:
                    ctx = None
        except Exception:
            ctx = None
    return _browser_ctx.set(ctx)


def reset_browser_context(token) -> None:
    try:
        _browser_ctx.reset(token)
    except Exception:
        pass


def browser_distinct_id() -> Optional[str]:
    """The browser's current posthog-js distinct id (anonymous UUID before identify, the
    numeric user id after), or None outside a request / without the cookie."""
    ctx = _browser_ctx.get()
    return ctx.get("distinct_id") if ctx else None


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

# All wrappers target the posthog 7.x SDK, which took distinct_id/properties out of the
# positional signature and dropped Posthog.identify() entirely (set() is its replacement for
# writing person properties). Passing them positionally — as these did before — raised on
# *every* call, and the bare `except Exception: pass` below swallowed it, so all server-side
# analytics silently went nowhere while looking healthy. requirements.txt pins the major
# version so that can't happen again on a fresh install.
def track(user_id: Optional[int], event: str, **props) -> None:
    """Server-side event. With a user id the event lands on the numeric person (the same
    distinct id the browser identifies with — see base.html). With user_id=None it falls back
    to the browser's anonymous distinct id from the posthog-js cookie, flagged so it doesn't
    create a person profile (mirrors person_profiles: "identified_only" client-side); the
    event still merges onto the person if that browser later identifies. No user and no
    cookie → dropped."""
    if _ph is None:
        return
    ctx = _browser_ctx.get() or {}
    if ctx.get("$session_id"):
        props["$session_id"] = ctx["$session_id"]
    if user_id is None:
        distinct_id = ctx.get("distinct_id")
        if not distinct_id:
            return
        props["$process_person_profile"] = False
    else:
        distinct_id = str(user_id)
    try:
        _ph.capture(event, distinct_id=distinct_id, properties=props or None)
    except Exception:
        pass


def is_internal_user(user) -> bool:
    admin = os.getenv("ADMIN_USERNAME")
    return bool(admin and getattr(user, "username", None) == admin)


def identify_user(user, set_once: Optional[dict] = None) -> None:
    """Writes the full person profile for a user. Call at signup AND after every change to
    account_level / sessions_remaining / verification / extension state, so cohorts like
    "paying users" or "connected the extension" stay current — a one-time identify at signup
    leaves every person frozen at `trial`."""
    if _ph is None or user is None:
        return
    try:
        created = getattr(user, "created_at", None)
        props = {
            "email": user.email,
            "name": user.full_name,
            "username": user.username,
            "account_level": user.account_level.value,
            "sessions_remaining": user.sessions_remaining,
            "stripe_customer": bool(user.stripe_customer_id),
            "has_subscription": bool(user.stripe_sub_id),
            "referred": user.referred_by_id is not None,
            "email_verified": bool(user.email_verified),
            "ext_connected": getattr(user, "ext_first_seen_at", None) is not None,
            "is_internal": is_internal_user(user),
            "created_at": created.isoformat() if created else None,
        }
        _ph.set(distinct_id=str(user.id), properties=props)
        if set_once:
            _ph.set_once(distinct_id=str(user.id), properties=set_once)
    except Exception:
        pass


def identify(user_id: int, email: str, name: str, account_level: str) -> None:
    """Legacy minimal identify — prefer identify_user(user). Kept so nothing that still
    imports it breaks."""
    if _ph is None:
        return
    try:
        _ph.set(distinct_id=str(user_id),
                properties={"email": email, "name": name, "account_level": account_level})
    except Exception:
        pass


def set_once(user_id: int, **props) -> None:
    if _ph is None or not props:
        return
    try:
        _ph.set_once(distinct_id=str(user_id), properties=props)
    except Exception:
        pass


def alias(previous_id: Optional[str], user_id: int) -> None:
    """Merges an anonymous browser distinct id into the numeric user person. Used for the
    mobile → desktop handoff (/api/install-link → /claim), where the phone that saw the ad
    and the laptop that signs up are different browsers, so posthog-js's own identify() on
    the laptop can never reach the phone's history."""
    if _ph is None or not previous_id:
        return
    try:
        _ph.alias(previous_id=previous_id, distinct_id=str(user_id))
    except Exception:
        pass


def attribution_set_once(attr: Optional[dict], signup_method: str) -> dict:
    """Builds the $set_once payload for a signup from the server-side ia_attr attribution
    dict (utm_*, gclid, fbclid, r=referer, t=first-touch ts — see _attribution_from_query in
    server.py). Uses PostHog's own $initial_* property names so the stock first-touch
    breakdowns work for signups where posthog-js never saw the ad click: the mobile → desktop
    handoff, or a landing visit where the consent banner blocked the script. $set_once never
    overwrites a value posthog-js already recorded."""
    once = {"signup_method": signup_method, "signed_up_at": datetime.utcnow().isoformat()}
    attr = attr or {}
    for k in _ATTRIBUTION_KEYS:
        v = attr.get(k)
        if v:
            once[f"$initial_{k}"] = v
    referer = attr.get("r")
    if referer:
        once["$initial_referrer"] = referer
        try:
            once["$initial_referring_domain"] = urlparse(referer).netloc or "$direct"
        except Exception:
            pass
    return once
