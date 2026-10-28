import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from route_map import HEADER, FOOTER, HEIGHT, WIDTH, coordinates, fetch_tile, render_route_map, viewport


class RouteMapTest(unittest.TestCase):
    def test_viewport_fits_routes_including_dateline(self):
        for start, end in [([52.17, 20.97], [60.19, 11.1]),
                           ([50, 179], [51, -179]), ([52, 21], [52, 21])]:
            zoom, _, _, points = viewport(start, end)
            self.assertTrue(0 <= zoom <= 9)
            for x, y in points:
                self.assertTrue(0 < x < WIDTH)
                self.assertTrue(0 < y < HEIGHT - HEADER - FOOTER)

    def test_invalid_coordinates(self):
        for value in ['nan,10', '50,inf', '100,20', '50,200']:
            with self.assertRaises(ValueError):
                coordinates(value)

    def test_map_renders_and_uses_exact_origin_airport(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'config.json').write_text(json.dumps({
                'ports': {'zwarszawy': {'geo': [52.17, 20.97]}}}))
            cache = root / 'data' / 'cache'
            cache.mkdir(parents=True)
            (cache / 'airports.json').write_text(json.dumps([
                {'code': 'WMI', 'coordinates': {'lat': 52.45, 'lon': 20.65}}]))
            calls = []
            def tile(z, x, y):
                calls.append((z, x, y))
                return Image.new('RGB', (256, 256), '#eeeeee')
            deal = {'origin': 'WMI', 'dest': 'OSL', 'origin_city': 'Warszawa',
                    'dest_city': 'Oslo', 'port': 'zwarszawy',
                    'dest_geo': '60.19,11.1', 'price': 99}
            with patch('route_map.viewport', wraps=viewport) as bounds:
                raw = render_route_map(deal, root, tile)
            self.assertEqual(bounds.call_args.args[0], [52.45, 20.65])
            with Image.open(io.BytesIO(raw)) as image:
                self.assertEqual(image.size, (1000, 640))
                self.assertEqual(image.getpixel((0, 0)), (11, 23, 51))
            self.assertTrue(0 < len(calls) <= 20)

    def test_tile_cache_prevents_another_request(self):
        with tempfile.TemporaryDirectory() as temp:
            buffer = io.BytesIO()
            Image.new('RGB', (256, 256), 'white').save(buffer, 'PNG')
            with patch('route_map.urllib.request.urlopen') as request:
                request.return_value.__enter__.return_value.read.return_value = buffer.getvalue()
                fetch_tile(3, 4, 2, Path(temp))
                fetch_tile(3, 4, 2, Path(temp))
                self.assertEqual(request.call_count, 1)


if __name__ == '__main__':
    unittest.main()
