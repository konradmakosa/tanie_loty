import json
import tempfile
import unittest
from pathlib import Path

import ingest


class SnapshotPayloadTest(unittest.TestCase):
    def test_all_three_tabs_are_required_and_share_generation_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            port_dir = Path(tmp)
            self.assertRaises(FileNotFoundError, ingest.snapshot_payload,
                              port_dir, "zwarszawy")
            for filename in ("deals", "far", "oneway"):
                (port_dir / (filename + ".json")).write_text(json.dumps({
                    "generated_at": "2026-10-25T12:00:00+00:00",
                    "config": {"days_ahead": 120},
                    "deals": [{"offers": [{"link": "https://wizzair.com/"}]}]
                }), encoding="utf-8")
            payload = ingest.snapshot_payload(port_dir, "zwarszawy")
            self.assertEqual(set(payload["tabs"]), {"okazje", "daleko", "oneway"})
            self.assertEqual(payload["tabs"]["oneway"]["deals"][0]["offers"][0]["link"],
                             "https://wizzair.com/")
            data = json.loads((port_dir / "far.json").read_text())
            data["generated_at"] = "2026-10-24T12:00:00+00:00"
            (port_dir / "far.json").write_text(json.dumps(data))
            self.assertRaises(ValueError, ingest.snapshot_payload,
                              port_dir, "zwarszawy")


if __name__ == "__main__":
    unittest.main()
