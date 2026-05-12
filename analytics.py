import logging
import os
import sys

logger = logging.getLogger("app")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(_handler)
    logger.propagate = False

_ph = None


def _init():
    global _ph
    key = os.getenv("POSTHOG_API_KEY")
    if not key:
        return
    try:
        from posthog import Posthog
        host = os.getenv("POSTHOG_HOST", "https://us.i.posthog.com")
        _ph = Posthog(project_api_key=key, host=host)
        logger.info("PostHog analytics enabled (host=%s)", host)
    except ImportError:
        logger.warning("posthog package not installed — analytics disabled")


_init()


def identify(user_id: int, email: str, name: str, account_level: str) -> None:
    if _ph is None:
        return
    try:
        _ph.identify(str(user_id), {"email": email, "name": name, "account_level": account_level})
    except Exception:
        pass


def track(user_id: int | None, event: str, **props) -> None:
    if _ph is None or user_id is None:
        return
    try:
        _ph.capture(str(user_id), event, props or None)
    except Exception:
        pass
