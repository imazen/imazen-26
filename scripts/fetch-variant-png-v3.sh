#!/usr/bin/env bash
# Populate variant/png-v3: fetch renders from public R2, commit as LFS pointers in
# batches, push each batch, dedup so worktree and LFS cache share APFS blocks.
# Idempotent: re-running skips files already on disk and already-pushed batches.
set -uo pipefail
REPO=${REPO:-$(git rev-parse --show-toplevel)}
D=${D:-$(mktemp -d)}   # working dir for url lists and batch files
LOG=$D/png-v3-fetch.log
BASE=https://codec-corpus.r2.imazen.org/imazen-26-png-v3/
BATCH=120
cd "$REPO" || exit 1
say(){ printf '%s %s\n' "$(date -u +%H:%M:%S)" "$*" | tee -a "$LOG"; }
# BSD xargs -I has a ~255B replsize cap and these URLs are longer, so pass the
# URL as a positional arg instead of using a replacement string. BASE/D are
# exported so the child shells inherit them -- passing the worker through
# `bash -c "$(declare -f ...)"` silently drops them and writes every file to a
# path built from the un-stripped URL.
export BASE D

rm -f "$D"/batch-*
say "START"

if [ ! -f "$D/hdr-urls.txt" ]; then
  say "probing 2160 urls for .hdr.png companions"
  sed 's/\.sdr\.png$/.hdr.png/' "$D/png-urls.txt" \
    | xargs -P 12 -n 1 sh -c 'curl -sfI "$1" >/dev/null 2>&1 && echo "$1"' _ \
    > "$D/hdr-urls.txt"
fi
say "hdr renders found: $(wc -l < "$D/hdr-urls.txt" | tr -d ' ')"

# all-urls.txt is pre-verified (HEAD 200 only) — see MISSING.tsv for the 404s
say "total objects in set: $(wc -l < "$D/all-urls.txt" | tr -d ' ')"

: > "$D/todo.txt"
while read -r u; do
  rel="${u#$BASE}"
  [ -s "png-v3/$rel" ] || echo "$u" >> "$D/todo.txt"
done < "$D/all-urls.txt"
say "still to fetch: $(wc -l < "$D/todo.txt" | tr -d ' ')"

: > "$D/failed.txt"
split -l "$BATCH" "$D/todo.txt" "$D/batch-"
batch=0
for bf in "$D"/batch-*; do
  batch=$((batch+1))
  free=$(df -g /Users/lilith | tail -1 | awk '{print $4}')
  if [ "$free" -lt 6 ]; then say "ABORT: only ${free}Gi free"; exit 2; fi
  say "batch $batch: $(wc -l < "$bf" | tr -d ' ') files, ${free}Gi free — downloading"
  nice -n 19 xargs -P 8 -n 1 sh -c '
    u="$1"; rel="${u#$BASE}"
    mkdir -p "png-v3/$(dirname "$rel")"
    curl -sSf --retry 3 --retry-delay 2 -o "png-v3/$rel" "$u" || echo "$u" >> "$D/failed.txt"
  ' _ < "$bf" 2>>"$LOG"
  # paths must mirror the corpus layout; anything else means URL stripping broke
  if find png-v3 -type d -name 'https:' | grep -q .; then
    say "batch $batch: ABORT — URL-shaped paths under png-v3/, stripping is broken"
    exit 4
  fi
  # curl without -f writes the error body to the output file and exits 0, so a
  # 404 page can land named .png. Reject anything without the PNG signature
  # BEFORE it is staged — a bad blob cannot be rewound out of a pushed branch.
  notpng=0
  while IFS= read -r f; do
    [ "$(head -c 8 "$f" | xxd -p)" = "89504e470d0a1a0a" ] && continue
    say "  not a PNG, removing: $f"; rm -f "$f"; notpng=$((notpng+1))
  done < <(find png-v3 -name '*.png' -newer "$bf" 2>/dev/null)
  [ "$notpng" -gt 0 ] && say "batch $batch: dropped $notpng non-PNG responses"
  git add png-v3 >>"$LOG" 2>&1
  cnt=$(git diff --cached --name-only | grep -c .)
  [ "$cnt" -eq 0 ] && { say "batch $batch: nothing staged"; continue; }
  git -c user.name="Lilith River" -c user.email="jill@imazen.io" \
      commit -q -m "feat(png-v3): renders batch $batch ($cnt files)" >>"$LOG" 2>&1
  git push -q origin variant/png-v3 >>"$LOG" 2>&1 \
    || { say "batch $batch: PUSH FAILED"; exit 3; }
  git lfs dedup >>"$LOG" 2>&1
  say "batch $batch: done — $(git lfs ls-files | wc -l | tr -d ' ') tracked, $(du -sh png-v3|cut -f1) on disk"
done
say "FETCH COMPLETE tracked=$(git lfs ls-files | wc -l | tr -d ' ') failed=$(wc -l < "$D/failed.txt" | tr -d ' ')"
