# tmap-archived-serializer.avif — archived bytes

Binary lives on block storage (read-only), not in git:

    /mnt/v/output/imazen-26-compat/fixtures-archive/tmap-archived-serializer.avif

sha256: `0dcffa65716e4d062ac60538f1e4dd6608dd73e835f7467aa037e7368f3d3d18` (3611 bytes)

Provenance: AVIF gain-map fixture encoded by the archived standalone
`zenavif-serialize` rev 990bd6d (what published zenavif 0.1.6 wrote):
compatible brands `mif1`,`miaf` only — no `tmap` brand, no `grpl`/`altr`.
The current zenavif workspace-member serializer cannot produce this form, so
the exact bytes are vendored on block storage. `src/generate.rs` reads them
from the path above and fails loudly if the file is missing or the sha256
differs.
