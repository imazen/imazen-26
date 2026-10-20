# Known Bugs

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
