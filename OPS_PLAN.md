# Backup, Security & Reliability Plan

## Backup

- **SQLite DB (`users.db`) has no backup process.** It lives at `DB_DATA_DIR` (default `~/.interview-us-too`, outside the repo) and nothing copies it off-box. Set up a nightly cron that copies the file (or uses `sqlite3 .backup`) to off-server storage (S3, Backblaze, etc.).
- **No point-in-time recovery.** WAL mode means a crash mid-write is safe, but there's no way to recover to "yesterday at 3pm" without periodic snapshots. Daily backups + a few weeks of retention would cover this.
- **`.env` / secrets have no backup.** If the server disk is lost, `SECRET_KEY`, Stripe keys, etc. are gone too. Keep a copy in a password manager or secrets vault, not just on the box.
- **Redis is not backed up** — acceptable since it's only pub/sub + rate-limit counters + capture state, all safely reconstructable/ephemeral.

## Security

- **Deploy runs as a self-hosted GitHub Actions runner that pulls and restarts on every push to `main`**, with no review gate or staging step. Anyone with push access to `main` (or who compromises the GH repo) gets code execution on the server. Consider requiring PR review before merge, or at least branch protection.
- **`AUTHOR_PASSWORD` gates `/verify-author` via HTTP Basic auth** — Basic auth sends credentials in plaintext unless the whole path is HTTPS-only; confirm the reverse proxy enforces HTTPS and doesn't log the header.
- **Stripe webhook signature verification is in place** (`stripe.Webhook.construct_event`), which is good — no action needed there.
- **No secrets scanning / rotation policy.** If `STRIPE_SECRET_KEY` or `SECRET_KEY` ever leak (e.g. committed by accident), there's no defined rotation runbook. Worth a short checklist for "what do I rotate if X leaks."
- **Bearer tokens for the extension (`api_token`) don't appear to expire.** A stolen token is valid indefinitely — consider optional expiry/rotation.

## Reliability

- **Single point of failure: one server, one SQLite file, one Redis instance, no redundancy.** Any hardware failure takes the whole product down until manually restored from backup (which, per above, doesn't exist yet).
- **Deploy has no rollback mechanism.** If a bad commit lands on `main`, the fix is "push another commit" — there's no quick revert-to-last-known-good beyond `git revert` + waiting for CI again. A tagged "last good deploy" or a manual rollback script would shorten downtime.
- **No health check / auto-restart monitoring beyond systemd.** `systemctl restart interview-wise` handles crashes, but nothing alerts you when it happens or when the process is unhealthy but still "running" (e.g. DB locked, Redis down). A simple uptime/health-check ping (e.g. UptimeRobot hitting `/`) would close this gap cheaply.
- **SQLite under concurrent load**: WAL + 30s busy_timeout is a reasonable mitigation, but SQLite is still single-writer — if traffic grows a lot, writes will start queuing. Worth revisiting (e.g. Postgres) if session volume increases significantly.
