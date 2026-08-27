# Cross-id duplicate census + png-v3 drift inventory (2026-08-27)

Produced by the zensim-side dHash audit after re-basing it on this repo as the
root source (zensim `benchmarks/imazen26_dhash_audit_2026-08-27.md`, CORRECTED
RESULTS section). Two corpus-level facts recorded here because they are
properties of the corpus, not of any consumer:

## 1. Cross-id near-duplicates that cross split buckets

`canon_crossid_pairs_2026-08-27.tsv` — 237 cross-id pairs at dHash-64 d≤10
among the 414 picker-covered images (eval-relevant subset; a full-corpus
census over all 2,160 would extend this). The by-design content families
(patent scan forms `6xxx`, screenshot dpr ladders `8xxx`, plot seed families
`7xxx`) place visually-identical content under different ids, and the
last-digit split rule then lands some twins on opposite sides of
train/validate/test — e.g. `7017`[test] ~ `7064`[train] d=0,
`8229`[test] ~ `8112`[train] d=0. At d≤2 there are 9 non-train ids with a
train-side twin.

Consequence for consumers: id-level split hygiene does not imply
content-level hygiene for these families. Downstream measurement (zensim,
9 leader models, ctrl-vs-clean eval): realized effect on eval SROCC is ≈0
(median Δ +0.0026, max |Δ| 0.0100). Options if content-level separation is
ever wanted: split by content-family key instead of raw id for these
classes, or exclude twins from held-out views.

## 2. png-v3 `nope/` inventory

`png_v3_noid_inventory_2026-08-27.tsv` — the 406 objects in the png-v3
prefix without a 4-digit leading id, all inside the `nope/` staging folder
(auto_screen captures + working material). Already outside the manifest
(membership oracle) and outside every id-keyed consumer; listed concretely
for the queued reconciliation pass (STORAGE-MAP "Known drift"). Mirror note:
the local dev-box mirror was spot-verified byte-identical to the published
prefix (13/13 md5) on this date.
