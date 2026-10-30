import hashlib
import html
import http.client
import json
import os
import re
import threading
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
    if deal.get("trip") == "oneway" or not deal.get("date_in"):
        return "https://polataj.se/%s/#wjedna" % deal["port"]
    return "https://polataj.se/loty/%s-%s/" % (
        slug(deal["origin_city"]), slug(deal["dest_city"]))


def ai_description(deal, dates):
    key = os.environ.get("OPENROUTER_API_KEY") or _env_value("OPENROUTER_API_KEY")
    if not key:
        return None
    prompt = (
        "Napisz krótki, luźny opis okazji lotniczej (2–3 zdania) jak na polskie "
        "forum — naturalny, ciekawy ton. Bez żadnych powitań, zwłaszcza Siemka, "
        "cześć i witajcie. Zacznij od konkretu związanego z miastem docelowym: "
        "atrakcji, klimatu lub pomysłu na pobyt. Nie wymyślaj warunków biletu, "
        "bagażu, rabatów ani presji czasowej. Bez linków i autopromocji, bez "
        "wzmianki o botach lub AI. Dane: %s – %s, %.0f zł %s, termin %s."
        % (deal["origin_city"], deal["dest_city"], deal["price"],
           "w jedną stronę" if deal.get("trip") == "oneway" or not deal.get("date_in") else "w dwie strony",
           ", ".join(d["date_out"] + (" – " + d["date_in"] if d.get("date_in") else "")
                     for d in dates[:3])))
    for model in ("openrouter/auto", "deepseek/deepseek-v4.1-flash-1017"):
        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=json.dumps({"model": model,
                                 "messages": [{"role": "user", "content": prompt}],
                                 "max_tokens": 900, "temperature": 0.9}).encode(),
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                message = json.load(r)["choices"][0]["message"]
            text = (message.get("content") or "").strip()
            if (30 < len(text) < 800 and "http" not in text.lower()
                    and not re.search(r"\b(siemka|cześć|witajcie|hej|dzień dobry)\b", text, re.I)):
                return text
        except (OSError, ValueError, KeyError, IndexError, http.client.HTTPException):
            continue
    return None


def _env_value(name):
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def hit_map_url(deal, root=ROOT):
    try:
        from route_map import render_hit_image
        photo = render_hit_image(deal, root=root)
    except (ImportError, OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
        photo = None
    if photo is None:
        return None, None
    name = "%s-%s-%s.png" % (deal["origin"].lower(), deal["dest"].lower(),
                             hashlib.sha256(photo).hexdigest()[:8])
    url = "https://polataj.se/assets/hits/" + name
    path = root / "docs" / "assets" / "hits" / name
    if path.exists():
        return photo, url
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(photo)
    try:
        from deploy import load_env, ftp_connect, mkdirs
        env = load_env(root / ".env")
        ftp = ftp_connect(env)
        target = env["TL_WEB_DIR"].rstrip("/") + "/polataj/assets/hits"
        mkdirs(ftp, target)
        with open(path, "rb") as f:
            ftp.storbinary("STOR " + target + "/" + name, f)
        ftp.quit()
        return photo, url
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        path.unlink(missing_ok=True)
        return photo, None


def fallback_description(deal):
    variants = (
        "Złapałem super okazję: %s – %s za %.0f zł! Ktoś chętny?",
        "Pomysł na kolejny wyjazd: %s – %s za %.0f zł.",
        "Okazja, by tanio polecieć: %s – %s za %.0f zł.",
        "Loty na trasie %s – %s za %.0f zł — warto sprawdzić podane terminy.",
        "Kolejna perełka cenowa — %s – %s za jedyne %.0f zł!",
    )
    index = int(hashlib.sha256(
        ("%s-%s" % (deal["origin"], deal["dest"])).encode()).hexdigest(), 16) % len(variants)
    return variants[index] % (deal["origin_city"], deal["dest_city"], deal["price"])


_descriptions = {}
_description_lock = threading.Lock()


def description(deal):
    key = tuple(deal.get(k) for k in (
        "origin", "dest", "origin_city", "dest_city", "price", "date_out", "date_in", "trip"))
    with _description_lock:
        if key not in _descriptions:
            _descriptions[key] = ai_description(deal, [deal]) or fallback_description(deal)
        return _descriptions[key]


def pepper_message(deal, map_url=None):
    esc = lambda value: html.escape(str(value))
    oneway = deal.get("trip") == "oneway" or not deal.get("date_in")
    title = "Loty: %s – %s za %.0f zł! (%s)" % (
        deal["origin_city"], deal["dest_city"], deal["price"],
        "w jedną stronę" if oneway else "w dwie strony")
    dates = "\n".join(
        "• %s" % esc(d["date_out"]) if not d.get("date_in")
        else "• %s – %s" % (esc(d["date_out"]), esc(d["date_in"]))
        for d in deal["_dates"][:MAX_DATES])
    image_block = "\n\n<b>OBRAZEK (URL):</b>\n%s" % esc(map_url) if map_url else ""
    return (
        "🔥 <b>HIT NA PEPPER.PL</b> 🔥\n\n"
        "<b>TYTUŁ:</b>\n%s\n\n"
        "<b>CENA:</b>\n%.0f\n\n"
        "<b>LINK:</b>\n%s\n\n"
        "<b>OPIS DO WKLEJENIA:</b>\n%s\n\n"
        "<b>Przykładowe daty:</b>\n%s%s"
        % (esc(title), deal["price"], esc(route_url(deal)),
           esc(description(deal)),
           dates, image_block))


def send_admin_hit(config, deal):
    photo, map_url = hit_map_url(deal)
    text = pepper_message(deal, map_url=map_url)
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
