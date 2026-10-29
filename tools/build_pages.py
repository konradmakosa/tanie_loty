"""Renderuje docs/<port>/index.html z templates/app.html + config.json.
Użycie: python3 tools/build_pages.py   (zero zależności)
"""
import hashlib
import html
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote

try:
    from .social_links import social_links
except ImportError:
    from social_links import social_links

ROOT = Path(__file__).resolve().parent.parent
TPL = ROOT / "templates" / "app.html"

_PL = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def slug(s):
    s = unicodedata.normalize("NFKD", s.translate(_PL))
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()


def og_image_url():
    version = hashlib.sha256((ROOT / "docs" / "og.png").read_bytes()).hexdigest()[:12]
    return "https://polataj.se/og.png?v=" + version


def refresh_og_metadata():
    url = og_image_url()
    changed = 0
    for page in (ROOT / "docs").rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        updated = re.sub(r'https://polataj\.se/og\.png(?:\?v=[a-f0-9]+)?', url, text)
        if updated != text:
            page.write_text(updated, encoding="utf-8")
            changed += 1
    return changed


def refresh_social_links():
    for page in (ROOT / "docs").rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        if '</body>' not in text:
            continue
        nav = social_links(home=page == ROOT / "docs/index.html")
        if 'class="social-links"' in text:
            updated = re.sub(r'<nav class="social-links"[^>]*>.*?</nav>', nav, text, flags=re.S)
        elif page == ROOT / "docs/index.html":
            updated = text.replace('</div>\n<div id="map">', nav + '\n</div>\n<div id="map">', 1)
        elif '<footer>' in text:
            updated = text.replace('<footer>', nav + '\n<footer>', 1)
        elif '<div class="foot">' in text:
            updated = text.replace('<div class="foot">', nav + '\n<div class="foot">', 1)
        else:
            updated = text.replace('</body>', nav + '\n</body>', 1)
        if updated != text:
            page.write_text(updated, encoding="utf-8")


def render(tpl, p):
    out = tpl.replace("{{OG_IMAGE_URL}}", og_image_url()).replace("{{SOCIAL_LINKS}}", social_links())
    for k in ("PORT", "CITY", "CITY_GEN", "AIRPORTS_DESC", "GEO_LAT",
              "GEO_LON", "EXAMPLE_ROUTE", "CITY_SLUG", "ROUTE_LINKS", "WYKOP_SRC"):
        out = out.replace("{{%s}}" % k, str(p["__vals__"][k]))
    return out


def main(routes=None):
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if routes is None:
        from build_seo_routes import prepare_routes
        routes = prepare_routes(cfg)
    tpl = TPL.read_text(encoding="utf-8")
    refresh_og_metadata()
    for port, v in cfg["ports"].items():
        vals = {
            "PORT": port,
            "CITY": v["city"],
            "CITY_GEN": v["city_gen"],
            "AIRPORTS_DESC": v["airports_desc"],
            "GEO_LAT": "%.2f" % v["geo"][0],
            "GEO_LON": "%.2f" % v["geo"][1],
            "EXAMPLE_ROUTE": v["example_route"],
            "CITY_SLUG": slug(v["city"]),
            "WYKOP_SRC": ("https://wykop.pl/dataprovider/diggerwidget?type=normal"
                          "&url=%s&title=%s&bg=0B1733" % (
                              quote("https://polataj.se/%s/" % port, safe=""),
                              quote("Tanie loty %s | polataj.se" % v["city_gen"], safe=""))),
            "ROUTE_LINKS": "".join(
                '<a href="/loty/%s/">%s<span>od %.0f zł</span></a>'
                % (html.escape(r["slug"], quote=True),
                   html.escape(r["dest_city"]), r["min_price"])
                for r in sorted(routes, key=lambda r: r["dest_city"])
                if r["port"] == port),
        }
        v["__vals__"] = vals
        out = render(tpl, v)
        if re.search(r"\{\{[A-Z_]+\}\}", out):
            raise SystemExit("nierozwiązany placeholder w %s" % port)
        dest = ROOT / "docs" / port / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(out, encoding="utf-8")
        print("%s → %s (%d B)" % (port, dest, len(out.encode())))
    refresh_social_links()


if __name__ == "__main__":
    main()
