"""Publikacja okazji na Wykop (mikroblog) — API v3.

Wykop publikuje te same oferty co pozostałe kanały przy każdym skanie:
max MAX_POSTS nowych wpisów, deduplikacja ofert, cooldown ROUTE_DAYS na trasę
(na poziomie miasta — WAW/WMI/RDO do tego samego celu to jedna trasa).
Grafika: dokładnie 1 załącznik (mapka trasy).
"""
import json
import os
import time
import urllib.request
import urllib.error
import http.client
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "data" / "cache" / "wykop_state.json"
API = "https://wykop.pl/api/v3"
MAX_POSTS = 3
ROUTE_DAYS = 5


def load_config():
    values = {}
    path = ROOT / "wykop" / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
    get = lambda k, d="": os.environ.get(k, values.get(k, d))
    return {"key": get("WYKOP_APP_KEY"), "secret": get("WYKOP_APP_SECRET"),
            "refresh": get("WYKOP_REFRESH_TOKEN"),
            "enabled": get("WYKOP_ENABLED") == "1"}


def _load_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state))


def _deal_id(deal):
    return "%s-%s-%s-%s" % (deal["origin"], deal["dest"],
                            deal["date_out"], deal.get("date_in"))


def _route(deal):
    return "%s-%s" % (deal.get("origin_city") or deal["origin"],
                      deal.get("dest_city") or deal["dest"])


def _user_token(config):
    """Świeży JWT użytkownika: z cache lub po refresh_token (rtoken się rotuje)."""
    state = _load_state()
    if state.get("token") and not _jwt_expired(state["token"]):
        return state["token"]
    rtoken = state.get("rtoken") or config["refresh"]
    req = urllib.request.Request(API + "/refresh-token", headers={
        "Content-Type": "application/json", "accept": "application/json"},
        data=json.dumps({"data": {"refresh_token": rtoken}}).encode())
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)["data"]
    state.update({"token": data["token"], "rtoken": data["refresh_token"]})
    _save_state(state)
    return data["token"]


def _jwt_expired(token):
    try:
        payload = json.loads(__import__("base64").urlsafe_b64decode(
            token.split(".")[1] + "==").decode())
        return payload.get("exp", 0) < time.time() + 60
    except (ValueError, KeyError, IndexError):
        return True


def _upload(token, image):
    boundary = "wykop" + os.urandom(12).hex()
    body = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; "
             "filename=\"trasa.png\"\r\nContent-Type: image/png\r\n\r\n" % boundary).encode()
            + image + ("\r\n--%s--\r\n" % boundary).encode())
    req = urllib.request.Request(API + "/media/photos/upload?type=comments",
                                 data=body, headers={
        "Authorization": "Bearer " + token, "accept": "application/json",
        "Content-Type": "multipart/form-data; boundary=" + boundary})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["data"]["key"]


def _entry(token, content, media_key=None):
    payload = {"data": {"content": content}}
    if media_key:
        payload["data"]["photo"] = media_key
    req = urllib.request.Request(API + "/entries",
                                 data=json.dumps(payload).encode(),
                                 headers={"Authorization": "Bearer " + token,
                                          "accept": "application/json",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["data"]


def format_entry(deal):
    """Jeden wpis = jedna oferta, jak na pozostałych kanałach."""
    dates = deal["date_out"] + (" – %s" % deal["date_in"] if deal.get("date_in")
                                else " (w jedną stronę)")
    return ("✈️ **%s ➡️ %s** – od %.0f zł (%s)\n"
            "📅 Daty: %s\n\n"
            "%s\n\n"
            "🔗 Szczegóły: %s\n\n"
            "---\nSkaner & alerty w czasie rzeczywistym: https://polataj.se | "
            "Telegram: https://t.me/polataj_se\n"
            "#polatajse #tanieloty #podroze #promocje"
            % (deal["origin_city"], deal["dest_city"], deal["price"],
               "w jedną stronę" if not deal.get("date_in") else "w dwie strony",
               dates, deal.get("_description", ""), _deal_url(deal)))


def _deal_url(deal):
    if deal.get("trip") == "oneway" or not deal.get("date_in"):
        return "https://polataj.se/%s/#wjedna" % deal["port"]
    from tools.build_pages import slug
    return "https://polataj.se/loty/%s-%s/" % (
        slug(deal["origin_city"]), slug(deal["dest_city"]))


def post(config, content, image=None):
    if not config["enabled"]:
        print("wykop: wyłączony (brak WYKOP_ENABLED=1) — wpis pominięty")
        return None
    token = _user_token(config)
    media = _upload(token, image) if image else None
    return _entry(token, content, media)


def publish(config, deals, image_for, now):
    """Publikuje nowe oferty (jak pozostałe kanały). Zwraca liczbę wpisów."""
    if not config["enabled"]:
        return 0
    state = _load_state()
    posted = set(state.get("posted_ids") or [])
    routes = state.get("routes") or {}
    from hit_detector import description
    sent = 0
    run_routes = set()
    for deal in sorted(deals, key=lambda d: d["price"]):
        if sent >= MAX_POSTS:
            break
        key, route = _deal_id(deal), _route(deal)
        if (key in posted or route in run_routes or
                routes.get(route, 0) > now.timestamp() - ROUTE_DAYS * 86400):
            continue
        content = format_entry({**deal, "_description": description(deal)})
        try:
            image = image_for(deal) if image_for else None
        except (OSError, ValueError, KeyError, TypeError, IndexError,
                http.client.HTTPException):
            image = None
        if not post(config, content, image):
            print("wykop: wpis niepotwierdzony, ponowienie przy kolejnym skanie")
            break
        posted.add(key)
        run_routes.add(route)
        routes[route] = now.timestamp()
        sent += 1
        print("wykop: opublikowano %s" % key)
    state = _load_state()
    state["posted_ids"] = list(posted | set(state.get("posted_ids") or []))[-300:]
    state["routes"] = {r: ts for r, ts in routes.items()
                       if ts > now.timestamp() - 30 * 86400}
    _save_state(state)
    return sent
