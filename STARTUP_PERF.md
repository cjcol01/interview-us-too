# Server startup performance — why the PC is slower than the laptop

**Symptom:** `python server.py` reaches "ready" in ~3–4s on the laptop (macOS) but takes
15s+ on the PC (WSL2).

**What I did:** added lightweight, always-on phase timing to the boot path so a single run
tells you exactly which phase is slow. No behaviour change — just `[startup]` log lines.
Run the server on the PC, copy the `[startup]` lines, and compare to the laptop baseline
below. The phase that's inflated on the PC is the cause.

## How to read the logs

Every boot now prints lines like:

```
[startup] stdlib imports           + 0.04s (since proc start  0.04s)
[startup] heavy imports loaded     + 0.90s (since proc start  0.94s)
[startup] lifespan start           + 0.13s (since proc start  1.07s)
[startup]   init_db create_all       + 0.00s
[startup]   init_db migrations+indexes + 0.00s
[startup]   init_db referral backfill + 0.00s
[startup] init_db() done           + 0.01s (since proc start  1.08s)
[startup] redis reachable          + 0.00s (since proc start  1.08s)
[startup] READY (total boot)       + 0.00s (since proc start  1.08s)
```

- The `+X.XXs` is the time that phase took.
- `since proc start` is the running total from the first instant of the process.
- The three indented `init_db …` lines break the DB init into its sub-steps.

## Laptop baseline (macOS, native SSD)

| Phase | Time |
|-------|------|
| stdlib imports | 0.04s |
| **heavy imports** (anthropic, openai, sqlalchemy, fastapi, …) | **0.90s** |
| rest of module load (routes, templates, clients) | 0.13s |
| init_db (create_all + migrations + backfill) | 0.01s |
| redis reachable | 0.00s |
| **total to READY** | **~1.08s** |

So on a fast filesystem, boot is completely dominated by the `heavy imports` phase.

## Why "heavy imports" is the prime suspect on the PC

Importing `anthropic` + `openai` is expensive because of *file count*, not compute:

- The venv has **~5,800 `.py` files**; `anthropic` alone is **1,073** files and `openai`
  is **1,484**. Importing `server` reads **~2,730 module files** from disk.
- Profiling the import on the laptop shows ~0.66s spent purely in filesystem reads
  (`importlib … get_data` / `BufferedReader.read`) plus ~0.5s of CPU building the ~1,600
  pydantic models those packages define at import time.

On the laptop those 2,730 file reads cost ~0.3–0.9s because the SSD is fast. **On WSL2, if
the repo and its `.venv` live on a `/mnt/…` drive, that path is a 9p network-emulated
filesystem where every `open`/`stat`/`read` is a round-trip.** Multiplying 2,730 tiny file
reads by the 9p per-op penalty is exactly the kind of thing that turns ~1s into 10–15s.

This isn't a guess about the environment: the repo's own code already documents that the
PC dev setup is WSL2 with the project on a 9p `/mnt/d/...` mount — see the comments in
`database.py` (SQLite WAL / 9p warning) and the `__main__` block in `server.py`
(`WATCHFILES_FORCE_POLLING` because inotify doesn't fire on 9p).

## Confirm it on the PC (2 quick checks)

1. **Look at the `[startup]` logs.** If `heavy imports loaded` shows something like
   `+10s`+ while `init_db`/`redis` stay small, the filesystem-bound import is the cause.

2. **Check whether the repo is on a 9p mount** (run in the WSL2 shell, in the repo):
   ```bash
   findmnt -T . -o SOURCE,FSTYPE,TARGET   # FSTYPE '9p' == the slow mount
   df -T .                                # same info, alternative
   # crude read-throughput probe of the venv:
   time find .venv -name '*.py' | wc -l   # slow here strongly implicates the fs
   ```

## The fix (if it's the 9p mount, which is very likely)

Move the project **and its virtualenv** onto the WSL2 Linux filesystem (ext4) instead of
`/mnt/…`:

```bash
# inside WSL2
cp -r /mnt/d/path/to/interview-us-too ~/interview-us-too
cd ~/interview-us-too
rm -rf .venv                       # a venv can't just be moved across fs cleanly
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Running from `~/` (native ext4) instead of `/mnt/d` (9p) typically gives a 5–20x speedup
on import-heavy Python startup and is the standard WSL2 recommendation. It also fixes the
inotify/reload and SQLite-locking caveats the code already works around.

### Other phases to watch (less likely, but the logs will tell you)

- **`redis reachable` shows +2s/+4s/+6s…** — Redis wasn't up yet when the server started;
  the boot blocks on a retry loop (`server.py` lifespan, 5 attempts × 2s sleeps). Start
  Redis first, or make sure it's running as a service. On the laptop this is 0.00s because
  Redis answers immediately.
- **`init_db …` sub-steps are large** — SQLite DDL touches the DB file plus its `-wal`/
  `-shm` sidecars repeatedly; on 9p that's slow too. Same fix (move off the mount).

## Note on the laptop

The laptop measured ~1.1s to READY here, faster than the "3–4s" you quoted — the extra
couple of seconds there is likely interpreter/venv cold-cache and shell startup, not the
app. The point of the instrumentation is the *relative* breakdown, which is what pinpoints
the PC's bottleneck. Your earlier hunch ("not everything is set up on the laptop") is worth
keeping in mind for the `redis` line specifically: if Redis isn't installed/running on one
machine, that phase is where it'll show up.

## Reverting the instrumentation

The logging is cheap and harmless to leave in. If you ever want it gone, remove the
`_PROC_T0`/`_BOOT_T0`/`_boot_mark` additions in `server.py` and the `_mark(...)` calls in
`database.py`'s `init_db()`.
