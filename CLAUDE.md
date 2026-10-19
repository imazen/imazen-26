# Known Bugs

## Resolved 2026-10-19: GPS audit tag-instance grouping

The metadata removal audit grouped ExifTool CopyN labels as position carriers,
which could separate direction references from their coordinates. It now uses
document/metadata-group identity and rejects ambiguous carriers. Rechecking all
291 GPS-bearing sources changed no per-file classification; carrier annotations
were corrected. The original review and audit provenance are preserved.
