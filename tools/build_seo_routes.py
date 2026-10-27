#!/usr/bin/env python3
"""Statyczne strony pSEO: docs/loty/<miasto>-<miasto>/ + sitemap + robots.

Dane wejściowe: config.json (porty), docs/<port>/deals.json i far.json
(aktywne okazje), data/history.jsonl (min. cena z 30 dni).

Użycie: python3 tools/build_seo_routes.py   (zero zależności)
"""
import html
import json
import math
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
TPL = (ROOT / "templates" / "route.html").read_text(encoding="utf-8")
SITE = "https://polataj.se"
MAX_DEALS_ROWS = 15
TOP_REL = 6

MONTHS = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
          "lipiec", "sierpień", "wrzesień", "październik",
          "listopad", "grudzień"]
WEEKDAYS = ["poniedziałek", "wtorek", "środa", "czwartek",
            "piątek", "sobota", "niedziela"]

_PL = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def slug(s):
    s = unicodedata.normalize("NFKD", s.translate(_PL))
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s


def esc(s):
    return html.escape(str(s), quote=True)


def hav(lat1, lon1, lat2, lon2):
    r = math.radians
    dlat, dlon = r(lat2 - lat1), r(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(dlon / 2) ** 2)
    return 6371 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fmt_price(p):
    return ("%d" % round(p)) if p == round(p) else ("%.0f" % p)


def fmt_date(iso):
    d = datetime.strptime(iso, "%Y-%m-%d")
    return "%d.%02d" % (d.day, d.month)


def load_history():
    """min. cena z 30 dni per (iata, dest) + liczba próbek."""
    out = defaultdict(list)
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    f = ROOT / "data" / "history.jsonl"
    if not f.exists():
        return out
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("trip") == "oneway":
            continue
        try:
            ts = datetime.fromisoformat(r["ts"])
        except (KeyError, ValueError):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= cutoff:
            out[(r["origin"], r["dest"])].append(float(r["price"]))
    return out


def collect_routes(cfg):
    """(port_slug, dest_iata) -> dict trasy z dealami (deals+far, RT)."""
    routes = {}
    for port, p in cfg["ports"].items():
        deals = []
        for name in ("deals.json", "far.json"):
            f = DOCS / port / name
            if f.exists():
                deals += json.loads(f.read_text(encoding="utf-8"))["deals"]
        for d in deals:
            if not d.get("date_in"):            # tylko RT
                continue
            key = (port, d["dest"])
            r = routes.setdefault(key, {
                "port": port, "dest": d["dest"],
                "dest_city": d.get("dest_city") or d["dest"],
                "dest_country": d.get("dest_country") or "",
                "dest_geo": None, "deals": [],
            })
            if not r["dest_geo"] and d.get("dest_geo"):
                r["dest_geo"] = d["dest_geo"]
            r["deals"].append(d)
    return routes


