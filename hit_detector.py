import hashlib
import html
import http.client
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram_alerts import api_call, map_image, process
from tools.build_pages import slug

ROOT = Path(__file__).resolve().parent

ABSOLUTE_MAX = 60.0
DISCOUNT_RATIO = 0.30
MAX_DATES = 3
FRESH_HOURS = 8


def collect_hit_candidates(root, now):
    ports = json.loads((root / "config.json").read_text(encoding="utf-8"))["ports"]
    candidates, stamps = {}, []
    for port, info in ports.items():
        for filename in ("deals.json", "far.json", "oneway.json"):
            path = root / "docs" / port / filename
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            stamp = datetime.fromisoformat(data["generated_at"])
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            stamps.append((port, filename, data["generated_at"]))
            if not now - timedelta(hours=FRESH_HOURS) <= stamp <= now:
                continue
            for deal in data["deals"]:
                if deal["date_out"] <= now.date().isoformat():
                    continue
                key = "%s-%s-%s-%s" % (deal["origin"], deal["dest"],
                                       deal["date_out"], deal.get("date_in"))
                item = {**deal, "port": port, "origin_city": info["city"],
                        "origin_city_gen": info["city_gen"]}
                if key not in candidates or deal["price"] < candidates[key]["price"]:
                    candidates[key] = item
    return hashlib.sha256(json.dumps(stamps).encode()).hexdigest(), candidates


def is_hit(deal):
    price = deal.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        return False
    if price <= ABSOLUTE_MAX:
        return True
    typical = deal.get("typical_price")
    return bool(isinstance(typical, (int, float)) and typical > 0 and
                price <= typical * DISCOUNT_RATIO)


def route_url(deal):
    return "https://polataj.se/loty/%s-%s/" % (
        slug(deal["origin_city"]), slug(deal["dest_city"]))


def ai_description(deal, dates):
    key = os.environ.get("OPENROUTER_API_KEY") or _env_value("OPENROUTER_API_KEY")
    if not key:
        return None
    prompt = (
        "Napisz opis okazji lotniczej w stylu postów na polskim forum Pepper.pl. "
        "Styl: luźny, krótki (2–4 zdania), z entuzjastycznym ale naturalnym tonem "
        "jak 'Super cena za...', 'Okazja by tanio polecieć do...', 'Piękna cena za...'. "
        "Możesz zacząć od powitania typu 'Cześć Pepperki!' lub 'Siemka!'. "
        "Wspomnij przykładowy termin podróży. Bez linków, bez wzmianki o botach/skannerach. "
        "Dane: loty %s – %s za %.0f zł %s, terminy: %s."
        % (deal["origin_city"], deal["dest_city"], deal["price"],
           "w jedną stronę" if deal.get("trip") == "oneway" else "w dwie strony",
           ", ".join(d["date_out"] for d in dates[:3])))
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps({"model": "openrouter/auto",
                             "messages": [{"role": "user", "content": prompt}],
                             "max_tokens": 200}).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            text = json.load(r)["choices"][0]["message"]["content"].strip()
        return text if 30 < len(text) < 800 and "http" not in text else None
    except (OSError, ValueError, KeyError, IndexError, http.client.HTTPException):
        return None


def _env_value(name):
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def pepper_message(deal):
    esc = lambda value: html.escape(str(value))
    oneway = deal.get("trip") == "oneway" or not deal.get("date_in")
    title = "Loty: %s – %s za %.0f zł! (%s)" % (
        deal["origin_city"], deal["dest_city"], deal["price"],
        "w jedną stronę" if oneway else "w dwie strony")
    dates = "\n".join(
        "• %s" % esc(d["date_out"]) if not d.get("date_in")
        else "• %s – %s" % (esc(d["date_out"]), esc(d["date_in"]))
        for d in deal["_dates"][:MAX_DATES])
    return (
        "🔥 <b>HIT NA PEPPER.PL</b> 🔥\n\n"
        "<b>TYTUŁ:</b>\n%s\n\n"
        "<b>CENA:</b>\n%.0f\n\n"
        "<b>LINK:</b>\n%s\n\n"
        "<b>OPIS DO WKLEJENIA:</b>\n%s\n\n"
        "<b>Przykładowe daty:</b>\n%s\n\n"
        "Szybsze alerty o takich błędach cenowych i okazjach wpadają na nasz Telegram: "
        "https://t.me/polataj_se"
        % (esc(title), deal["price"], esc(route_url(deal)),
           esc(ai_description(deal, deal["_dates"]) or
               "Wyszukaliśmy okazję na loty: %s – %s." % (deal["origin_city"], deal["dest_city"])),
           dates))


def send_admin_hit(config, deal):
    text = pepper_message(deal)
    photo = map_image(deal, label="hit-admin", bare=True)
    token = config["TELEGRAM_BOT_TOKEN"]
    chat = config["TELEGRAM_ADMIN_CHAT_ID"]
    if photo is not None:
        if len(text) <= 1024:
            result = api_call(token, "sendPhoto", {
                "chat_id": chat, "caption": text, "parse_mode": "HTML"}, photo=photo)
            return isinstance(result, dict) and bool(result.get("message_id"))
        ok = api_call(token, "sendPhoto", {"chat_id": chat}, photo=photo)
        if not (isinstance(ok, dict) and ok.get("message_id")):
            return False
    result = api_call(token, "sendMessage", {
        "chat_id": chat, "text": text, "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    })
    return isinstance(result, dict) and bool(result.get("message_id"))


def group_hits(candidates):
    hits = [deal for deal in candidates.values() if is_hit(deal)]
    by_route = {}
    for deal in hits:
        key = (deal["origin"], deal["dest"])
        by_route.setdefault(key, []).append(deal)
    selected = {}
    for key, deals in by_route.items():
        deals.sort(key=lambda d: (d["price"], d["date_out"]))
        best = {**deals[0], "_dates": deals}
        selected["%s-%s-%s-%s" % (key[0], key[1], best["date_out"], best["date_in"])] = best
    return selected


def publish_admin_hits(config, batch, candidates, state_path, now):
    if not config.get("TELEGRAM_ADMIN_CHAT_ID"):
        return 0
    hits = group_hits(candidates)
    target = {**config, "RECIPIENT_ID": "admin:%s" % config["TELEGRAM_ADMIN_CHAT_ID"],
              "TELEGRAM_CHANNEL_ID": config["TELEGRAM_ADMIN_CHAT_ID"]}
    return process(target, batch, hits, state_path, now,
                   sender=send_admin_hit, label="hit-admin")
