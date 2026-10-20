#!/usr/bin/env python3
"""Publish the approved two-file P3 conversion as forward commits and a new pinned catalogue."""
import argparse
import csv
import io
import json
import shutil
import subprocess
from pathlib import Path

import publish_corpus as publication
from prepare_publication import DECODING, special_card

VERSION = "2026.10.20"
NAME = "imazen-26-jxl-p3"
IDS = {"13005", "13006"}


def show(repo, branch, name):
    return subprocess.check_output(["git", "show", f"origin/{branch}:{name}"], cwd=repo).decode()


def table(text):
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))


def write(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("render", type=Path)
    parser.add_argument("repository", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    repo = args.repository
    changes = {r["id"]: r for r in publication.rows(args.render / "manifests/jxl-p3.tsv") if r["id"] in IDS}
    if set(changes) != IDS or any(r["colour"] != "display-p3" or r["form"] != "lossless" for r in changes.values()):
        raise ValueError("the canonical replacements are not lossless Display P3")
    before = {branch: publication.run(["git", "rev-parse", f"origin/{branch}"], cwd=repo, capture=True)
              for branch in ["train", "validate", "test", "main"]}
    if args.evidence.exists():
        raise ValueError("publication evidence exists; inspect its saved receipts")
    args.evidence.mkdir(parents=True)
    publication.save(args.evidence / "before.json", before)
    staged = {}
    for branch in before:
        rows = table(show(repo, branch, "manifest.tsv"))
        for row in rows:
            if row["id"] in changes and row["layer"] == "jxl-p3" and row["form"] != "hdr-pq":
                new = changes[row["id"]]
                if row["colour"] != "adobe-rgb" or row["path"] != new["path"].removeprefix("jxl-p3/"):
                    raise ValueError("unexpected prior published colour/path")
                for field in new:
                    if field in row and field not in ["path", "source", "license"]:
                        row[field] = new[field]
        dest = args.evidence / branch
        dest.mkdir()
        write(dest / "manifest.tsv", rows)
        (dest / "README.md").write_text(special_card(NAME, "jxl-p3", rows, VERSION))
        (dest / "DECODING.md").write_text(DECODING)
        citation = show(repo, branch, "CITATION.cff").replace("2026.10.19", VERSION).replace("2026-10-19", "2026-10-20")
        (dest / "CITATION.cff").write_text(citation)
        changelog = show(repo, branch, "CHANGELOG.md")
        marker = "## [2026.10.19]"
        changelog = changelog.replace(marker, f"## [{VERSION}] - 2026-10-20\n\n### Changed\n\n- Convert Adobe RGB sources 13005 and 13006 to Display P3 with relative colorimetric intent and gamut clipping; encode their converted samples losslessly. Originals and sRGB files are unchanged.\n\n" + marker)
        (dest / "CHANGELOG.md").write_text(changelog)
        staged[branch] = rows
    publication.save(args.evidence / "plan.json", {"version": VERSION, "before": before,
                     "files": len(staged["main"]), "bytes": sum(int(r["bytes"]) for r in staged["main"])})
    if not args.apply:
        return
    if publication.run(["jj", "diff", "--summary"], cwd=repo, capture=True):
        raise ValueError("publication checkout has unrelated changes")
    refs = {}
    for branch in ["train", "validate", "test", "main"]:
        publication.run(["jj", "new", f"{branch}@origin", "-m", "fix: convert Adobe RGB sources to Display P3"], cwd=repo)
        for name in ["manifest.tsv", "README.md", "DECODING.md", "CITATION.cff", "CHANGELOG.md"]:
            shutil.copyfile(args.evidence / branch / name, repo / name)
        if branch != "main":
            for row in staged[branch]:
                if row["id"] in changes and row["layer"] == "jxl-p3":
                    source = args.render / changes[row["id"]]["path"]
                    if publication.digest(source) != row["sha256"]:
                        raise ValueError("source differs from staged publication")
                    shutil.copyfile(source, repo / row["path"])
        else:
            with (repo / "BRANCHES.tsv").open("w") as stream:
                stream.write("branch\tcommit\tmanifest_sha256\n")
                for bucket in ["train", "validate", "test"]:
                    stream.write(f"{bucket}\t{refs[bucket]}\t{publication.digest(args.evidence / bucket / 'manifest.tsv')}\n")
        publication.run(["python3", "tools/validate.py", "--branch", branch], cwd=repo)
        refs[branch] = publication.push(repo, branch)
        publication.save(args.evidence / (branch + ".pushed.json"), {"commit": refs[branch]})
    publication.save(args.evidence / "published.json", {"version": VERSION, "refs": refs})
    print(json.dumps({"version": VERSION, "refs": refs}), flush=True)


if __name__ == "__main__":
    main()
