import csv, collections
canon={r["id"]:r for r in csv.DictReader(open("/mnt/v/output/imazen-26-variants/signal-index-2026-09-24/sources_signal.tsv"),delimiter="\t")}
cand={}
paths=dict(l.rstrip("\n").split("\t") for l in open("cand_list.tsv"))
inv={v:k for k,v in paths.items()}
for r in csv.DictReader(open("cand_signal.tsv"),delimiter="\t"): cand[r["id"]]=r
matches=list(csv.DictReader(open("matches.tsv"),delimiter="\t"))
def sig(r):
    s={}
    if int(r["icc_bytes"] or 0): s["icc"]=r["icc_desc"] or "icc"
    if r["sig_cicp"] not in ("","-"): s["cicp"]=r["sig_cicp"]
    if r["png_srgb"] not in ("","-"): s["srgb-chunk"]=r["png_srgb"]
    if r["png_gama"] not in ("","-"): s["gama"]=r["png_gama"]
    if r["png_chrm"]=="1": s["chrm"]="1"
    if r["orientation"] not in ("","1","0"): s["orient"]=r["orientation"]
    gm=[]
    if r["heic_gain_map"]=="1": gm.append("heic-aux")
    if r["heif_tmap"]=="1": gm.append("tmap")
    if r["jpeg_mpf"]=="1" or (r["jpeg_images"] not in ("","1","0")): gm.append("jpeg-mpf")
    if r["jpeg_gain_map_signal"] not in ("","None"): gm.append("jpeg-"+r["jpeg_gain_map_signal"])
    if gm: s["gainmap"]="+".join(gm)
    if r["heif_clli"] not in ("","-") or r["sig_clli"] not in ("","-"): s["clli"]=r["heif_clli"] or r["sig_clli"]
    if int(r["exif_bytes"] or 0): s["exif"]="1"
    if int(r["xmp_bytes"] or 0): s["xmp"]="1"
    return s
report=[]
per_id=collections.defaultdict(list)
for m in matches:
    if m["candidate"]: per_id[m["id"]].append(m)
lost=collections.Counter(); lost_ids=collections.defaultdict(set); changed=collections.Counter(); changed_ids=collections.defaultdict(set)
for i,ms in per_id.items():
    cs=sig(canon[i])
    for m in ms:
        c=cand.get(inv[m["candidate"]])
        if not c or c["error"]: continue
        os_=sig(c)
        for k,v in os_.items():
            if k not in cs:
                lost[(m["class"],k)]+=1; lost_ids[(m["class"],k)].add(i)
            elif cs[k]!=v and k in ("icc","cicp","orient","gainmap"):
                changed[(m["class"],k,v,cs[k])]+=1; changed_ids[(m["class"],k)].add(i)
        for k in cs:
            if k not in os_ and k in ("icc","cicp","orient","gainmap","srgb-chunk","gama","chrm"):
                changed[(m["class"],"GAINED "+k,"",cs[k])]+=1
print("== signals present in an earlier copy but absent from the canonical file (ids affected)")
for (cls,k),ids in sorted(lost_ids.items()):
    print(f"  {cls:40} {k:11} {len(ids):4}")
print("== changed values")
for (cls,k,old,new),n in sorted(changed.items()): print(f"  {cls:40} {k:12} {old[:40]!r} -> {new[:40]!r}: {n} rows")
