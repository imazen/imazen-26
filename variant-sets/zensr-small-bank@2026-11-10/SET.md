# zensr-small-bank@2026-11-10

**Status:** completed exploration bank with a verified retained mirror; image bytes are not published.
**Consumer:** [zensr](https://github.com/imazen/zensr), repair/SR tuning tools.
**Membership authority:** corpus metadata at
`32ba0ebea7b3cccbd6e141a397d90423140a7fc6`.

The bank selects **244 origins in 21 categories**, 161 train and 83 validate,
with no test images read. Selection requires agreement between the published
four-digit-ID split and successor `split_map_family_v2.tsv`. It excludes 207
role disagreements and two sources over the 64 MP input cap. Within each
split/category, deterministic hash order selects at most eight train/four
validate origins and one member per declared family. This is an exploratory
selection, not a clustering-derived production training set.

The source is the existing render-v4 sRGB IMI train/validate archives. Export
IDs prefix the four-digit corpus ID with `1`, following
[`render_v4_list.py`](https://github.com/imazen/imazen-26/blob/bcea0abc1210ac589ada62c80df9dca177f13ff7/scripts/render_v4_list.py).
Both IDs and roles remain in [`selection.tsv`](selection.tsv).

Whole-frame aspect-fit LR long edges are 32/64/128. The short side rounds to
the nearest integer; HR is exactly four times LR. No crop is applied.
Source→HR→LR uses zenresize linear-light CatmullRom. Sources are rendered
sRGB RGB8 or Gray8 (replicated exactly into RGB). HDR and alpha are not covered.
Every origin includes clean input and JPEG q5/10/20/30/40/50/60/70/80/90/100
with 420 and 444 sampling, encoded/decoded by zenjpeg.

CUDA canon4 produces raw F32 repair candidates; shared native guards and
coefficient projection produce guard-only and half/default/double slack
variants. SPANF and DSCF upscale decoded, half-repaired and fully repaired
RGB8. The bank contains **16,836 input cases and 213,012 retained images**,
including **98,088 SR outputs**, stored losslessly in **244 IMIJ archives**.
Archive bytes total **7,140,865,837**. The forced offline repair comparison
does not replay the runtime router/deblock policy. Existing canon4 training
exposure precludes fresh base-model generalization claims.

Generator source: zensr `053525fee19d4b055b5add9e9844e4cb0fce7f6a`;
frozen image worker source: `69c3f45352331753f8fc43bdfa7dbef3adf04bc9`.
[Generator and retention contract](https://github.com/imazen/zensr/blob/63f6d78d80817e482d803b5e776308a10730f04a/tools/sr-bank/README.md).
[Measured generation and limitations](https://github.com/imazen/zensr/blob/090c6291fe8ad48250b7e8dc6ceb51e9fc660596/benchmarks/sr_bank_2026-11-10.md).

`files.tsv` hashes the archive files. Its width/height are zero because each
archive contains multiple image geometries. `records.tsv` hashes each
companion JSON record, which identifies every archive entry's dimensions,
encoded/pixel hashes, model/settings, original/render URLs, feature schema
and scalar PSNR/zensim-A/SSIM2 results. These records preserve both original
generation and reuse identities. No metric maps are stored.

Known copy: i265, `/mnt/v/output/zensr/sr-bank-20261110/run-v3/shards/`.
The plan and completion identities live in the parent run directory.
Plan SHA-256:
`decae0dc98e047b2335f05b2d9a72730953950933198d3dd2a882df95e01ba8d`.
Completed bank identity SHA-256:
`86ba55a4193a56aa22b1fec9e66c4e1ec673a1d52cebf7339ad6c68c786fa2a8`.
Source-image licences remain those of the corpus manifests. This registration
publishes metadata only and does not redistribute images or model weights.

Verified retained copy (2026-11-10):
`tower:/mnt/disk1/coefficient/output/zensr/sr-bank-20261110-v1.tar`,
7,749,263,360 bytes, SHA-256
`35689212375377ed1bd479c952db1248d52f769158872faa9f971b7e45b6f56d`.
The archive includes `run-v3/shards/` plus the plan, original reuse provenance,
frozen binaries and completed scalar blend study. Sender/receiver stream hashes
match; file/directory fsync completed; three seeded random IMIJ members read back
from the retained tar match their registered file hashes. The local receipt is
`BACKUP_RECEIPT.json` in the bank root. Access was over SSH, without NFS.

## Frozen-input limitations

This registration identifies the original experiment, not corrected encoder
outputs. Its pinned zenjpeg `24b6d3fb` has a partial-strip chroma-padding bug:
a neutral 32×8 420 witness gains tint during encoding, reproduced by both
zenjpeg and libjpeg-turbo decoding. JPEG padding was corrected on main through
[zenjpeg PR 262](https://github.com/imazen/zenjpeg/pull/262). The bank also
predates zensr's partial-block projection correction `0bb29cf6`. Original
JPEGs, candidates and scores remain frozen; no claim of corrected-runtime
quality follows from this registry.

[Separate projection replay and corrected SR witnesses](https://github.com/imazen/zensr/blob/5042bccd10027964c25d86a13cdc46ef926e6dbe/benchmarks/projection_fix_2026-11-10.md)
retain new artifact identities rather than overwriting these archives.
