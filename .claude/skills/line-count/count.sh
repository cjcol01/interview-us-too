#!/bin/bash
# Line counts for git-tracked files, per extension plus a repo-wide total.
# Usage: count.sh [ext ...]   — bare extensions, no dots. Defaults to py js html css.
#
# git ls-files -z / xargs -0 is load-bearing: this repo has tracked paths with
# spaces in them (e.g. "Cancel Confirm v2.dc.html"), which plain `xargs wc -l`
# splits into nonexistent filenames and silently drops from the count.
set -uo pipefail

exts=("$@"); [ ${#exts[@]} -eq 0 ] && exts=(py js html css)

# Last line of `wc -l` is "N total" for many files, "N path" for exactly one;
# $1 covers both. The END block prints 0 when the extension matched nothing.
count() { git ls-files -z "$@" | xargs -0 wc -l 2>/dev/null | tail -1 | awk '{n=$1} END{print n+0}'; }

{ for e in "${exts[@]}"; do echo "$e $(count "*.$e")"; done; echo "total $(count)"; } \
  | awk '{ k[NR]=$1; v[NR]=$2; if (length($1)>w) w=length($1); if (length($2)>n) n=length($2) }
         END { for (i=1;i<=NR;i++) { if (i==NR) { s=""; for (j=0;j<w+n+2;j++) s=s"-"; print s }
                                     printf "%-*s  %*s\n", w, k[i], n, v[i] } }'
