"""Per-HEIC diff of item colour/aux properties: backup (pre-rewrite) vs canonical."""
import csv, sys, collections
from heif_props import props
rows = [m for m in csv.DictReader(open("matches.tsv"), delimiter="\t")
        if m["canonical"].lower().endswith(".heic") and "lilith-photos-backup" in m["candidate"]]
out = open("heic_prop_diff.tsv", "w")
out.write("id\tcamera\titem_id\titem_type\tbackup\tcanonical\n")
summary = collections.Counter(); per = {}
for m in sorted(rows, key=lambda r: r["id"]):
    a, b = props(m["candidate"]), props(m["canonical"])
    name = m["canonical"].rsplit("/", 1)[1]
    cam = name.split("_")[4] if name.count("_") >= 4 else "?"
    diffs = []
    for iid in sorted(set(a) | set(b)):
        ta, pa = a.get(iid, ("-", ()))
        tb, pb = b.get(iid, ("-", ()))
        if pa != pb:
            ca = [p for p in pa if p.startswith("colr")]; cb = [p for p in pb if p.startswith("colr")]
            aux = [p for p in pa + pb if p.startswith("auxC")]
            diffs.append((iid, ta, pa, pb))
            out.write(f"{m['id']}\t{cam}\t{iid}\t{ta}{' '+aux[0] if aux else ''}\t{' | '.join(pa)}\t{' | '.join(pb)}\n")
    per[m["id"]] = (cam, diffs)
out.close()
for i, (cam, diffs) in per.items():
    kinds = []
    for iid, ty, pa, pb in diffs:
        ca = [p for p in pa if p.startswith("colr")]; cb = [p for p in pb if p.startswith("colr")]
        kinds.append(f"{ty}:{ca[0][5:] if ca else '-'}->{cb[0][5:] if cb else '-'}")
    summary[(cam, tuple(sorted(set(kinds))))] += 1
for (cam, k), n in sorted(summary.items()):
    print(n, cam, "\n    " + "\n    ".join(k) if k else "unchanged")
print(len(per), "HEICs compared")
