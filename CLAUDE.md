# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Bash path rule

Always use double-quoted paths in Bash commands (e.g. `ls "/Users/cjcoleman/CJ All/..."`). Never use backslash-escaped paths (e.g. `ls /Users/cjcoleman/CJ\ All/...`) — they break permission matching and trigger prompts.

## Commands

```bash
# Run the server
python server.py

# Run the server with auto-reload on file changes (dev only)
RELOAD=1 python server.py

# Run all tests (uses fakeredis, no real services needed)
python run_tests.py

# Run a specific test section by temporarily commenting out other sections in run_tests.py
TESTING=1 python run_tests.py
```

The test runner sets `TESTING=1` automatically, which swaps real Redis for fakeredis. External API tests (Claude, Stripe) require real keys to pass.

## Architecture

This is a FastAPI web app with a Chrome extension. The flow: extension captures a screenshot → POSTs to `/api/capture` with a Bearer token → server sends it to Claude via the Anthropic vision API → streams the response back to the browser dashboard via Server-Sent Events (SSE) over Redis pub/sub.

**Core modules:**

- `server.py` — all routes, business logic, SSE streaming. Single file; nothing is split into routers.
- `auth.py` — two auth paths: cookie-based JWT (browser sessions via `get_current_user`/`get_optional_user`) and Bearer token (extension API calls via `get_user_by_token`).
- `models.py` — three SQLAlchemy models: `User`, `InterviewSession`, `Referral`. `AccountLevel` enum: `free → trial → paid → unlimited`.
- `billing.py` — Stripe checkout, portal, and webhook handling.
- `config.py` — all env vars. Server **refuses to start** if `SECRET_KEY` is the default or if Stripe keys are missing.
- `database.py` — SQLite by default (`interview.db`), SQLAlchemy session factory.
- `mailer.py` — Resend API for verification and cancellation emails.
- `extension/` — Chrome MV3 extension. `background.js` handles hotkeys and API calls; `content.js` bridges the extension ↔ page.
- `templates/` — Jinja2 templates. `base.html` is the layout parent.
- `tests/` — custom test harness (`harness.py`), not pytest. Each `test_*.py` exports a `register(test, skip, client)` function called from `run_tests.py`.

**Redis usage:** capture state (`user:{id}:capture`), complexity setting (`user:{id}:complexity`), pub/sub channel (`user:{id}:events`) for SSE streaming, and rolling conversation history (`user:{id}:history`) — a bounded list of the last `HISTORY_MAX_EXCHANGES` (default 5) exchanges, text-only (screenshots are never re-sent, only the current capture's own image), shared across all three capture endpoints and prepended to the Claude/OpenAI `messages` array in `_stream_ai_response`. Skipped if the gap since the last capture exceeds `HISTORY_TOPIC_GAP_SECONDS` (default 5min); cleared when a genuinely new `InterviewSession` starts, with a TTL matching session length as a backstop. Fakeredis is used in tests via `TESTING=1`.

**Session model:** `InterviewSession` tracks 2.5-hour paid sessions and 10-minute trials. Paid users get sessions deducted from `sessions_remaining` when starting a new one.

**Rate limiting:** implemented directly in Redis (`rl:{uid}:{endpoint}:last` / `rl:{uid}:{endpoint}:count`), no external library.

## Key env vars

| Var | Required | Notes |
|-----|----------|-------|
| `SECRET_KEY` | Yes | Server won't start without it |
| `ANTHROPIC_API_KEY` | Yes | Vision API for captures. On failure, requests fail over to OpenAI vision (`gpt-4o`) — see `_stream_ai_response` in `server.py` |
| `OPENAI_API_KEY` | Yes | `gpt-4o-transcribe` for audio capture, and the Claude vision fallback (`gpt-5.4`) above |
| `DEEPGRAM_API_KEY` | No | Fallback transcription if OpenAI transcription fails. Without it, an OpenAI outage just fails the audio capture as before |
| `STRIPE_SECRET_KEY` | Yes | |
| `STRIPE_WEBHOOK_SECRET` | Yes | |
| `STRIPE_SUB_PRICE_ID` / `STRIPE_PRICE_ID` | Yes | |
| `STRIPE_SESSIONS_INTRO_PRICE_ID` | Yes | |
| `STRIPE_SESSIONS_PACK_PRICE_ID` | Yes | |
| `REDIS_URL` | No | Defaults to `redis://localhost:6379/0` |
| `BASE_URL` | No | Used in extension setup; defaults to local IP |
| `DB_DATA_DIR` | No | Where SQLite files live. Defaults to `~/.interview-us-too` (a WSL2 workaround — see `config.py`). Set explicitly on servers/VPS to a path your deploy/backup process actually manages. |
| `AI_PROMPT` | No | System prompt for Claude |
| `RESEND_API_KEY` | No | Email verification |
| `AUTHOR_PASSWORD` | No | Gates an internal admin-only page. Keep unset locally; set a strong random value in production. |
| `SKIP_EMAIL_VERIFICATION` | No | Dev-only convenience flag — see `.env` for details. Must never be set in production. |
