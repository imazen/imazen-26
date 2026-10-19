#!/usr/bin/env python3
"""Inventory an explicit corpus route list without writing native metadata details.

Input TSV: id, layer, path (absolute), sha256. Output directories must be new.
Each route is checked even when another route fails. Labels are limited to the
fixed allow-list prefixes; arbitrary native labels/details remain in memory.
"""
import argparse
import collections
import concurrent.futures as futures
import csv
import json
from pathlib import Path
import sys

import strip_review as review


def check(row, binary, allow):
    try:
        data = Path(row["path"]).read_bytes()
        if review.digest(data) != row["sha256"]:
            raise review.AuditError("RouteHashMismatch")
        parts = review.inventory(binary, data, tuple(w["label_prefix"] for w in allow))
        ext = Path(row["path"]).suffix.lower().lstrip(".")
        fmt = "jpg" if ext == "jpeg" else ext
        unknown = 0
        for part in parts:
            if part["disposition"] != "unknown":
                continue
            if not any(w["format"] == fmt and w["kind"] == part["kind"]
                       and w["tag"] == part["tag"]
                       and part["label"].startswith(w["label_prefix"]) for w in allow):
                unknown += 1
        return parts, "UnknownParts" if unknown else "ok", unknown
    except Exception as error:
        return [], str(error) if isinstance(error, review.AuditError) else type(error).__name__, 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("list")
    parser.add_argument("out")
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--inventory-commit", required=True)
    parser.add_argument("--allowlist", default=str(review.ROOT / "manifests/inventory_allowlist.tsv"))
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    rows = review.table(args.list)
    keys = [(r["layer"], r["path"]) for r in rows]
    if not rows or len(keys) != len(set(keys)):
        raise review.AuditError("EmptyOrDuplicateRouteList")
    if not 1 <= args.workers <= 8:
        raise review.AuditError("WorkerCount")
    allow = review.table(args.allowlist)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    provenance = {"started": review.now(), "list_sha256": review.digest(Path(args.list).read_bytes()),
                  "tool_sha256": review.digest(Path(__file__).read_bytes()),
                  "parser_sha256": review.digest(Path(review.__file__).read_bytes()),
                  "inventory_sha256": review.digest(Path(args.inventory).read_bytes()),
                  "inventory_commit": args.inventory_commit,
                  "allowlist_sha256": review.digest(Path(args.allowlist).read_bytes())}
    counts = collections.Counter()
    failures = collections.Counter()
    columns = ["file", "depth", "kind", "offset", "length", "tag", "label", "disposition", "detail"]
    with (out / "inventory.tsv").open("w", newline="") as stream, \
            (out / "routes.tsv").open("w", newline="") as statuses:
        writer = csv.DictWriter(stream, columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        state = csv.writer(statuses, delimiter="\t", lineterminator="\n")
        state.writerow(["id", "layer", "path", "sha256", "parts", "unknown_parts", "status"])
        with futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = {pool.submit(check, r, args.inventory, allow): r for r in rows}
            for index, future in enumerate(futures.as_completed(pending), 1):
                row = pending[future]
                parts, status, unknown = future.result()
                counts[row["layer"]] += 1
                if status != "ok":
                    failures[(row["layer"], status)] += 1
                state.writerow([row["id"], row["layer"], row["path"], row["sha256"],
                                len(parts), unknown, status])
                if not parts:
                    writer.writerow(dict(file=row["path"], depth=0, kind="file", offset=0,
                                         length=0, tag="-", label="", disposition="error", detail=status))
                for part in parts:
                    writer.writerow(dict(file=row["path"], depth=part["depth"], kind=part["kind"],
                                         offset=part["offset"], length=part["length"], tag=part["tag"],
                                         label=part["label"], disposition=part["disposition"], detail=""))
                stream.flush()
                statuses.flush()
                if index == 1 or index % 50 == 0 or index == len(rows):
                    print(json.dumps(dict(time=review.now(), complete=index, total=len(rows),
                                          failures=sum(failures.values()))), flush=True)
    provenance["finished"] = review.now()
    result = {"routes": len(rows), "layers": dict(counts), "failures": sum(failures.values()),
              "failure_groups": [{"layer": k[0], "error": k[1], "count": v}
                                 for k, v in sorted(failures.items())], "provenance": provenance}
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "provenance"}), flush=True)
    return int(bool(failures))


if __name__ == "__main__":
    sys.excepthook = lambda kind, value, trace: print("fatal: " + kind.__name__, file=sys.stderr)
    try:
        sys.exit(main())
    except review.AuditError as error:
        print("fatal: " + str(error), file=sys.stderr)
        sys.exit(1)
