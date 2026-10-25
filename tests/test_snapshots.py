import gzip
import json
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from ingest import snapshot_payload, post_snapshot


ROOT = Path(__file__).resolve().parent.parent
PHP = ("/opt/homebrew/bin/php" if
       Path("/opt/homebrew/bin/php").exists() else shutil.which("php"))


class SnapshotApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PHP:
            raise unittest.SkipTest("PHP unavailable")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.server = Path(cls.tmp.name)
        for name in ("db.php", "ports.php", "snapshot.php", "schema.sql"):
            shutil.copy(ROOT / "server" / name, cls.server / name)
        (cls.server / "config.php").write_text(
            "<?php return ['DB_DSN' => 'sqlite:%s', "
            "'INGEST_KEY' => 'test-key', "
            "'ALLOWED_ORIGINS' => ['https://polataj.se']];"
            % (cls.server / "deals.sqlite"), encoding="utf-8")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.base = "http://127.0.0.1:%d/snapshot.php" % port
        cls.proc = subprocess.Popen(
            [PHP, "-S", "127.0.0.1:%d" % port,
             "-t", str(cls.server)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                cls.request("?port=zwarszawy")
            except urllib.error.HTTPError:
                break
            except urllib.error.URLError:
                time.sleep(0.1)
        else:
            raise RuntimeError("PHP server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        cls.tmp.cleanup()

    @classmethod
    def request(cls, path="", payload=None, key="test-key"):
        headers = {"Origin": "https://polataj.se"}
        if payload is not None:
            headers.update({"X-Ingest-Key": key, "Content-Encoding": "gzip",
                            "Content-Type": "application/json"})
            body = gzip.compress(json.dumps(payload).encode("utf-8"))
        else:
            body = None
        req = urllib.request.Request(cls.base + path, data=body,
                                     headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.headers, json.load(resp)

    @staticmethod
    def snapshot(ts):
        tabs = {
            tab: {"generated_at": ts, "config": {"days_ahead": 120}, "deals": [
                {"id": "OW-KTW-FCO-2026-11-22", "date_in": None,
                 "offers": [{"link": "https://wizzair.com/"}]}
            ]} for tab in ("okazje", "daleko", "oneway")
        }
        return {"port": "zkatowic", "tabs": tabs}

    def test_full_snapshot_and_no_regression(self):
        with self.assertRaises(urllib.error.HTTPError) as missing:
            self.request("?port=zkatowic")
        self.assertEqual(missing.exception.code, 404)
        data = self.snapshot("2026-10-25T12:00:00+00:00")
        with self.assertRaises(urllib.error.HTTPError) as forbidden:
            self.request(payload=data, key="wrong")
        self.assertEqual(forbidden.exception.code, 401)
        status, _, result = self.request(payload=data)
        self.assertEqual((status, result["ok"]), (200, True))
        _, headers, stored = self.request("?port=zkatowic")
        self.assertEqual(headers["Access-Control-Allow-Origin"],
                         "https://polataj.se")
        self.assertEqual(stored, data["tabs"])
        older = self.snapshot("2026-10-24T12:00:00+00:00")
        self.request(payload=older)
        self.assertEqual(self.request("?port=zkatowic")[2], data["tabs"])

    def test_rejects_partial_and_unknown_port(self):
        partial = self.snapshot("2026-10-25T13:00:00+00:00")
        del partial["tabs"]["oneway"]
        with self.assertRaises(urllib.error.HTTPError) as invalid:
            self.request(payload=partial)
        self.assertEqual(invalid.exception.code, 400)
        partial["port"] = "../zkatowic"
        with self.assertRaises(urllib.error.HTTPError) as port:
            self.request(payload=partial)
        self.assertEqual(port.exception.code, 400)

    def test_real_port_snapshot_preserves_links_and_one_way(self):
        data = snapshot_payload(ROOT / "docs" / "zgdanska", "zgdanska")
        post_snapshot(self.base, "test-key", data)
        stored = self.request("?port=zgdanska")[2]
        for tab in data["tabs"]:
            self.assertEqual(stored[tab]["deals"], data["tabs"][tab]["deals"])
        self.assertTrue(any(d.get("trip") == "oneway" for d in
                            stored["oneway"]["deals"]))


if __name__ == "__main__":
    unittest.main()
