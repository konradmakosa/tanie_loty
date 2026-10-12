#!/usr/bin/env python3
"""Łowca tanich lotów z Warszawy — pobiera okazje z publicznych API
(Ryanair + Aviasales/Travelpayouts) i zapisuje je do docs/deals.json
(podgląd: docs/index.html)."""

import json
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
ENV_PATH = ROOT / ".env"
HISTORY_PATH = ROOT / "data" / "history.jsonl"
DEALS_PATH = ROOT / "docs" / "deals.json"
CACHE_DIR = ROOT / "data" / "cache"

RYANAIR_ROUTES = ("https://www.ryanair.com/api/views/locate/searchWidget"
                  "/routes/pl/airport/{origin}")
RYANAIR_CAL = ("https://www.ryanair.com/api/farfnd/v4/roundTripFares"
               "/{origin}/{dest}/cheapestPerDay")
ROUTES_CACHE_DAYS = 7
MAX_PER_ROUTE = 10
AVIASALES_API = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
AVIASALES_SITE = "https://www.aviasales.com"
TP_DATA = "https://api.travelpayouts.com/data/pl"

HISTORY_DAYS = 180
CACHE_MAX_AGE_DAYS = 30

# Polskie nazwy krajów, których brakuje w pliku countries.json Travelpayouts
# (tam "GB" ma name="GB").
COUNTRY_PL = {"GB": "Wielka Brytania"}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

RYANAIR_LINK = (
    "https://www.ryanair.com/pl/pl/trip/flights/select"
    "?adults=1&teens=0&children=0&infants=0"
    "&dateOut={date_out}&dateIn={date_in}"
    "&isConnectedFlight=false&discount=0&promoCode=&isReturn=true"
    "&originIata={origin}&destinationIata={dest}"
    "&tpAdults=1&tpTeens=0&tpChildren=0&tpInfants=0"
    "&tpStartDate={date_out}&tpEndDate={date_in}"
    "&tpDiscount=0&tpPromoCode="
    "&tpOriginIata={origin}&tpDestinationIata={dest}"
)

NOTE_RYANAIR = "cena bez bagażu rejestrowanego"
NOTE_AVIASALES = "cena z ostatnich 48 h, sprawdź przy zakupie"
NOTE_AVIASALES_LOWCOST = ("cena pośrednika z ostatnich 48 h — "
                          "przy Ryanair/Wizz lepiej kupić bezpośrednio")
LOWCOST_CODES = {"FR", "RK", "RR", "MW", "W6", "W4", "W9"}

AIRLINE_NAMES = {
    "FR": "Ryanair", "RK": "Ryanair UK",
    "W6": "Wizz Air", "W4": "Wizz Air Malta", "W9": "Wizz Air UK",
    "LO": "LOT", "U2": "easyJet", "EJU": "easyJet Europe",
    "VY": "Vueling", "EW": "Eurowings", "LH": "Lufthansa",
    "KL": "KLM", "AF": "Air France", "SK": "SAS", "AY": "Finnair",
    "BT": "airBaltic", "OS": "Austrian", "LX": "SWISS",
    "TK": "Turkish Airlines", "PC": "Pegasus", "A3": "Aegean",
    "TP": "TAP", "IB": "Iberia", "BA": "British Airways",
    "AZ": "ITA Airways", "NO": "Neos", "0B": "Blue Air",
    "FB": "Bulgaria Air",
    "RR": "Buzz (Ryanair)", "MW": "Malta Air (Ryanair)",
}


def airline_name(code, tp_airlines=None):
    """Nazwa linii: najpierw mapa statyczna, potem airlines.json
    z Travelpayouts, na końcu sam kod."""
    if not code:
        return ""
    if code in AIRLINE_NAMES:
        return AIRLINE_NAMES[code]
    if tp_airlines and code in tp_airlines:
        return tp_airlines[code]
    return code


def load_env():
    """Wczytuje ROOT/.env (KLUCZ=wartość), nie nadpisując istniejących
    zmiennych środowiskowych."""
    if not ENV_PATH.exists():
        return
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def http_get_json(url, headers=None):
    """GET -> sparsowany JSON. Rzuca wyjątek przy błędzie HTTP/sieci."""
    hdrs = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise urllib.error.HTTPError(url, resp.status, resp.reason,
                                         resp.headers, None)
        return json.loads(resp.read().decode("utf-8"))


