#!/usr/bin/env bash
# Build the v4 review as a static site and deploy it to Cloudflare Pages: project
# imazen-26-review, https://imazen-26-review.pages.dev, custom domain imazen-26.imazen.org (a CNAME
# to the pages.dev name, registered on the project).
#
#   scripts/deploy_v4_review_site.sh <render-dir> <stage-dir> <site-dir>
#
# <stage-dir> is the review's staging dir with `build_v4_review.py images` and `fullpacks` done
# (the artifact's .artifact-staging/v4-review); <site-dir> is rebuilt from scratch. Needs
# CF_PAGES_KEY (a token with Cloudflare Pages Write) and R2_ACCOUNT_ID (the account id) in the
# environment. Check the result with scripts/check_v4_review_site.py.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
render="$1"; stage="$2"; site="$3"
project="${PAGES_PROJECT:-imazen-26-review}"
: "${CF_PAGES_KEY:?needs CF_PAGES_KEY, a token with Cloudflare Pages Write}"
: "${R2_ACCOUNT_ID:?needs R2_ACCOUNT_ID, the Cloudflare account id}"
python3 "$repo/scripts/build_v4_review.py" site "$render" "$stage" "$site"
export CLOUDFLARE_API_TOKEN="$CF_PAGES_KEY" CLOUDFLARE_ACCOUNT_ID="$R2_ACCOUNT_ID"
wrangler=(npx --yes wrangler@4.148.0)
# wrangler 4.148 hands a new Pages project to Cloudflare Workers unless --force is given, and a
# Pages-only token can't deploy Workers; once the project exists, Pages commands go to Pages.
if ! "${wrangler[@]}" pages project list 2>/dev/null | grep -qw "$project"; then
  "${wrangler[@]}" pages project create "$project" --production-branch main --force
fi
"${wrangler[@]}" pages deploy "$site" --project-name "$project" --branch main --commit-dirty=true
