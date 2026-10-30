"""Publikacja okazji na Wykop (mikroblog) — API v3.

Digest: max 1 wpis dziennie (rano, gdy timer go uruchomi).
Hit: natychmiastowy wpis, max 1 na 4 h, niezależnie od digestu.
Grafika: dokładnie 1 załącznik (mapka trasy / ilustracja).
"""
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error
import http.client
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "data" / "cache" / "wykop_state.json"
API = "https://wykop.pl/api/v3"
HIT_COOLDOWN = 4 * 3600
MAX_DEALS = 5


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


def can_digest(state, now):
    return state.get("digest_date") != now.strftime("%Y-%m-%d")


def can_hit(state, now):
    return now.timestamp() - state.get("hit_ts", 0) >= HIT_COOLDOWN


def _token(config):
    req = urllib.request.Request(API + "/auth", headers={
        "Content-Type": "application/json", "accept": "application/json"},
        data=json.dumps({"data": {"key": config["key"],
                                  "secret": config["secret"]}}).encode())
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["data"]["token"]


def _jwt_expired(token):
    try:
        payload = json.loads(__import__("base64").urlsafe_b64decode(
            token.split(".")[1] + "==").decode())
        return payload.get("exp", 0) < time.time() + 60
    except (ValueError, KeyError, IndexError):
        return True


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


def _deal_url(deal):
    if deal.get("trip") == "oneway" or not deal.get("date_in"):
        return "https://polataj.se/%s/#wjedna" % deal["port"]
    return "https://polataj.se/%s/" % deal["port"]


def format_deal(index, deal):
    dates = deal["date_out"] + (" – %s" % deal["date_in"] if deal.get("date_in")
                                else " (w jedną stronę)")
    return ("%d. **%s ➡️ %s** – od %.0f zł (%s)\n"
            "   📅 Daty: %s\n"
            "   🔗 %s" % (index, deal["origin_city"], deal["dest_city"],
                         deal["price"],
                         "w jedną stronę" if not deal.get("date_in") else "dwie strony",
                         dates, _deal_url(deal)))


def format_digest(deals):
    if not deals:
        raise ValueError('brak ofert do podsumowania')
    body = "\n\n".join(format_deal(i + 1, d) + "\n" + d.get('_description', '')
                       for i, d in enumerate(deals[:MAX_DEALS]))
    return ("✈️ **Najlepsze tanie loty z polskich lotnisk — podsumowanie**\n\n"
            + body +
            "\n\n---\nSkaner & alerty w czasie rzeczywistym: https://polataj.se | "
            "Telegram: https://t.me/polataj_se\n"
            "#polatajse #tanieloty #podroze #tworczoscwlasna #promocje")


def format_hit(deal):
    return ("🔥 **Hit cenowy!**\n\n" + format_deal(1, deal) +
            "\n" + deal.get('_description', '') +
            "\n\n---\nSzczegóły: https://polataj.se/%s/\n"
            "#tanieloty #okazja #polatajse" % deal["port"])


def post(config, content, image=None):
    if not config["enabled"]:
        print("wykop: wyłączony (brak WYKOP_ENABLED=1) — wpis pominięty")
        return None
    token = _user_token(config)
    media = _upload(token, image) if image else None
    return _entry(token, content, media)


def run(config, batch_state, deals, image, is_hit, now):
    """Decyduje i publikuje. Zwraca 'digest'/'hit'/None."""
    if not deals or not config['enabled']:
        return None
    state = _load_state()
    if (is_hit and not can_hit(state, now)) or (not is_hit and not can_digest(state, now)):
        return None
    from hit_detector import description
    deals = [{**d, '_description': description(d)} for d in deals[:1 if is_hit else MAX_DEALS]]
    if is_hit:
        result = post(config, format_hit(deals[0]), image)
        if result:
            state = _load_state()
            state["hit_ts"] = now.timestamp()
            _save_state(state)
            return "hit" if result else None
        return None
    if not can_digest(state, now):
        return None
    result = post(config, format_digest(deals), image)
    if result:
        state = _load_state()
        state["digest_date"] = now.strftime("%Y-%m-%d")
        _save_state(state)
        return "digest" if result else None
    return None
