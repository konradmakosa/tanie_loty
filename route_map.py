import io
import json
import math
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT = 1000, 640
HEADER, FOOTER = 82, 38
TILE_URL = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Topo_Map/MapServer/tile/{z}/{y}/{x}")


def airport_coordinates(root=ROOT):
    path = root / "data" / "cache" / "airports.json"
    if not path.exists():
        return {}
    airports = json.loads(path.read_text(encoding="utf-8"))
    return {a["code"]: [a["coordinates"]["lat"], a["coordinates"]["lon"]]
            for a in airports if a.get("coordinates", {}).get("lat") is not None
            and a.get("coordinates", {}).get("lon") is not None}


def coordinates(value):
    if isinstance(value, str):
        value = value.split(",")
    lat, lon = map(float, value)
    if not math.isfinite(lat) or not math.isfinite(lon) or not -85 <= lat <= 85 or not -180 <= lon <= 180:
        raise ValueError("nieprawidłowe współrzędne")
    return lat, lon


def project(point, zoom):
    lat, lon = coordinates(point)
    size = 256 * 2 ** zoom
    return ((lon + 180) / 360 * size,
            (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * size)


def viewport(origin, dest, height):
    for zoom in range(9, -1, -1):
        a, b = project(origin, zoom), project(dest, zoom)
        world = 256 * 2 ** zoom
        b = (a[0] + (b[0] - a[0] + world / 2) % world - world / 2, b[1])
        if abs(b[0] - a[0]) <= WIDTH - 240 and abs(b[1] - a[1]) <= height - 160:
            break
    left = (a[0] + b[0]) / 2 - WIDTH / 2
    top = (a[1] + b[1]) / 2 - height / 2
    return zoom, left, top, [(x - left, y - top) for x, y in (a, b)]


def fetch_tile(zoom, x, y, root=ROOT):
    path = root / "data" / "cache" / "telegram_tiles" / str(zoom) / str(x) / (str(y) + ".png")
    if path.exists() and time.time() - path.stat().st_mtime < 7 * 86400:
        try:
            with Image.open(path) as image:
                if image.size == (256, 256):
                    return image.convert("RGB")
        except OSError:
            pass
    req = urllib.request.Request(TILE_URL.format(z=zoom, x=x, y=y),
                                 headers={"User-Agent": "polataj.se-route-alerts/1.0"})
    with urllib.request.urlopen(req, timeout=8) as response:
        raw = response.read(2_000_000)
    with Image.open(io.BytesIO(raw)) as image:
        if image.size != (256, 256):
            raise ValueError("nieprawidłowy kafelek")
        tile = image.convert("RGB")
    path.parent.mkdir(parents=True, exist_ok=True)
    tile.save(path, "PNG")
    return tile


def _slug(text):
    _PL = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    text = unicodedata.normalize("NFKD", text.translate(_PL))
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()


def city_photo(city, root=ROOT):
    """Miniatura z Wikipedii (Wikimedia Commons) — darmowe zdjęcie miasta."""
    cache = root / "data" / "cache" / "city_photos"
    path = cache / (_slug(city) + ".jpg")
    if path.exists() and time.time() - path.stat().st_mtime < 30 * 86400:
        try:
            return Image.open(path).convert("RGB")
        except OSError:
            pass
    agent = {"User-Agent": "polataj.se/1.0 (city thumbnails)"}
    for lang in ("pl", "en"):
        try:
            api = ("https://%s.wikipedia.org/api/rest_v1/page/summary/%s"
                   % (lang, urllib.parse.quote(city)))
            with urllib.request.urlopen(
                    urllib.request.Request(api, headers=agent), timeout=10) as r:
                data = json.load(r)
            src = (data.get("thumbnail") or {}).get("source")
            if not src:
                continue
            with urllib.request.urlopen(
                    urllib.request.Request(src, headers=agent), timeout=15) as r:
                image = Image.open(io.BytesIO(r.read(8_000_000))).convert("RGB")
            cache.mkdir(parents=True, exist_ok=True)
            image.save(path, "JPEG", quality=88)
            return image
        except (OSError, ValueError, KeyError):
            continue
    return None


def _cover(image, width, height):
    w, h = image.size
    scale = max(width / w, height / h)
    image = image.resize((round(w * scale), round(h * scale)))
    x = (image.width - width) // 2
    y = (image.height - height) // 2
    return image.crop((x, y, x + width, y + height))


def render_hit_image(deal, root=ROOT, tile_loader=None):
    """Zdjęcie miasta (góra) + mapka trasy (dół). Fallback: sama mapka."""
    if not deal.get("dest_geo"):
        return None
    map_bytes = render_route_map(deal, root=root, tile_loader=tile_loader, bare=True)
    photo = city_photo(deal["dest_city"], root)
    if photo is None:
        return map_bytes
    canvas = Image.new("RGB", (WIDTH, HEIGHT), "#0b1733")
    canvas.paste(_cover(photo, WIDTH, 390), (0, 0))
    with Image.open(io.BytesIO(map_bytes)) as m:
        canvas.paste(_cover(m.convert("RGB"), WIDTH, HEIGHT - 390), (0, 390))
    ImageDraw.Draw(canvas).line((0, 390, WIDTH, 390), fill="#0b1733", width=4)
    out = io.BytesIO()
    canvas.save(out, "PNG", optimize=True)
    return out.getvalue()


def font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/System/Library/Fonts/Supplemental/Arial.ttf",
                 "/System/Library/Fonts/Menlo.ttc"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render_route_map(deal, root=ROOT, tile_loader=None, bare=False):
    airports = airport_coordinates(root)
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    origin = airports.get(deal["origin"]) or deal.get("origin_geo") or config["ports"][deal["port"]]["geo"]
    dest = coordinates(deal["dest_geo"])
    height = HEIGHT if bare else HEIGHT - HEADER - FOOTER
    zoom, left, top, points = viewport(origin, dest, height)
    base = Image.new("RGB", (WIDTH, height), "#e3f1f4")
    loader = tile_loader or (lambda z, x, y: fetch_tile(z, x, y, root))
    count = 0
    deadline = time.monotonic() + 30
    for y in range(math.floor(top / 256), math.floor((top + height - 1) / 256) + 1):
        if not 0 <= y < 2 ** zoom:
            continue
        for x in range(math.floor(left / 256), math.floor((left + WIDTH - 1) / 256) + 1):
            count += 1
            if count > 20:
                raise ValueError("za dużo kafelków")
            if time.monotonic() > deadline:
                raise TimeoutError("przekroczony czas generowania mapy")
            tile = loader(zoom, x % (2 ** zoom), y)
            base.paste(tile, (round(x * 256 - left), round(y * 256 - top)))
    draw = ImageDraw.Draw(base)
    a, b = points
    bend = min(55, math.dist(a, b) * .12)
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1
    control = ((a[0] + b[0]) / 2 - dy / length * bend,
               (a[1] + b[1]) / 2 + dx / length * bend)
    line = [((1-t)**2*a[0] + 2*(1-t)*t*control[0] + t*t*b[0],
             (1-t)**2*a[1] + 2*(1-t)*t*control[1] + t*t*b[1])
            for t in (i / 60 for i in range(61))]
    draw.line(line, fill="white", width=10)
    draw.line(line, fill="#315fcb", width=5)
    for (x, y), label, color in zip(points, (deal["origin"], deal["dest"]), ("#147847", "#315fcb")):
        draw.ellipse((x-11, y-11, x+11, y+11), fill=color, outline="white", width=3)
        text_width = draw.textlength(label, font=font(20))
        label_x = max(8, min(WIDTH - text_width - 24, x - text_width / 2 - 12))
        label_y = y + 18
        draw.rounded_rectangle((label_x, label_y, label_x + text_width + 24, label_y + 34),
                               radius=8, fill="#0b1733")
        draw.text((label_x + 12, label_y + 4), label, font=font(20), fill="white")
    attribution = "Tiles © Esri · Esri, TomTom, Garmin, FAO, NOAA, USGS, © OpenStreetMap contributors"
    if bare:
        draw = ImageDraw.Draw(base)
        tw = draw.textlength(attribution, font=font(11))
        draw.rounded_rectangle((6, HEIGHT - 20, 14 + tw, HEIGHT - 4), radius=4, fill=(11, 23, 51))
        draw.text((10, HEIGHT - 19), attribution, font=font(11), fill="#d1daeb")
        output = io.BytesIO()
        base.save(output, "PNG", optimize=True)
        return output.getvalue()
    image = Image.new("RGB", (WIDTH, HEIGHT), "#0b1733")
    image.paste(base, (0, HEADER))
    draw = ImageDraw.Draw(image)
    title = "%s → %s" % (deal["origin_city"], deal["dest_city"])
    size = 27
    while size > 15 and draw.textlength(title, font=font(size)) > 680:
        size -= 1
    draw.text((24, 13), title, font=font(size), fill="white")
    draw.text((24, 48), "polataj.se", font=font(17), fill="#b7c9ee")
    price = "%.0f zł" % deal["price"]
    draw.text((WIDTH - draw.textlength(price, font=font(32)) - 24, 22),
              price, font=font(32), fill="#4ade80")
    draw.text((12, HEIGHT - 26), attribution, font=font(12), fill="#d1daeb")
    output = io.BytesIO()
    image.save(output, "PNG", optimize=True)
    return output.getvalue()
