#!/usr/bin/env python3
"""Łowca tanich lotów z Warszawy — pobiera okazje z publicznych API
(Ryanair + Aviasales/Travelpayouts) i zapisuje je do docs/deals.json
(podgląd: docs/index.html)."""

import json
import os
import statistics
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

RYANAIR_API = "https://services-api.ryanair.com/farfnd/v4/roundTripFares"
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


def cached_json(name, url):
    """Pobiera JSON z URL-a, trzymając kopię w data/cache przez
    CACHE_MAX_AGE_DAYS dni. Przy błędzie używa starej kopii, jeśli jest."""
    path = CACHE_DIR / name
    fresh = (
        path.exists()
        and (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime))
        < timedelta(days=CACHE_MAX_AGE_DAYS)
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


def fetch_ryanair(cfg):
    """Najtańsze połączenia Ryanair dla każdego lotniska z konfiguracji."""
    jutro = date.today() + timedelta(days=1)
    deals = []
    for origin in cfg["airports"]:
        params = {
            "departureAirportIataCode": origin,
            "outboundDepartureDateFrom": jutro.isoformat(),
            "outboundDepartureDateTo": (
                jutro + timedelta(days=cfg["days_ahead"])).isoformat(),
            "inboundDepartureDateFrom": (
                jutro + timedelta(days=cfg["min_nights"])).isoformat(),
            "inboundDepartureDateTo": (
                jutro + timedelta(days=cfg["days_ahead"] + cfg["max_nights"])
            ).isoformat(),
            "durationFrom": cfg["min_nights"],
            "durationTo": cfg["max_nights"],
            "market": "pl-pl",
            "currency": "PLN",
            "priceValueTo": cfg["max_price_pln"],
        }
        url = RYANAIR_API + "?" + urllib.parse.urlencode(params)
        try:
            fares = http_get_json(url).get("fares", [])
        except Exception as e:
            print("Ryanair %s: błąd pobierania (%s) — pomijam" % (origin, e))
            continue
        ok = 0
        for fare in fares:
            try:
                deals.append(ryanair_deal(fare))
                ok += 1
            except (KeyError, TypeError, ValueError) as e:
                print("Ryanair %s: pominięto niekompletny wpis (%s)"
                      % (origin, e))
        print("Ryanair %s: %d połączeń" % (origin, ok))
    return deals


def ryanair_deal(fare):
    out = fare["outbound"]
    inn = fare["inbound"]
    origin = out["departureAirport"]["iataCode"]
    dest = out["arrivalAirport"]["iataCode"]

    dep_out = out["departureDate"]  # np. "2026-11-27T12:55:00"
    dep_in = inn["departureDate"]
    date_out, time_out = dep_out[:10], dep_out[11:16]
    date_in, time_in = dep_in[:10], dep_in[11:16]
    nights = (date.fromisoformat(date_in)
              - date.fromisoformat(date_out)).days

    return {
        "id": "%s-%s-%s-%s" % (origin, dest, date_out, date_in),
        "origin": origin,
        "origin_name": out["departureAirport"].get("name", origin),
        "dest": dest,
        "dest_city": out["arrivalAirport"].get("city", {}).get("name", dest),
        "dest_country": out["arrivalAirport"].get("countryName", ""),
        "date_out": date_out,
        "time_out": time_out,
        "date_in": date_in,
        "time_in": time_in,
        "nights": nights,
        "price": fare["summary"]["price"]["value"],
        "price_out": out.get("price", {}).get("value"),
        "price_in": inn.get("price", {}).get("value"),
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
    months = []
    cur = jutro.replace(day=1)
    while cur <= koniec:
        months.append(cur.strftime("%Y-%m"))
        rok, mies = cur.year + (cur.month == 12), (cur.month % 12) + 1
        cur = cur.replace(year=rok, month=mies)

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
        "note": NOTE_AVIASALES,
        "link": url,
    }


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
    deals = fetch_ryanair(cfg)
    deals += fetch_aviasales(cfg, token, marker)

    # Dedupe po trasie i datach — zostaje tańsza oferta.
    best = {}
    for d in deals:
        key = (d["origin"], d["dest"], d["date_out"], d["date_in"])
        if key not in best or d["price"] < best[key]["price"]:
            best[key] = d
    deals = list(best.values())

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
                   "sources": sources, "deals": deals},
                  f, ensure_ascii=False, indent=2)

    lows = sum(1 for d in deals if d["record_low"])
    print("Zapisano %d okazji do %s (rekordowo tanich: %d, źródła: %s)"
          % (len(deals), DEALS_PATH, lows,
             ", ".join(sources) if sources else "brak"))


if __name__ == "__main__":
    main()
