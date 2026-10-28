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

    def test_all_existing_pages_get_the_current_image_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            docs = root / 'docs'
            old_route = docs / 'loty' / 'old-route' / 'index.html'
            old_route.parent.mkdir(parents=True)
            (docs / 'og.png').write_bytes(b'new image')
            (docs / 'index.html').write_text('<meta property="og:image" content="https://polataj.se/og.png">')
            old_route.write_text('<meta name="twitter:image" content="https://polataj.se/og.png?v=deadbeef">')
            untouched = docs / 'other.html'
            untouched.write_text('<title>Other</title>')
            with patch.object(build_pages, 'ROOT', root):
                self.assertEqual(build_pages.refresh_og_metadata(), 2)
                self.assertIn(build_pages.og_image_url(), old_route.read_text())
                self.assertIn(build_pages.og_image_url(), (docs / 'index.html').read_text())
                self.assertEqual(untouched.read_text(), '<title>Other</title>')
                self.assertEqual(build_pages.refresh_og_metadata(), 0)

    def test_social_links_are_accessible_and_refresh_without_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'docs').mkdir()
            home = root / 'docs/index.html'
            home.write_text('<div class="hdr"></div>\n<div id="map"></div></body>')
            with patch.object(build_pages, 'ROOT', root):
                build_pages.refresh_social_links()
                first = home.read_text()
                build_pages.refresh_social_links()
            self.assertEqual(home.read_text(), first)
            self.assertEqual(first.count('class="social-links"'), 1)
            for url in ('https://t.me/polataj_se', 'https://t.me/polatajsebot',
                        'https://www.facebook.com/1393638090497267'):
                self.assertIn(url, first)
            self.assertIn('aria-label=', first)
            self.assertIn('pointer-events:auto', first)

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