def enrich(r, cfg, hist):
    p = cfg["ports"][r["port"]]
    deals = sorted(r["deals"], key=lambda x: x["price"])
    r["deals"] = deals
    r["min_price"] = deals[0]["price"]

    # min. cena 30 dni: historia (wszystkie IATA portu) + ceny bieżące
    hp = [x for iata in p["airports"]
          for x in hist.get((iata, r["dest"]), [])]
    r["hist_samples"] = len(hp)
    r["min_30d"] = min(hp + [d["price"] for d in deals]) if hp else None

    by_month, by_wd = {}, {}
    for d in deals:
        m = int(d["date_out"][5:7])
        by_month[m] = min(by_month.get(m, 1e9), d["price"])
        w = d.get("weekday_out")
        if w is not None:
            by_wd[w] = min(by_wd.get(w, 1e9), d["price"])
    r["cheap_months"] = [MONTHS[m - 1] for m, _ in
                         sorted(by_month.items(), key=lambda kv: kv[1])[:2]]
    r["cheap_wd"] = [WEEKDAYS[w] for w, _ in
                     sorted(by_wd.items(), key=lambda kv: kv[1])[:2]]

    r["airlines"] = sorted({d["airline"] for d in deals if d.get("airline")})
    dur = [d["duration_out_min"] for d in deals
           if d.get("duration_out_min") and not d.get("transfers_out")]
    r["dur_min"] = round(sorted(dur)[len(dur) // 2]) if dur else None
    if r["dest_geo"]:
        try:
            lat, lon = (float(x) for x in r["dest_geo"].split(","))
            r["dist_km"] = round(hav(p["geo"][0], p["geo"][1], lat, lon))
        except ValueError:
            r["dist_km"] = None
    else:
        r["dist_km"] = None
    r["iatas"] = "·".join(sorted({d["origin"] for d in deals}))
    r["slug"] = "%s-%s" % (slug(p["city"]), slug(r["dest_city"]))
    return r


def link_grid(title, items):
    if not items:
        return ""
    links = "".join(
        '<a href="/loty/%s/">%s<span class="mp">od %s zł</span></a>'
        % (esc(i["slug"]), esc(i["dest_city"]), fmt_price(i["min_price"]))
        for i in items)
    return ('<div class="card"><h2>%s</h2><div class="links">%s</div></div>'
            % (esc(title), links))


def render_route(r, cfg, related_from, related_to):
    p = cfg["ports"][r["port"]]
    best = r["deals"][0]
    buy = (best.get("offers") or [{}])[0].get("link") or "#"
    title = ("Tanie loty %s – %s (od %s zł) | polataj.se"
             % (p["city"], r["dest_city"], fmt_price(r["min_price"])))
    desc = ("Szukasz tanich lotów z %s (%s) do celu %s? "
            "Sprawdź aktualne okazje cenowe w dwie strony. "
            "Automatyczny skaner cen aktualizowany co 6 godzin."
            % (p["city"], r["iatas"], r["dest_city"]))
    canonical = "%s/loty/%s/" % (SITE, r["slug"])

    thin = len(r["deals"]) < 3 and r["hist_samples"] < 2
    robots = ('<meta name="robots" content="noindex,follow">' if thin
              else "")

    offers_json = [{
        "@type": "Offer", "price": round(d["price"], 2),
        "priceCurrency": "PLN",
        "url": (d.get("offers") or [{}])[0].get("link") or canonical,
        "availability": "https://schema.org/InStock",
        "validFrom": datetime.now(timezone.utc).date().isoformat(),
    } for d in r["deals"][:10]]
    jsonld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Lot %s – %s" % (p["city"], r["dest_city"]),
        "description": desc,
        "offers": {
            "@type": "AggregateOffer",
            "priceCurrency": "PLN",
            "lowPrice": round(r["min_price"], 2),
            "offerCount": len(r["deals"]),
            "offers": offers_json,
        },
    }
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "polataj.se",
             "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": "Loty",
             "item": SITE + "/loty/"},
            {"@type": "ListItem", "position": 3,
             "name": "%s – %s" % (p["city"], r["dest_city"]),
             "item": canonical},
        ],
    }
    jsonld_html = ('<script type="application/ld+json">%s</script>\n'
                   '<script type="application/ld+json">%s</script>'
                   % (json.dumps(jsonld, ensure_ascii=False),
                      json.dumps(breadcrumb, ensure_ascii=False)))

    # --- BODY ---
    b = []
    b.append('<div class="crumb"><a href="/">polataj.se</a> / '
             '<a href="/loty/">loty</a> / %s – %s</div>'
             % (esc(p["city"]), esc(r["dest_city"])))
    b.append('<div class="hero"><h1>%s <span class="iata">%s</span> → '
             '%s <span class="iata">%s</span></h1>'
             % (esc(p["city"]), esc(r["iatas"]),
                esc(r["dest_city"]), esc(r["dest"])))
    b.append('<div class="sub">%s · %s · loty w obie strony</div>'
             % (esc(r["dest_country"]), esc(p["airports_desc"])))
    b.append('<div class="row"><div class="price">'
             '<div class="v">od %s zł</div>'
             '<div class="lbl">najniższa cena w obie strony</div></div>'
             % fmt_price(r["min_price"]))
    b.append('<div class="dates">%s – %s · %s · %s<span> · %s</span></div>'
             % (fmt_date(best["date_out"]), fmt_date(best["date_in"]),
                esc(best.get("nights") and ("%d noc" % best["nights"]
                    if best["nights"] == 1
                    else "%d nocy" % best["nights"]) or ""),
                esc(best.get("airline") or ""),
                esc((best.get("via") or "link"))))
    b.append('<a class="cta" href="%s" data-deal="%s" rel="nofollow '
             'noopener">Zobacz bilet</a></div></div>' % (esc(buy), esc(r["slug"])))

    # statystyki
    cells = []
    if r["dist_km"]:
        cells.append(("Dystans", "≈ %d km" % r["dist_km"]))
    if r["dur_min"]:
        h, m = divmod(r["dur_min"], 60)
        cells.append(("Czas lotu", "%d h %02d min" % (h, m)))
    if r["airlines"]:
        cells.append(("Linie", ", ".join(esc(a) for a in r["airlines"])))
    cells.append(("Ofert teraz", str(len(r["deals"]))))
    if cells:
        b.append('<div class="grid">' + "".join(
            '<div class="cell"><div class="k">%s</div>'
            '<div class="v2">%s</div></div>' % (k, v)
            for k, v in cells) + '</div>')

    # trendy
    trend = []
    if r["min_30d"]:
        trend.append('<span class="chip g">min 30 dni: %s zł</span>'
                     % fmt_price(r["min_30d"]))
    if r["cheap_months"]:
        trend.append('<span class="chip">najtaniej: %s</span>'
                     % esc(", ".join(r["cheap_months"])))
    if r["cheap_wd"]:
        trend.append('<span class="chip">wylot: %s</span>'
                     % esc(", ".join(r["cheap_wd"])))
    if trend:
        b.append('<div class="card"><h2>Kiedy najtaniej</h2>'
                 '<div class="chips">%s</div></div>' % "".join(trend))

    # tabela deali
    rows = []
    for d in r["deals"][:MAX_DEALS_ROWS]:
        l = (d.get("offers") or [{}])[0]
        tr = d.get("transfers")
        if tr is None:
            tr = d.get("transfers_out")
        rows.append(
            '<tr><td>%s – %s</td><td>%s</td><td>%s</td>'
            '<td class="num p">%s zł</td>'
            '<td class="num"><a href="%s" data-deal="%s" rel="nofollow '
            'noopener">%s</a></td></tr>'
            % (fmt_date(d["date_out"]), fmt_date(d["date_in"]),
               esc(d.get("airline") or "—"),
               "bezpośredni" if not tr else "%d przes." % tr,
               fmt_price(d["price"]), esc(l.get("link") or "#"),
               esc(r["slug"]), esc(l.get("label") or "bilet")))
    b.append('<div class="card"><h2>Aktualne okazje '
             '(%d)</h2><table><tr><th>Termin</th><th>Linia</th>'
             '<th>Przesiadki</th><th class="num">Cena</th>'
             '<th class="num"></th></tr>%s</table>'
             '<div class="note">Ceny z automatycznego skanu, '
             'odświeżane co 6 h — mogą się zmienić u przewoźnika.</div>'
             '</div>' % (len(r["deals"]), "".join(rows)))

    b.append(link_grid("Inne tanie loty z %s" % p["city_gen"],
                       related_from))
    b.append(link_grid("%s — loty z innych polskich miast"
                       % r["dest_city"], related_to))
    b.append('<div class="card"><h2>Alerty cenowe</h2>'
             '<div class="sub" style="color:var(--muted);font-size:.9rem">'
             'Chcesz dostawać takie okazje mailem? Zapisz się na '
             '<a href="/%s/" style="color:var(--accent)">stronie portu %s'
             '</a>.</div></div>' % (esc(r["port"]), esc(p["city"])))

    out = TPL
    for k, v in {
        "TITLE": esc(title), "DESCRIPTION": esc(desc),
        "CANONICAL": esc(canonical), "ROBOTS": robots,
        "JSONLD": jsonld_html, "BODY": "".join(b),
    }.items():
        out = out.replace("{{%s}}" % k, v)
    return out


