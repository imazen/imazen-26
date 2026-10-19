#!/usr/bin/env bash
# Refresh the tool-owned source checkouts without deleting existing work.
# zencodec/zenmeta and ultrahdr-core are path patches; other dependencies use git main.
set -euo pipefail
cd "$(dirname "$0")"
export TMPDIR="${TMPDIR:-$HOME/tmp}"
mkdir -p "$TMPDIR" zen-main
owner="${SOURCE_SYNC_OWNER:-source-sync-$$}"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
commits=$(mktemp "$PWD/zen-main/COMMITS.XXXXXX")
for repo in zencodec ultrahdr; do
  dir="$PWD/zen-main/$repo"
  mkdir -p "$dir"
  lock="$dir/.workongoing"
  if [ -e "$lock" ]; then
    echo "refusing: source checkout has a lock: $lock" >&2
    exit 1
  fi
  printf '%s %s update tool build source\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$owner" > "$lock"
  if [ ! -d "$dir/.jj" ]; then
    # Check an existing Git checkout before jj imports its working copy.
    if [ -e "$dir/.git" ] && [ -n "$(git -C "$dir" status --porcelain)" ]; then
      echo "refusing: source checkout has uncommitted changes: $dir" >&2
      exit 1
    fi
    (cd "$dir" && jj git init --colocate)
  fi
  if [ -n "$(cd "$dir" && jj diff --name-only)" ]; then
    echo "refusing: source checkout has uncommitted changes: $dir" >&2
    exit 1
  fi
  if ! (cd "$dir" && jj git remote list) | awk '{print $1}' | grep -qx origin; then
    (cd "$dir" && jj git remote add origin "https://github.com/imazen/$repo")
  fi
  (cd "$dir" && jj git fetch && jj new main@origin -m 'build: track current main for corpus tools')
  printf '%s\t%s\n' "$repo" "$(cd "$dir" && jj log -r main@origin --no-graph -T commit_id)" >> "$commits"
  rm "$lock"
done
if [ -e zen-main/COMMITS.tsv ]; then
  cp -p zen-main/COMMITS.tsv "zen-main/COMMITS.before-$stamp.tsv"
fi
mv "$commits" zen-main/COMMITS.tsv
cat zen-main/COMMITS.tsv
