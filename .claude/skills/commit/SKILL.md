---
name: commit
description: Summarize the working diff since the last commit into a single-line commit message of the major features/changes, and print it in chat. Does NOT commit. Use when the user runs /commit or asks for a one-line commit message for pending changes.
---

# /commit

Produce a **single-line** commit message summarizing the major changes since the last commit, and
print it in chat. **Do not commit, stage, or push anything** — the user commits it themselves.

## Steps

1. Gather the diff since the last commit. Run these together:
   - `git status --short` — see staged, unstaged, and untracked files.
   - `git diff HEAD --stat` — per-file change magnitude.
   - `git diff HEAD` — the actual changes (read enough to understand *what* changed, not just where).
   - For untracked files that look relevant, glance at them too (`git status` lists them).

2. Identify the **major** features/changes — group related edits into themes. Ignore noise
   (whitespace, generated files, lockfile churn). Think in terms of user-facing or architectural
   deltas: e.g. `oauth refactor`, `bug fixes`, `settings page revamp`, `add password toggles`.

3. Write **one line** that captures the headline changes. Guidance:
   - Imperative or noun-phrase, lowercase-ish house style matching recent commits (check
     `git log --oneline -5` for the repo's tone).
   - Comma- or space-separated major items when there are several distinct themes, e.g.
     `oauth refactor, settings revamp, case-insensitive login`.
   - Keep it genuinely one line (aim ≤ ~72 chars where possible; a bit longer is fine if several
     real features shipped). No body, no bullet list.
   - Describe *what changed*, not every file. Lead with the biggest change.

4. Print the message in chat in a copy-pasteable code block, like:

   ```
   oauth refactor, settings page revamp, password show/hide toggles
   ```

   Then stop. Do **not** run `git commit`. If the diff is empty, say there's nothing to commit.
