#!/usr/bin/env python3
"""Łowca tanich lotów z Warszawy — pobiera okazje z publicznego API Ryanair
i zapisuje je do docs/deals.json (podgląd: docs/index.html)."""

import json
import statistics
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
HISTORY_PATH = ROOT / "data" / "history.jsonl"
DEALS_PATH = ROOT / "docs" / "deals.json"

API_URL = "https://services-api.ryanair.com/farfnd/v4/roundTripFares"
HISTORY_DAYS = 180

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

LINK_TEMPLATE = (
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


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def fetch_fares(origin, cfg):
    """Pobiera najtańsze połączenia w obie strony dla jednego lotniska.
    Zwraca listę surowych 'fares' z API albo pustą listę przy błędzie."""
    jutro = date.today() + timedelta(days=1)
    params = {
        "departureAirportIataCode": origin,
        "outboundDepartureDateFrom": jutro.isoformat(),
        "outboundDepartureDateTo": (jutro + timedelta(days=cfg["days_ahead"])).isoformat(),
        "inboundDepartureDateFrom": (jutro + timedelta(days=cfg["min_nights"])).isoformat(),
        "inboundDepartureDateTo": (
            jutro + timedelta(days=cfg["days_ahead"] + cfg["max_nights"])
        ).isoformat(),
        "durationFrom": cfg["min_nights"],
        "durationTo": cfg["max_nights"],
        "market": "pl-pl",
        "currency": "PLN",
        "priceValueTo": cfg["max_price_pln"],
    }
    url = API_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                print("Błąd HTTP %s dla %s — pomijam" % (resp.status, origin))
                return []
            return json.loads(resp.read().decode("utf-8")).get("fares", [])
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
        print("Nie udało się pobrać danych dla %s: %s — pomijam" % (origin, e))
        return []


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


def normalize(fare, history_by_route, cfg):
    """Surowy wpis z API -> rekord do deals.json."""
    out = fare["outbound"]
    inn = fare["inbound"]
    origin = out["departureAirport"]["iataCode"]
    dest = out["arrivalAirport"]["iataCode"]

    dep_out = out["departureDate"]  # np. "2026-11-27T12:55:00"
    dep_in = inn["departureDate"]
    date_out, time_out = dep_out[:10], dep_out[11:16]
    date_in, time_in = dep_in[:10], dep_in[11:16]
    nights = (
        date.fromisoformat(date_in) - date.fromisoformat(date_out)
    ).days

    price = fare["summary"]["price"]["value"]
    key = (origin, dest)
    history_prices = history_by_route.get(key, [])

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
        "price": price,
        "price_out": out.get("price", {}).get("value"),
        "price_in": inn.get("price", {}).get("value"),
        "airline": "Ryanair",
        "link": LINK_TEMPLATE.format(
            origin=origin, dest=dest, date_out=date_out, date_in=date_in
        ),
        "record_low": is_record_low(price, history_prices, cfg),
        "median_price": (
            round(statistics.median(history_prices), 2) if history_prices else None
        ),
    }


def main():
    cfg = load_config()
    history = load_history()

    # Mediany liczymy na historii sprzed bieżącego uruchomienia.
    history_by_route = {}
    for e in history:
        history_by_route.setdefault((e["origin"], e["dest"]), []).append(e["price"])

    deals = []
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for origin in cfg["airports"]:
        fares = fetch_fares(origin, cfg)
        print("%s: %d połączeń" % (origin, len(fares)))
        for fare in fares:
            try:
                deals.append(normalize(fare, history_by_route, cfg))
            except (KeyError, TypeError, ValueError) as e:
                print("Pominięto niekompletny wpis z %s: %s" % (origin, e))

    # Dopisujemy ceny z bieżącego runu do historii.
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        for e in history:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        for d in deals:
            f.write(
                json.dumps(
                    {
                        "ts": now,
                        "origin": d["origin"],
                        "dest": d["dest"],
                        "price": d["price"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    deals.sort(key=lambda d: d["price"])
    DEALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DEALS_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {"generated_at": now, "config": cfg, "deals": deals},
            f,
            ensure_ascii=False,
            indent=2,
        )

    lows = sum(1 for d in deals if d["record_low"])
    print(
        "Zapisano %d okazji do %s (rekordowo tanich: %d)"
        % (len(deals), DEALS_PATH.relative_to(ROOT), lows)
    )


if __name__ == "__main__":
    main()
