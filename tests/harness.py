PASS  = "\033[92m PASS\033[0m"
FAIL  = "\033[91m FAIL\033[0m"
SKIP  = "\033[93m SKIP\033[0m"
BOLD  = "\033[1m"
RESET = "\033[0m"

results = []
_client = None


def set_client(client):
    """Register the shared TestClient so test() can reset its cookie jar between tests.

    The suite runs every test against one TestClient for the whole process, and tests pass
    per-call `cookies={...}` — but httpx merges those into the client's persistent jar rather
    than scoping them to that call, so a "session"/"ref" cookie set by one test leaks into
    later tests that don't expect it (e.g. wrong-user auth, or an anonymous-page test getting
    an authenticated response). Clearing the jar before each test keeps tests isolated.
    """
    global _client
    _client = client


def test(name, fn):
    if _client is not None:
        _client.cookies.clear()
    try:
        result = fn()
        if result is False:
            print(f"{FAIL} {name}")
            results.append((name, False, None))
        else:
            print(f"{PASS} {name}")
            results.append((name, True, None))
    except Exception as e:
        print(f"{FAIL} {name}")
        print(f"       {type(e).__name__}: {e}")
        results.append((name, False, e))


def skip(name, reason=""):
    msg = f" ({reason})" if reason else ""
    print(f"{SKIP} {name}{msg}")
    results.append((name, None, None))
