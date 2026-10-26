"""Generuje ikony polataj.se do docs/: zaokrąglony granatowy kwadrat
z zielonym „lotniskowym" symbolem (pierścień + kropka).

Paleta jak w og.png/mapie: tło #0b1733, zieleń #4ade80, błękit #7aa2ff.
Użycie: python3 tools/make_icons.py   (wymaga Pillow)
"""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

BG = (11, 23, 51)          # #0b1733
GREEN = (74, 222, 128)     # #4ade80
BLUE = (122, 162, 255)     # #7aa2ff
S = 1024                   # rysujemy duże, potem LANCZOS

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#0b1733"/>
  <circle cx="32" cy="32" r="19" fill="none" stroke="#4ade80" stroke-width="7"/>
  <circle cx="32" cy="32" r="7" fill="#4ade80"/>
</svg>
"""


def draw_symbol(dr, s, inset=0.0):
    """Siatka + pierścień + kropka; rysuje w kwadracie s×s."""
    cx = cy = s / 2
    # pierścień ~12% boku, promień ~30% boku
    r = s * .30
    w = int(s * .12)
    dr.ellipse([cx - r, cy - r, cx + r, cy + r],
               outline=GREEN + (255,), width=w)
    # kropka ~22% boku
    r2 = s * .11
    dr.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill=GREEN + (255,))


def make(size, rounded=True):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    if rounded:
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, S - 1, S - 1], radius=S * .22, fill=255)
        bg = Image.new("RGBA", (S, S), BG + (255,))
        img.paste(bg, (0, 0), mask)
    else:
        img.paste(BG + (255,), [0, 0, S, S])
    draw_symbol(ImageDraw.Draw(img), S)
    return img.resize((size, size), Image.LANCZOS)


def main():
    (DOCS / "favicon.svg").write_text(SVG, encoding="utf-8")
    # .ico z kilkoma rozmiarami (Windows czyta od razu RGBA)
    ico = make(48)
    ico.save(DOCS / "favicon.ico", format="ICO",
             sizes=[(16, 16), (32, 32), (48, 48)])
    make(180, rounded=False).save(DOCS / "apple-touch-icon.png")
    make(192).save(DOCS / "icon-192.png")
    make(512).save(DOCS / "icon-512.png")
    for f in ["favicon.svg", "favicon.ico", "apple-touch-icon.png",
              "icon-192.png", "icon-512.png"]:
        print("docs/%s" % f)


if __name__ == "__main__":
    main()
