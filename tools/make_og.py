#!/usr/bin/env python3
"""Generuje docs/og.png (1200x630) — grafika podglądu linku (Open Graph).
Styl: techniczna mapa lotnicza, jak na stronie głównej.
Użycie: python3 tools/make_og.py"""

import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "og.png"
W, H = 1200, 630

# granica Polski — tools/poland_border.txt (projekcja x=(lon-19)*cos52,
# y=-(lat-52); y rośnie na południe, czyli w dół obrazka)
D = (ROOT / "tools" / "poland_border.txt").read_text(encoding="utf-8").strip()

PORTS = [  # iata, x, y (jak na mapie)
    ("WAW", 1.21114, -0.1657),
    ("KRK", 0.483201, 1.9223),
    ("GDN", -0.328661, -2.3776),
    ("POZ", -1.33835, -0.421),
    ("WRO", -1.30171, 0.8973),
    ("KTW", 0.049256, 1.5257),
]
# kilka tras pokazowych: z lotniska -> kierunek (też w tej projekcji)
ROUTES = [
    ("WAW", -2.6, -2.6),   # Londyn
    ("WAW", -1.6, 2.9),    # Barcelona
    ("KRK", 0.9, 2.9),     # Rzym
    ("GDN", -0.9, -2.9),   # Sztokholm
    ("WAW", 3.2, 0.9),     # Kijów/strona wschodnia
    ("KTW", 1.9, 2.9),     # Ateny
]

def font(path, size, index=0):
    return ImageFont.truetype(path, size, index=index)

MONO = "/System/Library/Fonts/Menlo.ttc"
TEXT = "/System/Library/Fonts/SFNS.ttf"

# obszar mapy: x -3.3..3.45, y -3.14..3.28 — skala do prawej części obrazka
MX0, MX1, MY0, MY1 = -3.3, 3.45, -3.14, 3.28
MAP_BOX = (660, 40, 1160, 600)  # px: lewo, góra, prawo, dół
sc = min((MAP_BOX[2] - MAP_BOX[0]) / (MX1 - MX0),
         (MAP_BOX[3] - MAP_BOX[1]) / (MY1 - MY0))
cx0 = MAP_BOX[0] + ((MAP_BOX[2] - MAP_BOX[0]) - sc * (MX1 - MX0)) / 2
cy0 = MAP_BOX[1] + ((MAP_BOX[3] - MAP_BOX[1]) - sc * (MY1 - MY0)) / 2

def px(x, y):
    return cx0 + (x - MX0) * sc, cy0 + (y - MY0) * sc

img = Image.new("RGB", (W, H))
dr = ImageDraw.Draw(img)

# tło — pionowy gradient jak na stronie
top, mid, bot = (11, 23, 51), (18, 28, 52), (23, 28, 43)
for y in range(H):
    t = y / H
    c = tuple(int(top[i] + (mid[i] - top[i]) * t * 2) if t < .5
              else int(mid[i] + (bot[i] - mid[i]) * (t - .5) * 2)
              for i in range(3))
    dr.line([(0, y), (W, y)], fill=c)

# siatka 1° jak na mapie
grid = (122, 162, 255, 35)
for gx in [x / 10 for x in range(-33, 35, 6)]:
    a, b = px(gx, MY0), px(gx, MY1)
    dr.line([a, b], fill=(30, 40, 70), width=1)
for gy in [y / 10 for y in range(-31, 33, 10)]:
    a, b = px(MX0, gy), px(MX1, gy)
    dr.line([a, b], fill=(30, 40, 70), width=1)

# kontur Polski
pts = [(float(x), float(y)) for x, y in
       re.findall(r"[ML](-?\d+\.?\d*),(-?\d+\.?\d*)", D)]
poly = [px(x, y) for x, y in pts]
dr.polygon(poly, fill=(36, 52, 96))
dr.line(poly + [poly[0]], fill=(140, 160, 210), width=2)

# trasy przerywane z lotnisk
airports = {p[0]: (p[1], p[2]) for p in PORTS}
for src, tx, ty in ROUTES:
    x1, y1 = px(*airports[src])
    x2, y2 = px(tx, ty)
    seg = 14
    dx, dy = (x2 - x1) / seg, (y2 - y1) / seg
    for i in range(0, seg, 2):
        dr.line([(x1 + dx * i, y1 + dy * i),
                 (x1 + dx * (i + .8), y1 + dy * (i + .8))],
                fill=(122, 162, 255), width=2)

f_iata = font(MONO, 17)
f_city = font(MONO, 13)
f_title = font(MONO, 84)
f_sub = font(MONO, 30)
f_small = font(MONO, 22)

# porty — zielone znaczniki jak na mapie
green = (74, 222, 128)
for iata, x, y in PORTS:
    cx, cy = px(x, y)
    dr.ellipse([cx - 15, cy - 15, cx + 15, cy + 15],
               outline=(*green,), width=2)
    dr.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=green)
    tw = dr.textlength(iata, font=f_iata)
    dr.text((cx - tw / 2, cy + 18), iata, font=f_iata, fill=green)

# teksty po lewej
dr.text((60, 150), "polataj.se", font=f_title, fill=(232, 234, 240))
dr.text((63, 270), "Okazje na loty w obie strony", font=f_sub,
        fill=(154, 163, 178))
dr.text((63, 320), "z lotnisk w całej Polsce", font=f_sub,
        fill=(154, 163, 178))
dr.text((63, 400), "odświeżane co 6 h", font=f_small, fill=green)
dr.text((63, 436), "WAW · KRK · GDN · POZ · WRO · KTW", font=f_small,
        fill=(122, 162, 255))

img.save(OUT, "PNG")
print("zapisano", OUT, img.size)
