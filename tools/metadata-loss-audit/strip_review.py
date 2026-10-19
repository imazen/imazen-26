#!/usr/bin/env python3
"""Review metadata removal without serializing metadata values.

Private paths live in a caller-supplied JSON configuration, never in this tool.
Encoded inputs, native inventory details and ExifTool values stay in memory.
Output contains structural tags/ranges/hashes, field names and location flags.
"""
import argparse
import collections
import concurrent.futures as futures
import csv
import datetime
import hashlib
import html
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
CAMERA = {"1000", "1200", "1400", "1600"}
STATE_URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/"
             "TIGERweb/State_County/MapServer/0/query?")


class AuditError(Exception):
    """A fixed diagnostic code, never an input-derived error message."""


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def table(path):
    with Path(path).open(newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def public_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": "imazen26-metadata-review/1"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read()
        except Exception as error:
            if attempt == 2:
                raise AuditError("PublicReadFailed-" + type(error).__name__ + "-" +
                                 str(getattr(error, "code", "transport"))) from None


def colorado_bounds():
    # Only the state's public geometry is requested. No image position leaves
    # this process. The geometry itself is not serialized into any output.
    query = urllib.parse.urlencode({"where": "NAME='Colorado'", "outFields": "NAME",
                                   "returnGeometry": "true", "outSR": "4326", "f": "json"})
    data = public_bytes(STATE_URL + query)
    obj = json.loads(data)
    if len(obj.get("features", [])) != 1:
        raise AuditError("StateBoundaryQueryFailed")
    feature = obj["features"][0]
    if feature["attributes"]["NAME"] != "Colorado":
        raise AuditError("WrongStateBoundary")
    geom = feature["geometry"]
    reference = geom.get("spatialReference", obj.get("spatialReference", {}))
    if reference.get("wkid") != 4326:
        raise AuditError("StateBoundaryCoordinateSystem")
    points = [point for ring in geom["rings"] for point in ring]
    xs, ys = zip(*((p[0], p[1]) for p in points))
    bounds = min(xs), min(ys), max(xs), max(ys)
    if not all(math.isfinite(x) for x in bounds):
        raise AuditError("StateBoundaryNonfinite")
    # Boundary controls derive their positions in memory from the fetched
    # geometry. Neither these positions nor the bounds enter a log or file.
    left, bottom, right, top = bounds
    center = (left + right) / 2, (bottom + top) / 2
    if not inside(bounds, *center) or not inside(bounds, left, bottom):
        raise AuditError("BoundaryControlFailed")
    if inside(bounds, left - (right - left), center[1]):
        raise AuditError("BoundaryControlFailed")
    if inside(bounds, center[0], top + (top - bottom)):
        raise AuditError("BoundaryControlFailed")
    return bounds, {"url": STATE_URL + query, "sha256": digest(data),
                    "method": "inclusive state geometry bounding box", "fetched": now()}


def inside(bounds, lon, lat):
    left, bottom, right, top = bounds
    return left <= lon <= right and bottom <= lat <= top


def coordinate(value, reference=None):
    if isinstance(value, bool):
        raise AuditError("GPSValueType")
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        values = re.findall(r"[-+]?\d+(?:\.\d+)?", value)
        if not 1 <= len(values) <= 3:
            raise AuditError("GPSValueSyntax")
        numbers = [float(x) for x in values]
        result = abs(numbers[0])
        if len(numbers) >= 2:
            result += numbers[1] / 60
        if len(numbers) == 3:
            result += numbers[2] / 3600
        if numbers[0] < 0 or value.rstrip().upper().endswith(("S", "W")):
            result = -result
    else:
        raise AuditError("GPSValueType")
    if str(reference).upper() in ("S", "W", "SOUTH", "WEST"):
        result = -abs(result)
    if not math.isfinite(result):
        raise AuditError("GPSValueNonfinite")
    return result


def gps_flags(tags, bounds):
    groups = collections.defaultdict(dict)
    gps_fields = 0

    def visit(obj, path=()):
        nonlocal gps_fields
        if isinstance(obj, dict):
            for key, value in obj.items():
                bits = key.split(":")
                name = bits[-1]
                if name.startswith("GPS"):
                    gps_fields += 1
                if name in ("GPSLatitude", "GPSLongitude", "GPSLatitudeRef", "GPSLongitudeRef"):
                    groups[path + tuple(bits[:-1])][name] = value
                if isinstance(value, (dict, list)):
                    visit(value, path + (key,))
        elif isinstance(obj, list):
            for i, value in enumerate(obj):
                visit(value, path + (str(i),))

    visit(tags)
    results = []
    incomplete = 0
    for fields in groups.values():
        if "GPSLatitude" not in fields and "GPSLongitude" not in fields:
            continue
        if not {"GPSLatitude", "GPSLongitude"} <= fields.keys():
            incomplete += 1
            continue
        lat = coordinate(fields["GPSLatitude"], fields.get("GPSLatitudeRef"))
        lon = coordinate(fields["GPSLongitude"], fields.get("GPSLongitudeRef"))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise AuditError("GPSValueRange")
        results.append(inside(bounds, lon, lat))
    had = bool(results or incomplete)
    return {"had_gps": had, "inside_colorado": ("yes" if any(results) else
            "unknown" if incomplete else "no" if had else "n/a"),
            "position_carriers": len(results), "inside_carriers": sum(results),
            "outside_carriers": len(results) - sum(results),
            "incomplete_carriers": incomplete, "gps_field_count": gps_fields}


def exif(data):
    result = subprocess.run(["exiftool", "-j", "-a", "-G4:1", "-s", "-n", "-struct",
                             "-ee3", "-u", "-q", "-q", "-"], input=data,
                            capture_output=True, timeout=180)
    if result.returncode != 0:
        raise AuditError("ExifToolFailed")
    objects = json.loads(result.stdout)
    if len(objects) != 1:
        raise AuditError("ExifToolObjectCount")
    obj = objects[0]
    if any(k.endswith(":Error") for k in obj):
        raise AuditError("ExifToolInputError")
    return obj


def metadata_fields(tags):
    # Values are retained only in this temporary dictionary for equality tests.
    # Structural offsets remain visible as field-name changes to the reviewer.
    skipped = {"File", "System", "ExifTool", "Composite"}
    return {key: value for key, value in tags.items()
            if key != "SourceFile" and not skipped.intersection(key.split(":"))}


def field_diff(before, after):
    return {"removed": sorted(before.keys() - after.keys()),
            "added": sorted(after.keys() - before.keys()),
            "changed": sorted(k for k in before.keys() & after.keys() if before[k] != after[k])}


def safe_tag(tag):
    if tag == "-" or re.fullmatch(r"(?:FF[0-9A-F]{2}|0x[0-9a-fA-F]+)", tag):
        return tag
    if len(tag) == 4 and all(32 <= ord(c) < 127 for c in tag):
        return tag
    # OpenEXR/XML names may be arbitrary file content. No such name is
    # required to identify JPEG/PNG/HEIF/TIFF structural numeric tags.
    return "named-tag-" + digest(tag.encode())[:16]


def inventory(binary, data):
    result = subprocess.run([binary, "inventory", "--tsv", "-"], input=data,
                            capture_output=True, timeout=180)
    if result.returncode != 0:
        raise AuditError("InventoryProcessFailed")
    csv.field_size_limit(sys.maxsize)
    parts, parents, counts = [], [], collections.Counter()
    rows = csv.DictReader(io.StringIO(result.stdout.decode()), delimiter="\t")
    for row in rows:
        if row["kind"] == "file":
            raise AuditError("InventoryFileStatus")
        depth, start, length = int(row["depth"]), int(row["offset"]), int(row["length"])
        if min(depth, start, length) < 0 or start + length > len(data):
            raise AuditError("InventoryRange")
        kind, tag, disposition = row["kind"], safe_tag(row["tag"]), row["disposition"]
        if not re.fullmatch(r"[a-z-]+", kind) or not re.fullmatch(r"[a-z() -]+", disposition):
            raise AuditError("InventorySchema")
        parents = parents[:depth]
        parent = tuple(parents)
        identity = (kind, tag, disposition)
        key = parent + ((identity, counts[(parent, identity)]),)
        counts[(parent, identity)] += 1
        parents.append(key[-1])
        parts.append({"key": key, "depth": depth, "kind": kind, "tag": tag,
                      "disposition": disposition, "offset": start, "length": length,
                      "sha256": digest(memoryview(data)[start:start + length])})
    if not parts:
        raise AuditError("EmptyInventory")
    return parts


def part_diff(before, after):
    a, b = {p["key"]: p for p in before}, {p["key"]: p for p in after}
    out = []
    for key in sorted(a.keys() | b.keys()):
        left, right = a.get(key), b.get(key)
        if left and right and left["sha256"] == right["sha256"]:
            continue
        status = "changed" if left and right else "removed" if left else "added"
        item = left or right
        out.append({"status": status, "kind": item["kind"], "tag": item["tag"],
                    "depth": item["depth"], "disposition": item["disposition"],
                    "before_offset": left["offset"] if left else None,
                    "before_length": left["length"] if left else None,
                    "after_offset": right["offset"] if right else None,
                    "after_length": right["length"] if right else None})
    return out


def resolve_sources(config, rows):
    earlier = collections.defaultdict(list)
    for row in table(config["matches"]):
        earlier[row["id"]].append(row)
    copies = collections.defaultdict(list)
    for row in table(config["camera_copies"]):
        copies[row["id"]].append(row)
    camera = {row["id"]: row for row in table(config["camera_manifest"])}
    changes = {row["id"]: row for row in table(Path(config["staging"]) / "changes.tsv")}
    sources = {}
    for row in rows:
        cid = row["id"]
        if cid in camera:
            record = camera[cid]
            candidates = [r for r in copies[cid]
                          if r["generation"] == record["source_generation"]
                          and record["source_sha256"].startswith(r["sha16"])
                          and Path(r["path"]).is_file()]
            if not candidates:
                raise AuditError("CameraSourceMissing-" + cid)
            sources[cid] = {"path": candidates[0]["path"],
                            "sha": record["source_sha256"], "generation": "camera-original"}
        elif row["path"].split("-", 1)[0] in CAMERA:
            rank = {"snapshot-06-04": 0, "attic:imazen-26 - Copy (2)": 1, "backup-06-09": 2}
            candidates = sorted((r for r in copies[cid] if r["generation"] in rank
                                 and Path(r["path"]).is_file()), key=lambda r: rank[r["generation"]])
            if not candidates:
                raise AuditError("RawSourceMissing-" + cid)
            sources[cid] = {"path": candidates[0]["path"], "sha": candidates[0]["sha16"],
                            "generation": "raw-original"}
        else:
            candidates = [r for r in earlier[cid] if r["same_bytes"] == "1"
                          and r["candidate"] and Path(r["candidate"]).is_file()]
            change = changes[cid]
            if candidates:
                sources[cid] = {"path": candidates[0]["candidate"],
                                "sha": change["before_sha256"], "generation": "pre-pass-copy"}
            else:
                sources[cid] = {"archive_key": config["archive_prefix"] + change["path"],
                                "sha": change["before_sha256"], "generation": "pre-pass-archive"}
    return sources


def archive_client(config):
    spec = importlib.util.spec_from_file_location("originals_r2", ROOT / "scripts/r2_originals_sync.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    credentials = module.creds()
    env = dict(os.environ, AWS_ACCESS_KEY_ID=credentials["R2_ACCESS_KEY_ID"],
               AWS_SECRET_ACCESS_KEY=credentials["R2_SECRET_ACCESS_KEY"], AWS_REGION="auto")
    env.pop("AWS_SESSION_TOKEN", None)
    objects = module.listing(credentials, config["archive_bucket"], config["archive_prefix"])
    return module.endpoint(credentials), env, objects


def source_bytes(source, config, archive):
    if "path" in source:
        data = Path(source["path"]).read_bytes()
    else:
        endpoint, env, objects = archive
        key = source["archive_key"]
        cid = key.rsplit("/", 1)[-1].split("_", 1)[0]
        keys = ([key] if key in objects else []) + sorted(
            k for k in objects if k != key and k.rsplit("/", 1)[-1].startswith(cid + "_"))
        if not keys:
            raise AuditError("ArchiveSourceMissing")
        for key in keys:
            result = subprocess.run(["s5cmd", "--endpoint-url", endpoint, "cat", "--raw",
                                     "--concurrency", "1", "--part-size", "1",
                                     "s3://" + config["archive_bucket"] + "/" + key],
                                    env=env, capture_output=True, timeout=180)
            if result.returncode == 0 and digest(result.stdout).startswith(source["sha"]):
                return result.stdout
        raise AuditError("ArchiveSourceHashMismatch")
    if not digest(data).startswith(source["sha"]):
        raise AuditError("SourceHashMismatch")
    return data


def audit(row, source, config, archive, bounds):
    result = {"id": "1" + row["id"], "legacy_id": row["id"], "path": row["path"],
              "source_generation": source["generation"], "checked": now()}
    try:
        before = source_bytes(source, config, archive)
        url = config["public_base"] + urllib.parse.quote(row["path"], safe="/")
        after = public_bytes(url)
        if digest(after) != row["sha256"] or len(after) != int(row["bytes_actual"]):
            raise AuditError("PublishedHashMismatch")
        a, b = inventory(config["inventory"], before), inventory(config["inventory"], after)
        old_tags, new_tags = exif(before), exif(after)
        gps, shipped = gps_flags(old_tags, bounds), gps_flags(new_tags, bounds)
        def file_type(tags):
            return next((v for k, v in tags.items() if k.split(":")[-1] == "FileType"
                         and v in {"JPEG", "PNG", "HEIC", "DNG", "TIFF"}), "unknown")
        result.update({"status": "ok", "source_sha256": digest(before), "shipped_sha256": digest(after),
                       "before_bytes": len(before), "after_bytes": len(after), "url": url,
                       "before_format": file_type(old_tags), "after_format": file_type(new_tags),
                       "source_parts": len(a), "shipped_parts": len(b),
                       "gps": gps, "shipped_gps": shipped,
                       "parts": part_diff(a, b),
                       "fields": field_diff(metadata_fields(old_tags), metadata_fields(new_tags))})
        if gps["incomplete_carriers"]:
            result["status"], result["error"] = "error", "GPSUnclassified"
    except Exception as exc:
        result.update(status="error", error=str(exc) if isinstance(exc, AuditError) else type(exc).__name__)
    return result


def write_preserved(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text() == text:
            return
        path.rename(path.with_name(path.name + ".bak-" + str(time.time_ns())))
    path.write_text(text)


STYLE = """<style>body{font:16px system-ui;margin:2rem;max-width:1400px;color:#17212b}
table{border-collapse:collapse;width:100%;margin:1rem 0}th,td{border:1px solid #ccd5dd;padding:.4rem;text-align:left;vertical-align:top}
th{background:#eef3f7}code{overflow-wrap:anywhere}input{font:inherit;padding:.5rem;width:75%}
.error{color:#a11212}.muted{color:#536575}summary{cursor:pointer;margin:1rem 0}a{color:#075da6}</style>"""


def document(title, body):
    return "<!doctype html><html lang=en><meta charset=utf-8><title>" + html.escape(title) + \
        "</title>" + STYLE + "<h1>" + html.escape(title) + "</h1>" + body + "</html>"


def render_report(out, records, provenance, total):
    out = Path(out)
    esc = lambda value: html.escape(str(value))
    part_counts, field_counts = collections.Counter(), collections.Counter()
    index = []
    for record in sorted(records, key=lambda r: r["id"]):
        cid = record["id"]
        if "parts" not in record:
            body = '<p class=error>Audit incomplete: ' + esc(record["error"]) + "</p>"
            index.append(f'<tr class=error><td><a href="files/{cid}.html">{cid}</a></td>'
                         f'<td>{esc(record["legacy_id"])}</td><td colspan=6>{esc(record["error"])}</td></tr>')
        else:
            fields, parts, gps, shipped = record["fields"], record["parts"], record["gps"], record["shipped_gps"]
            body = (f'<p>Legacy id {esc(record["legacy_id"])} · {esc(record["path"])}</p>'
                    f'<p><a href="{esc(record["url"])}">Published original</a></p>'
                    f'<p>Source: {esc(record["source_generation"])}. '
                    f'Public bytes match the manifest SHA-256.</p>'
                    f'<p>Had GPS: {esc(gps["had_gps"])}. Inside Colorado: {esc(gps["inside_colorado"])}. '
                    f'Shipped GPS: {esc(shipped["had_gps"])}. '
                    f'Position carriers: {gps["position_carriers"]}; inside: {gps["inside_carriers"]}; '
                    f'outside: {gps["outside_carriers"]}.</p>'
                    f'<p>Format {esc(record["before_format"])} → {esc(record["after_format"])}; '
                    f'bytes {record["before_bytes"]:,} → {record["after_bytes"]:,}; '
                    f'inventory parts {record["source_parts"]:,} → {record["shipped_parts"]:,}.</p>')
            if record["status"] != "ok":
                body += '<p class=error>Classification incomplete: ' + esc(record["error"]) + "</p>"
            body += "<h2>Metadata field names</h2>"
            for status in ("removed", "changed", "added"):
                values = fields[status]
                body += f"<details open><summary>{status.title()}: {len(values)}</summary><ul>"
                for key in values:
                    field_counts[(status, key)] += 1
                    body += "<li><code>" + esc(key) + "</code></li>"
                body += "</ul></details>"
            body += "<h2>Structural part differences</h2><table><tr><th>Change<th>Kind / tag<th>Disposition<th>Depth<th>Before offset / length<th>After offset / length</tr>"
            for part in parts:
                part_counts[(part["status"], part["kind"], part["tag"])] += 1
                body += (f'<tr><td>{esc(part["status"])}<td>{esc(part["kind"])} / <code>{esc(part["tag"])}</code>'
                         f'<td>{esc(part["disposition"])}<td>{part["depth"]}'
                         f'<td>{esc(part["before_offset"])} / {esc(part["before_length"])}'
                         f'<td>{esc(part["after_offset"])} / {esc(part["after_length"])}</tr>')
            body += "</table>"
            index.append(f'<tr><td><a href="files/{cid}.html">{cid}</a></td><td>{esc(record["legacy_id"])}</td>'
                         f'<td>{esc(gps["had_gps"])}</td><td>{esc(gps["inside_colorado"])}</td>'
                         f'<td>{esc(shipped["had_gps"])}</td><td>{len(fields["removed"])}</td>'
                         f'<td>{len(fields["changed"])}</td><td>{len(parts)}</td></tr>')
        write_preserved(out / "files" / (cid + ".html"), document(cid + " — metadata removal", body))
    good = [r for r in records if r["status"] == "ok"]
    inventoried = [r for r in records if "parts" in r]
    summary = {"manifest_images": total, "inventory_comparisons": len(inventoried),
               "unclassified_gps_files": sum(bool(r["gps"]["incomplete_carriers"]) for r in inventoried), "audited": len(records), "complete": len(good),
               "errors": len(records) - len(good),
               "source_gps_files": sum(r["gps"]["had_gps"] for r in inventoried),
               "inside_colorado_files": sum(r["gps"]["inside_colorado"] == "yes" for r in inventoried),
               "shipped_gps_files": sum(r["shipped_gps"]["had_gps"] for r in inventoried)}
    body = (f'<p>{len(good):,} of {total:,} originals fully audited; {summary["errors"]} errors. '
            f'{len(inventoried):,} inventory and field comparisons are available. '
            'Each compared row includes native inventories of both inputs, an ExifTool field comparison '
            'and a live public-object SHA-256 check.</p>'
            '<p>Only field names, structural ranges, hashes and location flags are saved. '
            'Part hashes describe encoded bytes; lossless recompression can change image-data hashes. '
            'Nested parts may overlap their container. Capture positions and metadata values are not displayed.</p>'
            '<p>Inside Colorado uses the inclusive bounding box of the '
            f'<a href="{esc(provenance["boundary"]["url"])}">Census state geometry</a>. '
            'Multiple position carriers can describe the same position; “inside” is yes when any carrier is inside.</p>'
            f'<p>Source GPS: {summary["source_gps_files"]} files; inside Colorado: '
            f'{summary["inside_colorado_files"]}; shipped GPS: {summary["shipped_gps_files"]}.</p>'
            '<p><a href="summary.json">Summary and provenance</a> · '
            '<a href="part-summary.tsv">Part summary</a> · <a href="field-summary.tsv">Field summary</a></p>'
            '<input id=search placeholder="Filter by id or a table value" aria-label="Filter files">'
            '<table id=files><thead><tr><th>Export id<th>Legacy id<th>Had GPS<th>Inside Colorado<th>Shipped GPS<th>Fields removed<th>Fields changed<th>Parts different</tr></thead><tbody>'
            + "".join(index) + '</tbody></table><script>document.getElementById("search").oninput=e=>{'
            'const q=e.target.value.toLowerCase();document.querySelectorAll("#files tbody tr").forEach('
            'r=>r.hidden=!r.textContent.toLowerCase().includes(q));};</script>')
    write_preserved(out / "index.html", document("imazen-26 metadata removal review", body))
    write_preserved(out / "summary.json", json.dumps(dict(summary, provenance=provenance), indent=2) + "\n")
    for filename, header, counts in [("part-summary.tsv", ["change", "kind", "tag", "parts"], part_counts),
                                      ("field-summary.tsv", ["change", "field", "files"], field_counts)]:
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        for key, count in sorted(counts.items()):
            writer.writerow([*key, count])
        write_preserved(out / filename, stream.getvalue())
    return summary


def privacy_control():
    marker = "metadata-value-must-remain-in-memory"
    changes = field_diff({"EXIF:Artist": marker}, {"EXIF:Artist": marker + "changed"})
    if marker in json.dumps(changes) or changes != {"removed": [], "added": [], "changed": ["EXIF:Artist"]}:
        raise AuditError("FieldPrivacyControlFailed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--only", help="comma-separated legacy ids for an explicit pilot")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--render-only", action="store_true",
                        help="rebuild pages from existing value-free records without opening inputs")
    parser.add_argument("--discover", action="store_true", help="resolve source references without opening images")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    rows = sum((table(ROOT / "manifests" / (bucket + ".tsv"))
                for bucket in ("train", "validate", "test")), [])
    total = len(rows)
    if args.only:
        selected = set(args.only.split(","))
        rows = [row for row in rows if row["id"] in selected]
        if {r["id"] for r in rows} != selected:
            raise AuditError("PilotIdMissing")
    if args.render_only:
        out = Path(config["out"])
        summary = json.loads((out / "summary.json").read_text())
        records = [json.loads((out / "records" / ("1" + r["id"] + ".json")).read_text()) for r in rows]
        provenance = summary["provenance"]
        provenance["renderer_sha256"] = digest(Path(__file__).read_bytes())
        provenance["rendered"] = now()
        result = render_report(out, records, provenance, total)
        print(json.dumps(result), flush=True)
        return int(bool(result["errors"]))
    sources = resolve_sources(config, rows)
    if args.discover:
        print(json.dumps({"images": len(rows), "sources": dict(collections.Counter(
            s["generation"] for s in sources.values()))}), flush=True)
        return 0
    privacy_control()
    bounds, boundary = colorado_bounds()
    archive = archive_client(config) if any("archive_key" in s for s in sources.values()) else None
    out = Path(config["out"])
    if out.exists() and not args.resume:
        raise AuditError("OutputExistsUseResumeOrNewDirectory")
    out.mkdir(parents=True, exist_ok=True)
    provenance = {"started": now(), "tool_sha256": digest(Path(__file__).read_bytes()),
                  "inventory_sha256": digest(Path(config["inventory"]).read_bytes()),
                  "inventory_commit": config["inventory_commit"], "boundary": boundary,
                  "exiftool_version": subprocess.run(["exiftool", "-ver"], capture_output=True,
                                                       text=True, check=True).stdout.strip(),
                  "manifests_sha256": digest(b"".join((ROOT / "manifests" / (b + ".tsv")).read_bytes()
                                                        for b in ("train", "validate", "test")))}
    records, todo = [], []
    for row in rows:
        path = out / "records" / ("1" + row["id"] + ".json")
        if args.resume and path.exists():
            record = json.loads(path.read_text())
            if record.get("tool_sha256") != provenance["tool_sha256"] or record["status"] != "ok":
                raise AuditError("ResumeRecordNeedsNewOutput")
            records.append(record)
        else:
            todo.append(row)
    print(json.dumps({"started": now(), "total": len(rows), "resumed": len(records)}), flush=True)
    with futures.ThreadPoolExecutor(max_workers=config.get("workers", 2)) as pool:
        pending = {pool.submit(audit, row, sources[row["id"]], config, archive, bounds): row["id"]
                   for row in todo}
        heartbeat = 0
        while pending:
            done, _ = futures.wait(pending, timeout=5, return_when=futures.FIRST_COMPLETED)
            for future in done:
                cid = pending.pop(future)
                record = future.result()
                record["tool_sha256"] = provenance["tool_sha256"]
                write_preserved(out / "records" / ("1" + cid + ".json"),
                                json.dumps(record, indent=2, ensure_ascii=True) + "\n")
                records.append(record)
            if done or time.monotonic() - heartbeat >= 30:
                print(json.dumps({"time": now(), "complete": len(records), "total": len(rows),
                                  "errors": sum(r["status"] != "ok" for r in records)}), flush=True)
                heartbeat = time.monotonic()
    provenance["finished"] = now()
    summary = render_report(out, records, provenance, total)
    print(json.dumps(summary), flush=True)
    return int(bool(summary["errors"]))


if __name__ == "__main__":
    # A parser or subprocess exception must never print input metadata through
    # its message or traceback. Expected failures use fixed diagnostic codes.
    sys.excepthook = lambda kind, value, trace: print("fatal: " + kind.__name__, file=sys.stderr)
    try:
        sys.exit(main())
    except AuditError as error:
        print("fatal: " + str(error), file=sys.stderr)
        sys.exit(1)
