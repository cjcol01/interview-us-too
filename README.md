# Interview Prep tool

A real-time coding interview prep tool. A Chrome extension captures your screen and sends it to a self-hosted server, which uses Claude to analyse the question and return a solution at your chosen complexity level — from a simple naive approach up to optimal with trade-off explanations.

## How it works

1. You're on a coding platform
2. Press `Ctrl+Shift+Y` (or click the extension popup) to capture the screen
3. The extension sends the screenshot to the server
4. Claude analyses the question and streams the result back to your web dashboard
5. You can adjust the complexity level (1-3) to get hints at different depths

**Complexity levels:**
- 1 — naive approach, simple and readable
- 2 — clean solution a junior dev would write
- 3 — optimal, production-quality, with trade-offs and edge cases covered

## Stack

- **Backend:** Python, FastAPI, SQLite via SQLAlchemy
- **AI:** Anthropic Claude (claude-sonnet-4-6) via vision API
- **Extension:** Chrome Manifest V3
- **Billing:** Stripe (subscription + one-time sessions plan)
- **Email:** Resend

## Setup

### 1. Clone and install dependencies

```bash
pip install -r requirements.txt
```

### 2. Create a `.env` file

Your on your own with this one!

`SECRET_KEY` is required — the server will refuse to start without it.

### 3. Run the server

```bash
python server.py
```

The server starts at `http://localhost:8000` by default.

### 4. Load the Chrome extension

1. Go to `chrome://extensions`
2. Enable Developer Mode
3. Click "Load unpacked" and select the `extension/` folder

Open the popup, paste your API token from the settings page, and you're ready.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Shift+Y` | Capture current tab and analyse |
| `Ctrl+Shift+9` | Toggle the assistant on/off |

## Project structure

```
server.py          # FastAPI app, capture API, SSE stream
auth.py            # JWT auth, password hashing
billing.py         # Stripe checkout, portal, webhooks
mailer.py          # Email verification via Resend
models.py          # SQLAlchemy models (User, InterviewSession)
database.py        # DB init and session factory
config.py          # Env var loading
extension/         # Chrome extension (MV3)
templates/         # Jinja2 HTML templates
```

## Deployment notes

- Switch SQLite to Postgres for production
- Set `BASE_URL` to your public domain
- Configure the Stripe webhook endpoint to `/billing/webhook`
- The extension is currently sideloaded — publishing to the Chrome Web Store requires a $5 developer account and a review