def cached_json(name, url, max_age_days=CACHE_MAX_AGE_DAYS):
    """Pobiera JSON z URL-a, trzymając kopię w data/cache przez
    max_age_days dni. Przy błędzie używa starej kopii, jeśli jest."""
    path = CACHE_DIR / name
    fresh = (
        path.exists()
        and (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime))
        < timedelta(days=max_age_days)
    )
    if not fresh:
        try:
            data = http_get_json(url)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return data
        except Exception as e:
            if not path.exists():
                print("Nie udało się pobrać %s: %s" % (url, e))
                return []
            print("Odświeżenie %s nieudane (%s) — używam starej kopii"
                  % (name, e))
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print("Nie udało się wczytać cache %s: %s" % (path, e))
        return []


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_history():
    """Wczytuje historię cen i przycina ją do ostatnich HISTORY_DAYS dni."""
    if not HISTORY_PATH.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)
    entries = []
    with open(HISTORY_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry["ts"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                entries.append(entry)
    return entries


def is_record_low(price, history_prices, cfg):
    """True, gdy mamy dość próbek w historii, a cena jest wyraźnie
    poniżej mediany (record_low_ratio)."""
    if len(history_prices) < cfg["record_low_min_samples"]:
        return False
    return price <= cfg["record_low_ratio"] * statistics.median(history_prices)


def annotate_record_low(deals, history_by_route, cfg):
    """Uzupełnia record_low i median_price na podstawie historii
    (sprzed bieżącego uruchomienia)."""
    for d in deals:
        prices = history_by_route.get((d["origin"], d["dest"]), [])
        d["record_low"] = is_record_low(d["price"], prices, cfg)
        d["median_price"] = (
            round(statistics.median(prices), 2) if prices else None
        )


def month_starts(start, end):
    """Lista 'YYYY-MM-01' pokrywająca miesiące od start do end włącznie."""
    months = []
    cur = start.replace(day=1)
    while cur <= end:
        months.append(cur.strftime("%Y-%m-01"))
        rok, mies = cur.year + (cur.month == 12), (cur.month % 12) + 1
        cur = cur.replace(year=rok, month=mies)
    return months


def fetch_ryanair(cfg):
    """Kalendarz cen Ryanair: wszystkie trasy z lotnisk z konfiguracji,
    wszystkie kombinacje dat w kopercie (max MAX_PER_ROUTE na trasę)."""
    jutro = date.today() + timedelta(days=1)
    max_out = jutro + timedelta(days=cfg["days_ahead"])
    months = month_starts(jutro, max_out + timedelta(days=cfg["max_nights"]))
    deals = []
    for origin in cfg["airports"]:
        routes = cached_json("routes_%s.json" % origin,
                             RYANAIR_ROUTES.format(origin=origin),
                             ROUTES_CACHE_DAYS)
        if not routes:
            print("Ryanair %s: brak listy tras — pomijam" % origin)
            continue
        n_tras = 0
        for r in routes:
            arr = r.get("arrivalAirport") or {}
            dest = arr.get("code")
            if not dest or not r.get("operator"):
                continue
            n_tras += 1
            deals.extend(ryanair_route(origin, dest, arr, cfg, jutro,
                                       max_out, months))
        print("Ryanair %s: %d tras" % (origin, n_tras))
    return deals


def ryanair_route(origin, dest, arr, cfg, jutro, max_out, months):
    """Kombinacje tam-i-z-powrotem dla jednej trasy, max MAX_PER_ROUTE."""
    out_by_day = {}
    in_by_day = {}
    for month in months:
        params = {
            "outboundMonthOfDate": month,
            "inboundMonthOfDate": month,
            "currency": "PLN",
        }
        url = (RYANAIR_CAL.format(origin=origin, dest=dest)
               + "?" + urllib.parse.urlencode(params))
        try:
            data = http_get_json(url)
        except Exception as e:
            print("Ryanair %s->%s %s: błąd (%s) — pomijam miesiąc"
                  % (origin, dest, month, e))
            time.sleep(0.15)
            continue
        time.sleep(0.15)
        for f in (data.get("outbound") or {}).get("fares") or []:
            if fare_ok(f):
                out_by_day[f["day"]] = f
        for f in (data.get("inbound") or {}).get("fares") or []:
            if fare_ok(f):
                in_by_day[f["day"]] = f

    combos = []
    for d_out, fo in out_by_day.items():
        do = date.fromisoformat(d_out)
        if not (jutro <= do <= max_out):
            continue
        for d_in, fi in in_by_day.items():
            nights = (date.fromisoformat(d_in) - do).days
            if not (cfg["min_nights"] <= nights <= cfg["max_nights"]):
                continue
            total = fo["price"]["value"] + fi["price"]["value"]
            if total > cfg["max_price_pln"]:
                continue
            combos.append((total, fo, fi, nights))
    combos.sort(key=lambda c: c[0])
    return [ryanair_deal(origin, dest, arr, fo, fi, total, nights)
            for total, fo, fi, nights in combos[:MAX_PER_ROUTE]]


def fare_ok(f):
    """Czy wpis kalendarza ma realną cenę."""
    return (f.get("price") and not f.get("soldOut")
            and not f.get("unavailable"))


def ryanair_deal(origin, dest, arr, fo, fi, total, nights):
    dep_out = fo.get("departureDate") or (fo["day"] + "T00:00:00")
    dep_in = fi.get("departureDate") or (fi["day"] + "T00:00:00")
    date_out, time_out = dep_out[:10], dep_out[11:16]
    date_in, time_in = dep_in[:10], dep_in[11:16]

    return {
        "id": "%s-%s-%s-%s" % (origin, dest, date_out, date_in),
        "origin": origin,
        "origin_name": origin,
        "dest": dest,
        "dest_city": (arr.get("city") or {}).get("name")
                     or arr.get("name") or dest,
        "dest_country": (arr.get("country") or {}).get("name", ""),
        "date_out": date_out,
        "time_out": time_out,
        "date_in": date_in,
        "time_in": time_in,
        "nights": nights,
        "price": round(total, 2),
        "price_out": fo["price"]["value"],
        "price_in": fi["price"]["value"],
        "transfers": 0,
        "weekday_out": date.fromisoformat(date_out).weekday(),
        "weekday_in": date.fromisoformat(date_in).weekday(),
        "airline_code": "FR",
        "airline": "Ryanair",
        "source": "ryanair",
        "note": NOTE_RYANAIR,
        "link": RYANAIR_LINK.format(origin=origin, dest=dest,
                                    date_out=date_out, date_in=date_in),
    }


def fetch_aviasales(cfg, token, marker):
    """Ceny wszystkich linii z Aviasales Data API (Travelpayouts).
    Bez tokena zwraca pustą listę."""
    if not token:
        print("Aviasales: brak TRAVELPAYOUTS_TOKEN — pomijam")
        return []

    # Mapowania kodów -> nazwy (cache w data/cache, odświeżane co 30 dni).
    cities = {c.get("code"): c for c in cached_json("cities.json",
                                                  TP_DATA + "/cities.json")}
    countries = {c.get("code"): c for c in cached_json(
        "countries.json", TP_DATA + "/countries.json")}
    airports = {a.get("code"): a for a in cached_json(
        "airports.json", TP_DATA + "/airports.json")}
    tp_airlines = {a.get("code"): a.get("name") for a in cached_json(
        "airlines.json", "https://api.travelpayouts.com/data/en/airlines.json")}

    def city_name(code):
        c = cities.get(code)
        return (c or {}).get("name") or code or ""

    def country_name(code):
        if code in cities and cities[code].get("country_code"):
            code = cities[code]["country_code"]
        elif code in airports and airports[code].get("country_code"):
            code = airports[code]["country_code"]
        c = countries.get(code) or {}
        name = c.get("name")
        if not name or name == code:
            tr = c.get("name_translations") or {}
            name = COUNTRY_PL.get(code) or tr.get("en") or name or ""
        return name

    jutro = date.today() + timedelta(days=1)
    koniec = jutro + timedelta(days=cfg["days_ahead"])

    # Jeden request na każdy miesiąc pokrywający zakres dat.
    months = [m[:7] for m in month_starts(jutro, koniec)]

    deals = []
    for month in months:
        params = {
            "origin": "WAW",  # kod miasta — obejmuje WAW i WMI
            "departure_at": month,
            "one_way": "false",
            "direct": "true",
            "unique": "false",
            "sorting": "price",
            "currency": "pln",
            "market": "pl",
            "limit": 1000,
            "page": 1,
        }
        url = AVIASALES_API + "?" + urllib.parse.urlencode(params)
        try:
            resp = http_get_json(url, {"X-Access-Token": token})
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                print("Aviasales %s: HTTP %d — nieprawidłowy token?"
                      % (month, e.code))
            else:
                print("Aviasales %s: błąd HTTP %d — pomijam"
                      % (month, e.code))
            continue
        except Exception as e:
            print("Aviasales %s: błąd pobierania (%s) — pomijam" % (month, e))
            continue

        data = resp.get("data") or []
        ok = 0
        for r in data:
            try:
                d = aviasales_deal(r, cfg, marker, city_name, country_name,
                                   airports, tp_airlines, jutro, koniec)
            except (KeyError, TypeError, ValueError) as e:
                print("Aviasales: pominięto niekompletny wpis (%s)" % e)
                continue
            if d is not None:
                deals.append(d)
                ok += 1
        print("Aviasales %s: %d rekordów z API, %d po filtrach"
              % (month, len(data), ok))
    return deals


def aviasales_deal(r, cfg, marker, city_name, country_name, airports,
                   tp_airlines, jutro, koniec):
    """Surowy rekord Aviasales -> rekord deal albo None gdy odfiltrowany."""
    price = r.get("price")
    dep_at = r.get("departure_at") or ""
    ret_at = r.get("return_at") or ""
    if price is None or len(dep_at) < 16 or len(ret_at) < 16:
        raise ValueError("brak price/departure_at/return_at")

    if float(price) > cfg["max_price_pln"]:
        return None
    if (r.get("transfers") or 0) != 0 or (r.get("return_transfers") or 0) != 0:
        return None

    date_out, time_out = dep_at[:10], dep_at[11:16]
    date_in, time_in = ret_at[:10], ret_at[11:16]
    d_out = date.fromisoformat(date_out)
    nights = (date.fromisoformat(date_in) - d_out).days
    if not (cfg["min_nights"] <= nights <= cfg["max_nights"]):
        return None
    if not (jutro <= d_out <= koniec):
        return None

    origin = r.get("origin_airport") or r.get("origin") or ""
    dest = r.get("destination_airport") or r.get("destination") or ""
    origin_city = r.get("origin") or origin
    dest_city_code = r.get("destination") or dest

    code = r.get("airline") or ""

    link = r.get("link")
    if link:
        url = AVIASALES_SITE + link
    else:
        url = ("%s/search/%s%s%s%s1"
               % (AVIASALES_SITE, origin_city,
                  date_out[8:10] + date_out[5:7],
                  dest_city_code,
                  date_in[8:10] + date_in[5:7]))
    if marker:
        url += ("&" if "?" in url else "?") + "marker=" + urllib.parse.quote(marker)

    origin_name = (airports.get(origin) or {}).get("name") or origin

    return {
        "id": "%s-%s-%s-%s" % (origin, dest, date_out, date_in),
        "origin": origin,
        "origin_name": origin_name,
        "dest": dest,
        "dest_city": city_name(dest_city_code),
        "dest_country": country_name(dest_city_code),
        "date_out": date_out,
        "time_out": time_out,
        "date_in": date_in,
        "time_in": time_in,
        "nights": nights,
        "price": float(price),
        "price_out": None,
        "price_in": None,
        "transfers": (r.get("transfers") or 0) + (r.get("return_transfers") or 0),
        "weekday_out": d_out.weekday(),
        "weekday_in": date.fromisoformat(date_in).weekday(),
        "airline_code": code,
        "airline": airline_name(code, tp_airlines),
        "source": "aviasales",
        "note": (NOTE_AVIASALES_LOWCOST if code in LOWCOST_CODES
                 else NOTE_AVIASALES),
        "link": url,
    }


SOURCE_LABELS = {"ryanair": "ryanair.com", "aviasales": "Aviasales"}


def direct_for(d, group):
    """Link bezpośredni do linii dla scalonej oferty + etykieta.
    Oferta ryanair-source wygrywa (jej link = strona wyboru lotu)."""
    for g in group:
        if g["source"] == "ryanair":
            return g["link"], "ryanair.com"
    code = d.get("airline_code")
    if code in ("FR", "RK", "RR", "MW"):
        return RYANAIR_LINK.format(origin=d["origin"], dest=d["dest"],
                                   date_out=d["date_out"],
                                   date_in=d["date_in"]), "ryanair.com"
    if code in ("W6", "W4", "W9"):
        return ("https://wizzair.com/pl-pl/booking/select-flight/"
                "{}/{}/{}/{}/1/0/0/null".format(d["origin"], d["dest"],
                                                d["date_out"], d["date_in"]),
                "wizzair.com")
    if code == "LO":
        return ("https://www.lot.com/pl/pl/booking/flights"
                "?from={}&to={}&departure={}&return={}".format(
                    d["origin"], d["dest"], d["date_out"], d["date_in"]),
                "lot.com")
    return None, None


def merge_offers(deals):
    """Scala rekordy o tym samym (origin, dest, date_out, date_in):
    rekord główny = najtańszy, reszta trafia do offers."""
    groups = {}
    for d in deals:
        key = (d["origin"], d["dest"], d["date_out"], d["date_in"])
        groups.setdefault(key, []).append(d)

    merged = []
    for group in groups.values():
        group.sort(key=lambda d: d["price"])
        main = dict(group[0])
        main["offers"] = [
            {"source": g["source"], "price": g["price"], "link": g["link"],
             "label": SOURCE_LABELS.get(g["source"], g["source"]),
             "airline": g["airline"]}
            for g in group
        ]
        main["direct_link"], main["direct_label"] = direct_for(main, group)
        # Top-level link == offers[0].link — oszczędzamy ~600 B na rekord.
        del main["link"]
        merged.append(main)
    return merged


def main():
    cfg = load_config()
    load_env()
    token = os.environ.get("TRAVELPAYOUTS_TOKEN")
    marker = os.environ.get("TRAVELPAYOUTS_MARKER")

    history = load_history()
    history_by_route = {}
    for e in history:
        history_by_route.setdefault((e["origin"], e["dest"]),
                                    []).append(e["price"])

    sources = ["ryanair"]
    if token:
        sources.append("aviasales")
    ry = fetch_ryanair(cfg)
    avi = fetch_aviasales(cfg, token, marker)
    counts = {"ryanair": len(ry), "aviasales": len(avi)}

    # Scalanie ofert z wielu źródeł dla tej samej trasy i dat.
    deals = merge_offers(ry + avi)

    annotate_record_low(deals, history_by_route, cfg)

    # Dopisujemy ceny z bieżącego runu do historii.
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        for e in history:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        for d in deals:
            f.write(json.dumps({"ts": now, "origin": d["origin"],
                                "dest": d["dest"], "price": d["price"],
                                "source": d["source"]},
                               ensure_ascii=False) + "\n")

    deals.sort(key=lambda d: d["price"])
    DEALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DEALS_PATH, "w", encoding="utf-8") as f:
        json.dump({"generated_at": now, "config": cfg,
                   "sources": sources, "counts": counts, "deals": deals},
                  f, ensure_ascii=False, separators=(",", ":"))

    lows = sum(1 for d in deals if d["record_low"])
    multi = sum(1 for d in deals if len(d["offers"]) > 1)
    print("Zapisano %d okazji do %s (rekordowo tanich: %d, "
          "z wieloma źródłami: %d, źródła: %s "
          "[ryanair: %d, aviasales: %d])"
          % (len(deals), DEALS_PATH, lows, multi,
             ", ".join(sources) if sources else "brak",
             counts["ryanair"], counts["aviasales"]))


if __name__ == "__main__":
    main()
