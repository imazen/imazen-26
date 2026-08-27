#!/usr/bin/env python3
"""Derive content-sharing sets from PROVENANCE (names/manifest), not dHash.

Two derivations (dHash remains the independent VERIFIER — it screens; this
script decides, deterministically and over the WHOLE corpus):

  A. --pool-names FILE : external-pool sharing. The pool file lists basenames
     (e.g. synthetic-v2 sources). Generated content carries its generator
     tokens in the name on both sides:
         pool:   gen-<kind>__<index>_s<seed>...
         corpus: <id>_plots_<kind>-<index>-s<seed>_...
     Tiers: exact (kind,index,seed) and seed (kind,seed) — for the chart
     generator the seed alone determines content (verified d=0 by dHash).

  B. corpus-internal families whose members cross split buckets. Family keys:
       plots       : (index, seed) — kind VARIANTS of one run (line /
                     line-concentric) render the same content (dHash d=0)
       patents 6xxx: (patent, page) — scan forms of one page. NOTE the
                     lynn-conway trio uses +30 id offsets (parity-preserving
                     ⇒ same bucket by design); the +3/+4-offset families cross
       screenshots : (site, page) minus dpr — grammar <site>_dpr<k>_page<n>;
                     site tokens can drift between dpr sets (loc-exhibits vs
                     loc-exhibitions) so match on a normalized prefix
     Any family with members in >1 split bucket is a split-piercing group.

Output: TSVs next to --out-prefix + a summary to stdout.
"""
import argparse, csv, os, re, collections

def split_of(i):
    d = int(i) % 10
    return "train" if d % 2 == 0 else ("validate" if d in (1, 3, 5) else "test")

def corpus_rows(repo):
    return list(csv.DictReader(open(os.path.join(repo, "CORPUS-MANIFEST.tsv")), delimiter="\t"))

def plot_tokens(basename):
    m = re.search(r"_plots_([a-z-]+?)-(\d+)-s([0-9a-f]+)_", basename)
    return m.groups() if m else None

def pool_tokens(basename):
    m = re.match(r"gen-([a-z-]+?)__(\d+)_s([0-9a-f]+)", basename)
    return m.groups() if m else None

def family_key(row):
    b = os.path.basename(row["path"]); cls = row["folder"]
    if cls.startswith("7000"):
        t = plot_tokens(b)
        return ("plots-run", t[1], t[2]) if t else None
    if cls.startswith("6000"):
        m = re.match(r"\d{4}_[a-z-]+_(.+?)[-_](?:original|rescan-color|rescan-gray)", b)
        pg = re.search(r"_p(\d+)", b)
        if m: return ("patent-page", m.group(1), pg.group(1) if pg else "")
    if cls.startswith("8100"):
        m = re.match(r"\d{4}_[a-z-]+_(.+?)_dpr\d+_page(\d+)", b)
        if m: return ("screen-page", re.sub(r"[^a-z0-9]", "", m.group(1))[:10], m.group(2))
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--pool-names", help="file of pool basenames for derivation A")
    ap.add_argument("--out-prefix", default="/tmp/sharing")
    a = ap.parse_args()
    rows = corpus_rows(a.repo)

    if a.pool_names:
        pool = [os.path.basename(l.strip()) for l in open(a.pool_names) if l.strip()]
        pexact, pseed = {}, collections.defaultdict(list)
        for n in pool:
            t = pool_tokens(n)
            if t:
                pexact[t] = n
                pseed[(t[0], t[2])].append(n)
        hits = []
        for r in rows:
            t = plot_tokens(os.path.basename(r["path"]))
            if not t: continue
            if t in pexact:
                hits.append((r["number"], split_of(r["number"]), "exact", pexact[t]))
            elif (t[0], t[2]) in pseed:
                hits.append((r["number"], split_of(r["number"]), "seed", pseed[(t[0], t[2])][0]))
        with open(a.out_prefix + "_poolshare.tsv", "w") as f:
            f.write("id\tsplit\ttier\tpool_example\n")
            for h in sorted(hits): f.write("\t".join(h) + "\n")
        c = collections.Counter((h[1], h[2]) for h in hits)
        print(f"A pool-share: {len(hits)} corpus ids  {dict(c)}")

    fams = collections.defaultdict(list)
    for r in rows:
        k = family_key(r)
        if k: fams[k].append(r["number"])
    piercing = {k: v for k, v in fams.items() if len({split_of(i) for i in v}) > 1}
    with open(a.out_prefix + "_families.tsv", "w") as f:
        f.write("family\tids\tsplits\n")
        for k, v in sorted(piercing.items()):
            f.write(f"{'|'.join(map(str,k))}\t{','.join(sorted(v))}\t{','.join(sorted({split_of(i) for i in v}))}\n")
    nontrain = sorted({i for v in piercing.values() for i in v if split_of(i) != "train"
                       and any(split_of(j) == "train" for j in v)})
    print(f"B split-piercing families: {len(piercing)} (of {len(fams)}); "
          f"non-train ids with a train twin: {len(nontrain)}")
    with open(a.out_prefix + "_dupoftrain.tsv", "w") as f:
        f.write("id\tsplit\n")
        for i in nontrain: f.write(f"{i}\t{split_of(i)}\n")

if __name__ == "__main__":
    main()
