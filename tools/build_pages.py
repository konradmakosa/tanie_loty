"""Renderuje docs/<port>/index.html z templates/app.html + config.json.
Użycie: python3 tools/build_pages.py   (zero zależności)
"""
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TPL = ROOT / "templates" / "app.html"

_PL = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def slug(s):
    s = unicodedata.normalize("NFKD", s.translate(_PL))
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()


def render(tpl, p):
    out = tpl
    for k in ("PORT", "CITY", "CITY_GEN", "AIRPORTS_DESC", "GEO_LAT",
              "GEO_LON", "EXAMPLE_ROUTE", "CITY_SLUG"):
        out = out.replace("{{%s}}" % k, str(p["__vals__"][k]))
    return out


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    tpl = TPL.read_text(encoding="utf-8")
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
        }
        v["__vals__"] = vals
        out = render(tpl, v)
        if re.search(r"\{\{[A-Z_]+\}\}", out):
            raise SystemExit("nierozwiązany placeholder w %s" % port)
        dest = ROOT / "docs" / port / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(out, encoding="utf-8")
        print("%s → %s (%d B)" % (port, dest, len(out.encode())))


if __name__ == "__main__":
    main()
