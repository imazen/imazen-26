#!/usr/bin/env python3
"""Check a deployed copy of the v4 review site in headless Chromium.

    uvx --with playwright python scripts/check_v4_review_site.py <site-url> --chrome <chrome binary>

Loads the page, counts the grid's tiles against data/index.json, opens the viewer on the first
image that has a full-resolution pack and switches it to full resolution, saves the hash file
through the page's download button and compares it with the parts the site serves, and fails on
any page error, console error, failed request or HTTP status of 400 or more.
"""
import argparse
import csv
import hashlib
import io
import json
import sys
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright


def fetch(url):
    # Cloudflare refuses Python's default user agent.
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "imazen-26-site-check"})).read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="the site's index URL (…/index.html or …/)")
    ap.add_argument("--chrome", required=True, help="the Chromium or Chrome binary to drive")
    ap.add_argument("--shots", default="", help="directory for screenshots of the grid and the viewer")
    a = ap.parse_args()
    base = a.url.rsplit("/", 1)[0] + "/"
    idx = json.loads(fetch(base + "data/index.json"))
    images = idx["images"]
    zoom = next(i for i, m in enumerate(images) if m.get("z"))
    expect = b"".join(fetch(base + f) for f in idx["hashesFiles"])
    try:
        fetch(base + "data/no-such-file.json")
        missing = "200"
    except urllib.error.HTTPError as e:
        missing = str(e.code)
    problems = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=a.chrome, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        page.on("pageerror", lambda e: problems.append(f"page error: {e}"))
        page.on("console", lambda m: problems.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
        page.on("requestfailed", lambda r: problems.append(f"request failed: {r.url} ({r.failure})"))
        page.on("response", lambda r: problems.append(f"HTTP {r.status}: {r.url}") if r.status >= 400 else None)
        page.goto(a.url, wait_until="networkidle", timeout=180_000)
        tiles = page.locator(".tile").count()
        store = page.locator("#store").inner_text()
        if a.shots:
            page.screenshot(path=f"{a.shots}/grid.png")
        m = images[zoom]
        page.fill("#q", m["id"])
        page.wait_for_timeout(500)
        page.locator(".tile").first.click()
        page.wait_for_function("() => { const i = document.getElementById('vimg'); return i.complete && i.naturalWidth > 0; }", timeout=60_000)
        preview_w = page.evaluate("document.getElementById('vimg').naturalWidth")
        page.click("#vfull")
        page.wait_for_function(f"() => document.getElementById('vimg').naturalWidth === {m['w']}", timeout=120_000)
        full_w = page.evaluate("document.getElementById('vimg').naturalWidth")
        page.click("#vinfo")
        page.wait_for_timeout(1000)
        panel = page.evaluate("document.getElementById('viewer').innerText.length")
        if a.shots:
            page.screenshot(path=f"{a.shots}/viewer.png")
        page.click("#vclose")
        with page.expect_download(timeout=180_000) as d:
            page.click("#dl")
        got = open(d.value.path(), "rb").read()
        browser.close()
    print(f"tiles {tiles} of {len(images)} images; marks: {store!r}")
    print(f"viewer on {m['id']}: preview {preview_w} px wide, full resolution {full_w} of {m['w']} px; panel {panel} characters")
    print(f"hash download: {len(got):,} bytes, sha256 {hashlib.sha256(got).hexdigest()[:16]}, "
          f"{'equal to' if got == expect else 'DIFFERENT FROM'} the {len(idx['hashesFiles'])} served parts")
    print(f"a missing path answers HTTP {missing}")
    identities, duplicates = set(), set()
    lines = (line for line in io.StringIO(got.decode("utf-8")) if not line.startswith("#"))
    for row in csv.DictReader(lines, delimiter="\t"):
        identity = (row["path"], row["decoder"])
        if identity in identities:
            duplicates.add(identity)
        identities.add(identity)
    print(f"hash download identities: {len(identities):,} unique, {len(duplicates):,} duplicated")
    if duplicates:
        problems.append(f"{len(duplicates)} duplicate path/decoder identities in the hash download")
    if missing != "404":
        problems.append(f"a missing path answers HTTP {missing}, not 404")
    if tiles != len(images):
        problems.append(f"{tiles} tiles for {len(images)} images")
    if got != expect:
        problems.append("the downloaded hash file differs from the served parts")
    for x in problems:
        print("PROBLEM", x)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
