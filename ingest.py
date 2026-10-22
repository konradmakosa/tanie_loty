#!/usr/bin/env python3
"""Wysyła oferty z docs/<port>/{deals,far}.json do bazy
przez API PHP (ingest.php). Bez TL_API_BASE/TL_INGEST_KEY — pomija.
Użycie: python ingest.py [port] (domyślnie zwarszawy)."""

import gzip
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"

# Port wylotu: python ingest.py zkrakowa (domyślnie zwarszawy).
PORT = sys.argv[1] if len(sys.argv) > 1 else "zwarszawy"
PORT_DIR = ROOT / "docs" / PORT

OFFER_KEYS = ("origin", "dest", "dest_city", "country", "country_code",
              "date_out", "date_in", "nights", "price", "airline_code",
              "category", "source", "transfers_out", "transfers_in")


def load_env():
    if not ENV_PATH.exists():
        return
    for line in open(ENV_PATH, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def build_payload(path, tab, ts):
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    offers = []
    for d in data.get("deals", []):
        offers.append({
            "origin": d["origin"],
            "dest": d["dest"],
            "dest_city": d.get("dest_city"),
            "country": d.get("dest_country"),
            "country_code": d.get("country_code"),
            "date_out": d["date_out"],
            "date_in": d["date_in"],
            "nights": d.get("nights"),
            "price": d["price"],
            "airline_code": d.get("airline_code"),
            "category": d.get("category"),
            "source": d.get("source"),
            "transfers_out": d.get("transfers_out"),
            "transfers_in": d.get("transfers_in"),
        })
    return {"ts": ts, "tab": tab, "offers": offers}


def post_json(url, key, payload):
    body = gzip.compress(json.dumps(payload,
                                    ensure_ascii=False).encode("utf-8"))
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Content-Encoding": "gzip",
                 "X-Ingest-Key": key,
                 "User-Agent": "tanie-loty-ingest/1.0"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if attempt == 0 and e.code >= 500:
                continue
            raise
    return None


def main():
    load_env()
    base = os.environ.get("TL_API_BASE", "").rstrip("/")
    key = os.environ.get("TL_INGEST_KEY", "")
    if not base or not key:
        print("ingest: brak TL_API_BASE lub TL_INGEST_KEY — pomijam")
        return

    ts = None
    deals_path = PORT_DIR / "deals.json"
    if deals_path.exists():
        ts = json.loads(deals_path.read_text(encoding="utf-8")) \
            .get("generated_at")
    from datetime import datetime, timezone
    ts = ts or datetime.now(timezone.utc).isoformat()

    for path, tab in [(deals_path, "okazje"),
                      (PORT_DIR / "far.json", "daleko")]:
        payload = build_payload(path, tab, ts)
        if not payload or not payload["offers"]:
            print("ingest: brak ofert dla %s — pomijam" % tab)
            continue
        try:
            resp = post_json(base + "/ingest.php", key, payload)
            print("ingest %s: %s" % (tab, resp))
        except Exception as e:
            print("ingest %s: błąd (%s)" % (tab, e))

    # Alerty e-mail: rekordowo tanie loty → notify.php.
    lows = [d for d in (json.loads(deals_path.read_text(encoding="utf-8"))
                        .get("deals") or [])
            if d.get("record_low")] if deals_path.exists() else []
    if not lows:
        print("notify: brak rekordów — pomijam")
    else:
        payload = {"port": PORT, "deals": [{
            "id": d["id"], "origin": d["origin"], "dest": d["dest"],
            "dest_city": d.get("dest_city"),
            "dest_country": d.get("dest_country"),
            "date_out": d["date_out"], "date_in": d["date_in"],
            "nights": d.get("nights"), "price": d["price"],
            "airline": d.get("airline"), "median_price": d.get("typical_price"),
            "link": (d.get("offers") or [{}])[0].get("link")
                    or d.get("direct_link") or "",
        } for d in lows]}
        try:
            resp = post_json(base + "/notify.php", key, payload)
            print("notify: %s" % resp)
        except Exception as e:
            print("notify: błąd (%s)" % e)

    # Utrzymanie bazy subskrybentów (przypomnienia + sprzątanie).
    # Idempotentne — bezpieczne przy 6 wywołaniach na przebieg.
    try:
        resp = post_json(base + "/maintenance.php", key, {})
        print("maintenance: %s" % resp)
    except Exception as e:
        print("maintenance: błąd (%s)" % e)


if __name__ == "__main__":
    main()
