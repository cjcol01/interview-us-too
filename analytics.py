import logging
import logging.handlers
import os
import sys

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
