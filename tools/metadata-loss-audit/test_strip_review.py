"""Controls for value-free reporting, including incomplete source metadata."""
import unittest
from unittest.mock import patch

import strip_review as review


class ReviewTests(unittest.TestCase):
    def test_field_changes_never_include_values(self):
        private = "private-value-sentinel"
        changes = review.field_diff(
            {"EXIF:Artist": private, "XMP:Title": private},
            {"EXIF:Artist": private + "changed", "XMP:Rights": private},
        )
        self.assertEqual(changes, {"removed": ["XMP:Title"],
                                   "changed": ["EXIF:Artist"], "added": ["XMP:Rights"]})
        self.assertNotIn(private, str(changes))

    def test_incomplete_gps_keeps_inventory_and_counts(self):
        flags = {"had_gps": True, "inside_colorado": "unknown", "position_carriers": 0,
                 "inside_carriers": 0, "outside_carriers": 0, "incomplete_carriers": 1}
        record = {"id": "10001", "legacy_id": "0001", "path": "source.jpg",
                  "status": "error", "error": "GPSUnclassified", "source_generation": "test",
                  "url": "https://example.org/source.jpg", "gps": flags,
                  "shipped_gps": dict(flags, had_gps=False),
                  "before_format": "JPEG", "after_format": "JPEG",
                  "before_bytes": 80, "after_bytes": 60, "source_parts": 3, "shipped_parts": 2,
                  "fields": {"removed": ["GPS:GPSLongitude"], "added": [], "changed": []},
                  "parts": [{"status": "removed", "kind": "metadata", "tag": "FFE1",
                             "depth": 0, "disposition": "metadata", "before_offset": 2,
                             "before_length": 20, "after_offset": None, "after_length": None}]}
        output = {}
        with patch.object(review, "write_preserved", side_effect=lambda p, s: output.update({str(p): s})):
            result = review.render_report("review", [record],
                                          {"boundary": {"url": "https://example.org/state"}}, 1)
        self.assertEqual(result["complete"], 0)
        self.assertEqual(result["inventory_comparisons"], 1)
        self.assertEqual(result["unclassified_gps_files"], 1)
        self.assertEqual(result["source_gps_files"], 1)
        self.assertIn("Classification incomplete", output["review/files/10001.html"])
        self.assertIn("GPS:GPSLongitude", output["review/files/10001.html"])
        self.assertIn("FFE1", output["review/part-summary.tsv"])


if __name__ == "__main__":
    unittest.main()
