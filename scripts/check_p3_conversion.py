#!/usr/bin/env python3
"""Check Adobe RGB→Display P3 against matrix math and LittleCMS on the old PNG samples."""
import argparse
import csv
import json
import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms

from colour_oracle import TO_XYZ


def table(path):
    with path.open() as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("previous", type=Path)
    args = parser.parse_args()
    previous = {r["id"]: r for r in table(args.previous / "report.tsv") if r["layer"] == "png-p3"}
    results = []
    for row in table(args.candidate / "report.tsv"):
        if row["layer"] != "png-p3":
            continue
        old = previous[row["id"]]
        if old["colour"] != "adobe-rgb" or row["colour"] != "display-p3":
            raise ValueError("conversion does not identify Adobe RGB→Display P3")
        source = args.previous / old["path"]
        output = args.candidate / row["path"]
        with Image.open(source) as image:
            values = np.asarray(image.convert("RGB")).astype(np.float64) / 255
        with Image.open(output) as image:
            ours = np.asarray(image.convert("RGB")).astype(np.int16)
        linear = values ** (563 / 256)
        transformed = linear @ (np.linalg.inv(TO_XYZ["display-p3"]) @ TO_XYZ["adobe-rgb"]).T
        clipped = np.clip(transformed, 0, 1)
        textbook = np.round(np.where(clipped <= .0031308, 12.92 * clipped,
                                     1.055 * clipped ** (1 / 2.4) - .055) * 255).astype(np.int16)
        # Disable LittleCMS's interpolation optimization so this is a direct ICC transform.
        with Image.open(source) as original, Image.open(output) as converted:
            transform = ImageCms.buildTransformFromOpenProfiles(
                ImageCms.ImageCmsProfile(io.BytesIO(original.info["icc_profile"])),
                ImageCms.ImageCmsProfile(io.BytesIO(converted.info["icc_profile"])),
                "RGB", "RGB", renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
                flags=ImageCms.Flags.NOOPTIMIZE)
            lcms = np.asarray(ImageCms.applyTransform(original.convert("RGB"), transform)).astype(np.int16)
        result = {"id": row["id"], "clipped_pixels": int(row["clipped"]),
                  "textbook_max_error": int(np.abs(ours - textbook).max()),
                  "littlecms_max_error": int(np.abs(ours - lcms).max()),
                  "samples": int(ours.size)}
        if result["textbook_max_error"] > 1 or result["littlecms_max_error"] > 1:
            raise ValueError(result)
        results.append(result)
        print(json.dumps(result), flush=True)
    if {r["id"] for r in results} != {"13005", "13006"}:
        raise ValueError("expected both Adobe RGB sources")
    with (args.candidate / "colour-conversion-check.json").open("x") as stream:
        stream.write(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
