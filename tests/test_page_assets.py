import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import build_pages


class PageAssetsTest(unittest.TestCase):
    def test_image_version_tracks_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'docs').mkdir()
            image = root / 'docs' / 'og.png'
            image.write_bytes(b'first image')
            with patch.object(build_pages, 'ROOT', root):
                first = build_pages.og_image_url()
                self.assertEqual(first, build_pages.og_image_url())
                self.assertTrue(first.endswith(hashlib.sha256(b'first image').hexdigest()[:12]))
                image.write_bytes(b'new image')
                self.assertNotEqual(first, build_pages.og_image_url())

    def test_home_metadata_is_updated_without_stacking_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'docs').mkdir()
            (root / 'docs' / 'og.png').write_bytes(b'new image')
            (root / 'config.json').write_text(json.dumps({'ports': {}}))
            template = root / 'template.html'
            template.write_text('')
            home = root / 'docs' / 'index.html'
            home.write_text('<meta property="og:image" content="https://polataj.se/og.png?v=deadbeef">')
            with patch.object(build_pages, 'ROOT', root), patch.object(build_pages, 'TPL', template):
                build_pages.main([])
                self.assertIn(build_pages.og_image_url(), home.read_text())
                first = home.read_text()
                build_pages.main([])
                self.assertEqual(home.read_text(), first)
                self.assertEqual(first.count('?v='), 1)


if __name__ == '__main__':
    unittest.main()
