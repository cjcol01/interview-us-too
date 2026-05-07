PASS  = "\033[92m PASS\033[0m"
FAIL  = "\033[91m FAIL\033[0m"
SKIP  = "\033[93m SKIP\033[0m"
BOLD  = "\033[1m"
RESET = "\033[0m"

results = []


def test(name, fn):
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
