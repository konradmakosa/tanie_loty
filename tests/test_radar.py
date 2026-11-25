import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "radar_scan",
    Path(__file__).resolve().parent.parent / "tools" / "radar_scan.py")
radar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(radar)
sys.modules["radar_scan"] = radar


ITEM = {"url": "https://www.facebook.com/groups/x/posts/1",
        "title": "Szukam tanich lotów do Oslo", "snippet": "polecacie?",
        "date": "2026-11-25", "source": "facebook"}


class TestDedup(unittest.TestCase):
    def test_seen_urls_persist(self):
        with tempfile.TemporaryDirectory() as td:
            radar.DB_PATH = Path(td) / "r.sqlite"
            c = radar.db()
            c.execute("INSERT INTO seen(url,source,first_seen,scored)"
                      " VALUES(?,?,?,1)", (ITEM["url"], "facebook", "t"))
            c.commit()
            self.assertIn(ITEM["url"], radar.seen_urls(c))
            c.close()


class TestScoreParse(unittest.TestCase):
    def _reply(self, text):
        return {"choices": [{"message": {"content": text}}]}

    @patch("radar_scan.http_json")
    def test_plain_json(self, m):
        m.return_value = self._reply(
            '{"is_relevant": true, "relevance_score": 8,'
            ' "topic_summary": "pyta o loty",'
            ' "suggested_reply": "odp"}')
        j = radar.score_item(ITEM, "k")
        self.assertTrue(j["is_relevant"])
        self.assertEqual(j["relevance_score"], 8)

    @patch("radar_scan.http_json")
    def test_json_inside_markdown(self, m):
        m.return_value = self._reply(
            '```json\n{"is_relevant": false, "relevance_score": 2,'
            ' "topic_summary": "reklama", "suggested_reply": ""}\n```')
        j = radar.score_item(ITEM, "k")
        self.assertFalse(j["is_relevant"])

    @patch("radar_scan.http_json")
    def test_garbage_returns_none(self, m):
        m.return_value = self._reply("nie wiem, co tu napisać")
        self.assertIsNone(radar.score_item(ITEM, "k"))

    @patch("radar_scan.http_json")
    def test_http_error_returns_none(self, m):
        m.side_effect = OSError("down")
        self.assertIsNone(radar.score_item(ITEM, "k"))


class TestSources(unittest.TestCase):
    @patch("radar_scan.http_json")
    def test_serper_maps_organic(self, m):
        m.return_value = {"organic": [
            {"link": "https://fb.com/groups/x/1", "title": "a",
             "snippet": "b", "date": "wczoraj"},
            {"link": "not-a-url", "title": "skip"},
        ]}
        out = radar.search_serper("q", "qdr:w", "key")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source"], "forum/www")

    def test_source_from_url(self):
        self.assertEqual(radar.source_from_url(
            "https://www.facebook.com/groups/a/1"), "facebook")
        self.assertEqual(radar.source_from_url(
            "https://www.reddit.com/r/x"), "reddit")
        self.assertEqual(radar.source_from_url(
            "https://forum.example.pl/t"), "forum/www")


class TestCoverage(unittest.TestCase):
    def test_collect_routes_and_text(self):
        with tempfile.TemporaryDirectory() as td:
            loty = Path(td) / "docs" / "loty"
            (loty / "warszawa-teneryfa").mkdir(parents=True)
            (loty / "warszawa-malaga").mkdir()
            (loty / "krakow-oslo").mkdir()
            (loty / "index").mkdir()          # bez '-' → pomijany
            with patch.object(radar, "ROOT", Path(td)):
                routes = radar.collect_routes()
            self.assertEqual(routes, {"warszawa": ["malaga", "teneryfa"],
                                      "krakow": ["oslo"]})
            txt = radar.coverage_text(routes)
            self.assertIn("warszawa: malaga, teneryfa", txt)
            self.assertIn("krakow: oslo", txt)


class TestResale(unittest.TestCase):
    def test_resale_posts_filtered(self):
        self.assertTrue(radar.is_resale(
            "Data wylotu: 22 grudnia — możliwość przepisania "
            "na 4 dowolne osoby"))
        self.assertTrue(radar.is_resale("Sprzedam bilet do Oslo"))
        self.assertTrue(radar.is_resale("opłata za zmianę nazwiska"))
        self.assertTrue(radar.is_resale("Odsprzedam 2 bilety, pilne"))

    def test_real_questions_pass(self):
        self.assertFalse(radar.is_resale(
            "Jaką wyspę polecacie na pierwszą podróż do Tajlandii?"))
        self.assertFalse(radar.is_resale(
            "Gdzie kupić tanie bilety do Oslo?"))
        # nagłówek grupy „sprzedam / kupię" sam w sobie nie jest
        # ogłoszeniem sprzedaży
        self.assertFalse(radar.is_resale(
            "Tanie bilety lotnicze / promocje / sprzedam / kupię. "
            "Polecacie jakieś lotnisko pod wyjazd?"))


class TestMergeSort(unittest.TestCase):
    def test_sort_desc_by_score(self):
        items = [{"url": "u1", "score": 5, "found_at": "a"},
                 {"url": "u2", "score": 9, "found_at": "b"}]
        items.sort(key=lambda x: (-(x.get("score") or 0),
                                  x.get("found_at") or ""))
        self.assertEqual(items[0]["url"], "u2")


if __name__ == "__main__":
    unittest.main()
