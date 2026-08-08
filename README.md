# Interview Prep tool

A practice companion for coding interview prep. Work through problems on any coding platform, capture the ones you get stuck on (or want to double-check your approach against), and a self-hosted server sends them to Claude, which explains a solution at your chosen complexity level — from a simple naive approach up to optimal with trade-off explanations — so you can compare it to your own attempt and learn from the gap.

## How it works

1. Sit down with a coding platform (LeetCode, HackerRank, a take-home, your own mock-interview set) and attempt the problem yourself first
2. Stuck, or want to sanity-check your solution? Press `Ctrl+Shift+6` (or click the extension popup) to capture the screen
3. The extension sends the screenshot to your server
4. Claude analyses the question and streams a walkthrough back to your web dashboard — read it, compare it to what you wrote, and note what you'd change
5. Adjust the complexity level (1-3) to see the same problem explained at different depths, which is a good way to check you actually understand *why* a solution is optimal, not just what it is

**Complexity levels:**
- 1 — naive approach, simple and readable — good for building basic understanding first
- 2 — clean solution a junior dev would write
- 3 — optimal, production-quality, with trade-offs and edge cases covered — the level to aim for before a real interview

Audio capture works the same way for practicing verbal answers: record yourself talking through a question out loud (the way you'd have to in a real interview), and get a breakdown back to compare against how you explained it.

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
| `Ctrl+Shift+6` | Capture current tab and analyse |
| `Ctrl+Shift+7` | Hold to record audio question |
| `Ctrl+Shift+8` | Instant replay of the last few seconds of tab audio |
| `Ctrl+Shift+9` | Typing mode |
| `Ctrl+Shift+0` | Turn the assistant on/off |

All five shortcuts are user-rebindable from the Settings page.