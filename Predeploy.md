# Predeploy Checklist

- [ ] E2E test: Stripe subscription referral credit (earn credit → referee subscribes → Stripe auto-applies balance → `referral_credit_pence` deducts via `invoice.paid`)
- [ ] Tighten CORS `allow_origins` from `*` to real domain (`server.py`)
- [ ] Verify card-fingerprint dedup fires on first real purchase with a live Stripe key (`billing.py`)
- [ ] Harden `_require_author` admin check — keys off mutable `username`, not a fixed admin id (`server.py`)
- [ ] Set `BASE_URL` to the real domain (still `127.0.0.1` locally)
- [ ] Set all required production env vars on the host (see table in `CLAUDE.md`)
- [ ] Set up basic alerting/health check — nothing currently pages on a critical failure (see `OPS_PLAN.md`)
- [ ] Decide on a rollback plan for a bad deploy — currently none beyond manual `git revert` (see `OPS_PLAN.md`)

## Alembic migrations

- New schema changes go in a **new revision file** (`alembic revision -m "description"`), never in `c1a770f1636e_baseline.py` — that file is permanently a no-op marker; editing it won't run anything
- `init_db()` auto-detects fresh vs existing DBs: fresh gets `alembic stamp head`, existing gets `alembic upgrade head` — no manual steps needed on deploy
- Avoid DDL that acquires `AccessExclusiveLock` (e.g. `ALTER TABLE DROP/ADD CONSTRAINT`) on tables with live traffic; Railway keeps failed containers alive during its grace period and the lock will cascade across deploys

## Predeploy setup

- [ ] Pick a host (Railway/Render/Fly.io/VPS), deploy, confirm clean start
- [ ] Point Stripe webhook to the live `/billing/webhook` endpoint
- [ ] Confirm SSL/HTTPS
- [ ] Consider switching Cloudflare from grey cloud (DNS only) to orange cloud (proxied) for DDoS protection — requires setting Cloudflare SSL/TLS mode to **Full (strict)** first, otherwise Cloudflare→Railway leg is plain HTTP. Railway's Let's Encrypt cert is valid so Full (strict) works fine.
- [ ] Buy domain, point DNS to host
- [ ] Set up support email (Resend/Cloudflare/Workspace)
- [ ] Update `FROM_EMAIL` once live
- [ ] Chrome extension E2E — capture/audio/typing hotkeys, badge states, hotkey sync
- [ ] Referrals — `/r/{code}` signup credit, self-referral blocked, retroactive `/referral/apply`
- [ ] Fresh DB — delete `users.db`, restart, confirm `init_db` creates tables cleanly
- [ ] Decide: Chrome Web Store / firefox vs. sideload; prep store listing if publishing
- [ ] create CDN backup for extension + video install
- [ ] dont launch on main domain, launch on subdomain

## Marketing

- [ ] LinkedIn post / outreach
- [ ] Discord communities (coding, interview prep)
- [ ] Reddit (r/cscareerquestions, r/leetcode, r/programming)
- [ ] TikTok / Instagram demos
- [ ] Direct ads (Google / Meta)
- [ ] Trustpilot — set up profile, request early reviews