def render_index(routes, cfg):
    by_port = defaultdict(list)
    for r in routes:
        by_port[r["port"]].append(r)
    rows = []
    for port in cfg["ports"]:
        p = cfg["ports"][port]
        rows.append('<h2 style="margin:22px 0 10px">Z %s '
                    '<span style="color:var(--muted);font-weight:400">'
                    '(%s)</span></h2><div class="links">'
                    % (esc(p["city_gen"]), esc(p["airports_desc"])))
        for r in sorted(by_port[port], key=lambda x: x["min_price"]):
            rows.append('<a href="/loty/%s/">%s'
                        '<span class="mp">od %s zł</span></a>'
                        % (esc(r["slug"]), esc(r["dest_city"]),
                           fmt_price(r["min_price"])))
        rows.append('</div>')
    body = ('<div class="hero"><h1>Tanie loty z Polski — wszystkie trasy'
            '</h1><div class="sub">%d tras z aktywnymi okazjami, '
            'skanowane co 6 h</div></div>'
            % len(routes)) + "".join(rows)
    out = TPL
    for k, v in {
        "TITLE": esc("Tanie loty z Polski — wszystkie trasy | polataj.se"),
        "DESCRIPTION": esc("Wszystkie trasy z aktywnymi okazjami lotniczymi "
                           "z polskich lotnisk. Skaner cen odświeżany co 6 h."),
        "CANONICAL": SITE + "/loty/",
        "ROBOTS": "", "JSONLD": "", "BODY": body,
    }.items():
        out = out.replace("{{%s}}" % k, v)
    return out


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    hist = load_history()
    routes = collect_routes(cfg)
    routes = [enrich(r, cfg, hist) for r in routes.values()]

    # dedup slugów (dwa IATA → to samo miasto): dopisz IATA
    seen = defaultdict(list)
    for r in routes:
        seen[r["slug"]].append(r)
    for slug_, rs in seen.items():
        if len(rs) > 1:
            for r in rs:
                r["slug"] = "%s-%s" % (slug_, r["dest"].lower())

    # linki wewnętrzne
    by_port = defaultdict(list)
    by_dest = defaultdict(list)
    for r in routes:
        by_port[r["port"]].append(r)
        by_dest[r["dest"]].append(r)

    out_dir = DOCS / "loty"
    written = []
    for r in routes:
        rel_from = [x for x in
                    sorted(by_port[r["port"]], key=lambda x: x["min_price"])
                    if x is not r][:TOP_REL]
        rel_to = [x for x in
                  sorted(by_dest[r["dest"]], key=lambda x: x["min_price"])
                  if x["port"] != r["port"]][:TOP_REL]
        page = render_route(r, cfg, rel_from, rel_to)
        d = out_dir / r["slug"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(page, encoding="utf-8")
        written.append("/loty/%s/" % r["slug"])

    (out_dir / "index.html").write_text(render_index(routes, cfg),
                                        encoding="utf-8")

    # sitemap
    now = datetime.now(timezone.utc).date().isoformat()
    urls = [SITE + "/", SITE + "/loty/"] + \
           [SITE + "/" + p + "/" for p in cfg["ports"]] + \
           [SITE + u for u in written] + [SITE + "/prywatnosc/"]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        pri = "0.8" if "/loty/" in u and u != SITE + "/loty/" else "0.6"
        sm.append("  <url><loc>%s</loc><lastmod>%s</lastmod>"
                  "<changefreq>daily</changefreq><priority>%s</priority>"
                  "</url>" % (u, now, pri))
    sm.append("</urlset>")
    (DOCS / "sitemap.xml").write_text("\n".join(sm), encoding="utf-8")
    (DOCS / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n" % SITE,
        encoding="utf-8")

    print("%d stron tras + index + sitemap (%d URL-i)"
          % (len(written), len(urls)))


if __name__ == "__main__":
    main()
