# Known Bugs

## Resolved 2026-10-20: stale raw decoder report inputs

The canonical raw `decode-check` tables still held pre-redo-5 results while the
full recheck and canonical bitmap table already reflected redo 5. Regenerating
the report from those raw tables reported 24 obsolete mismatches. The P3
conversion refresh uses the verified full recheck as its baseline, merges only
the new P3 rows, and checks that exactly eight bitmap rows change. The refreshed
full report passes all 4,300 JXL files and all 3,670 lossless PNG twins.
Evidence: `benchmarks/p3_conversion_2026-10-20.pointer.md`.

## Resolved 2026-10-20: selected census aliases and historical reader hashes

`--ids` narrowed the census alias output along with decoding. It now writes the
full current alias map after a selected top-up. The append-only census also
retains old encoded hashes: including those in the public hash download after
redo 5 would create 252 duplicate path/decoder identities. The builder now selects
current manifest hashes, while preserving the historical census rows. The public
browser check rejects duplicate identities. The top-up covers all 24 replacement
paths, and the deployed download has zero duplicates. Evidence:
`benchmarks/review_topup_2026-10-20.pointer.md`.

## Resolved 2026-10-20: temporary filesystem files in publication snapshots

A branch switch on the publication storage exposed `.fuse_hidden*` files to jj's
next snapshot. The failed, unpublished validation candidate contained these files;
all 17 already-uploaded commits were checked and contained none. Local Git excludes
now keep the temporary files out of subsequent snapshots. Before every push the
publisher checks every committed path against the branch manifest and the explicit
documentation list, and final verification repeats this across the complete reachable
history. The saved failed candidate is rejected by this check; the uploaded train
candidate passes. No remote history or source image was changed.

## Resolved 2026-10-19: GPS audit tag-instance grouping

The metadata removal audit grouped ExifTool CopyN labels as position carriers,
which could separate direction references from their coordinates. It now uses
document/metadata-group identity and rejects ambiguous carriers. Rechecking all
291 GPS-bearing sources changed no per-file classification; carrier annotations
were corrected. The original review and audit provenance are preserved.

## Resolved 2026-10-19: publication data-branch commit ancestry

A non-main data bookmark stayed mutable after its first jj push, so the next
snapshot rewrote the local batch candidate. The sideways push was interrupted
before the remote ref moved. A forward merge retains both local snapshots and
the original uploaded commit. The publisher now checks the previous remote
commit is an ancestor before every push and explicitly creates the next child
when jj leaves the pushed data commit writable. Resume verifies existing file
bytes and requires the task's owned private checkout. No remote history was
rewritten and no source image bytes changed.
