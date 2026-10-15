#!/usr/bin/env bash
# Clone the main branch of zencodec (with zenmeta) and ultrahdr into zen-main/.
# Several imazen mains pin older commits of these crates, and Cargo can't patch a git
# source with the same URL, so Cargo.toml patches them in by path from here. Every other
# imazen crate comes from its main branch through git, recorded in Cargo.lock.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p zen-main
: > zen-main/COMMITS.tsv
for repo in zencodec ultrahdr; do
  rm -rf "zen-main/$repo"
  git clone -q --depth 1 "https://github.com/imazen/$repo" "zen-main/$repo"
  printf '%s\t%s\n' "$repo" "$(git -C "zen-main/$repo" rev-parse HEAD)" >> zen-main/COMMITS.tsv
done
cat zen-main/COMMITS.tsv
