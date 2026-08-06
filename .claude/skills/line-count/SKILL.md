---
name: line-count
description: Print line counts for git-tracked files, broken down by extension plus a repo total. Use when the user runs /line-count or asks how many lines of code are in the repo.
---

# /line-count

Print a table of line counts for git-tracked files. **Output the command's result and nothing
else** — no preamble, no commentary, no analysis of the numbers, no follow-up offer.

## Steps

1. Run this from the repo root, exactly as written:

   ```bash
   bash .claude/skills/line-count/count.sh $ARGUMENTS
   ```

   With no arguments it counts `py js html css`. If the user named extensions (`/line-count py ts`,
   "line count for rust and toml"), pass those instead, bare — no dots, no globs: `py ts`, `rs toml`.

2. Print the script's stdout verbatim in a plain code block. That's the whole response.

## Notes

- `total` is every tracked file, not the sum of the listed extensions — it includes everything not
  broken out (`.md`, `.json`, `.txt`, …). It is normally larger than the rows above it; that is
  correct, not a bug.
- Binary files (`.png`, `.ico`, `.zip`) are counted by `wc -l` as whatever newline bytes they
  happen to contain. There are few enough here that it doesn't distort the total meaningfully.
- An extension with no tracked files reports `0` rather than being skipped.
- If the command fails because this isn't a git repo, say exactly that in one line.
