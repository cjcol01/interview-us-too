# Load testing (local dev server)

Stress-tests the app running on your machine to find its breaking point — the
concurrency level where latency spikes and errors start appearing.

**Never run this against the live/production site.** It's designed for `python server.py`
on localhost only.

All commands below are run from the **repo root** and use the project's `.venv`
explicitly (`.venv/bin/python`, `.venv/bin/locust`). Do this even if you normally
have a venv active or `locust` on your `PATH` — this machine also has an old
system-wide `locust` (v1.4.3, via `/usr/bin/locust`) that shadows the one this
tool was built and tested against (v2.45.0). The old version has a different CLI
and will fail confusingly (e.g. missing directories it should auto-create).

## How it stays free

`/api/capture` (and `/api/text-capture`) check the caller's subscription status
*before* calling Anthropic — free-tier accounts get an immediate `403` (see
`_gate_basic_access` in `server.py`). Every account this tool seeds is `free`-tier,
and both `seed_users.py` and `locustfile.py` refuse to run if a non-free account
sneaks into `accounts.json`. So the "mock capture" task exercises the full
auth → gate → rate-limit path without ever reaching the paid Anthropic/OpenAI APIs.

`loadtest/accounts.json` and `loadtest/results/` are gitignored — they contain
live api_tokens and are machine-specific; don't commit them.

## Setup

```bash
.venv/bin/pip install -r loadtest/requirements.txt
```

Make sure Redis is running and start the dev server normally (**not** `TESTING=1`,
so it uses the real `interview.db` / Redis that seeded users land in):

```bash
.venv/bin/python server.py
```

Seed some free-tier test users (defaults to 50, shared password `loadtest-pw-123`):

```bash
.venv/bin/python loadtest/seed_users.py --count 50
```

This writes `loadtest/accounts.json`. Re-running with the same `--count` is safe —
existing `loadtest_N` users are reused/reset to `free`, not duplicated. Each account
also gets a ready-to-use `session_token` (a pre-minted JWT), used below to simulate
already-logged-in returning users instead of a fresh `/auth/login` every time.

If you have an older `accounts.json` from before `session_token` was added, re-run
this command once to regenerate it — `locustfile.py` will refuse to start otherwise.

## Sanity check before the real run

Run this **without** `LOADTEST_RAMP` set — the ramp shape (see below) only activates
when that variable is `1`, so a plain smoke test stays a smoke test:

```bash
.venv/bin/locust -f loadtest/locustfile.py --headless -u 1 -r 1 -t 30s --host http://localhost:8000
```

Check the summary table:
- `/`, `/pricing`, `/login`, `/api/me`, `/settings` → all 200
- `/auth/login` → 200 (cookie login works)
- `/api/capture [mock, expect 403]` → counted as a **success** (that 403 is the
  expected gate-block, not a failure)
- **0 failures** overall, no 5xx anywhere

If that looks right, no Anthropic/OpenAI calls were made — you can safely ramp up.

## Finding the breaking point

The ramp shape is opt-in via `LOADTEST_RAMP=1`. **This is deliberate**: merely
*defining* a Locust `LoadTestShape` class makes Locust ignore `-u`/`-r`/`-t` and run
that class's own schedule instead — without the env var gate, even a "quick 20s
smoke test" would silently turn into the full multi-minute ramp.

```bash
LOADTEST_RAMP=1 .venv/bin/locust -f loadtest/locustfile.py --host http://localhost:8000 \
       --csv loadtest/results/local_run --html loadtest/results/report.html
```

(`--csv`/`--html` paths are relative to wherever you run the command from — since
we're running from the repo root, they need the `loadtest/` prefix so they land in
`loadtest/results/`, which is what's gitignored. If you `cd loadtest` first, drop
the prefix instead.)

Open the web UI at http://localhost:8089 and start the test (or just let it run —
the shape kicks in automatically once `LOADTEST_RAMP=1` is set). `StepLoadShape` in
`locustfile.py` adds `STEP_SIZE` (default 25) users every `STEP_TIME` (default 40s),
starting from `STEP_START` (default 25) — **with no upper cap**, so it keeps
climbing indefinitely. This is a find-the-ceiling run, not a fixed-size test: watch

- **p95/p99 response time** climbing sharply
- **failure rate** climbing (real failures only — mock-capture 403s don't count)
- RPS flattening or dropping while users keep increasing

and **stop the run yourself** (web UI stop button or Ctrl-C) once you see that knee —
it will not stop on its own.

`--csv` writes `loadtest/results/local_run_stats_history.csv`, a per-second time
series of response times/failures — the actual "slowdown over time" log. `--html`
writes a static report you can open in a browser afterward.

To tweak the ramp, traffic mix, or tasks, edit the constants at the top of
`locustfile.py` (`STEP_START`, `STEP_SIZE`, `STEP_TIME`, `ANON_WEIGHT`/`AUTH_WEIGHT`,
`LOGIN_FRACTION`).

**`LOGIN_FRACTION`** controls what share of simulated authenticated users go through
a real `POST /auth/login` (bcrypt + DB write) versus starting with an already-valid
session cookie (a returning user). Every prior run used `1.0` (always a fresh login),
which overstates login-path load — real traffic is mostly already-logged-in sessions,
not concurrent fresh logins. Default is `0.15`. Lowering it further isolates whether
other endpoints (DB reads/writes on `/settings`, `/api/me`, capture's gate check,
etc.) become the bottleneck once login/bcrypt pressure is minimized.

**Known failure mode:** ramping concurrent logins/writes against the SQLite backend
can make the single-process dev server wedge completely — threads stuck (0% CPU,
sockets stuck in `CLOSE-WAIT`), not responding even to a plain `GET /`, and not
shutting down on `SIGTERM` (needs `kill -9`). Root cause: every DB call and the
`bcrypt` password check in `server.py`/`auth.py` are synchronous, blocking calls
made directly inside `async def` routes rather than offloaded to a thread — since
uvicorn here runs a single process/single event loop, one blocked call freezes
*every* request, not just its own. `database.py` now sets WAL mode + a larger
connection pool, which raises the ceiling substantially (confirmed via `py-spy`/
`faulthandler` stack dumps during diagnosis), but the underlying blocking-call
pattern is unchanged, so a large enough run can still wedge it. If the server stops
responding mid-ramp, that's what's happening — keep a terminal free to `kill -9`
and restart `.venv/bin/python server.py`.

## Cleanup

```bash
.venv/bin/python loadtest/seed_users.py --cleanup
```

Deletes all `loadtest_*` users from the DB and removes `accounts.json`.
