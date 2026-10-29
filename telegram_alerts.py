import argparse
import fcntl
import hashlib
import html
import http.client
import json
import math
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAX_PRICE = 200
MAX_MESSAGES = 3


def load_config():
    values = {}
    path = ROOT / "telegram" / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    config = {k: os.environ.get(k, values.get(k, "")) for k in
              ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID", "TELEGRAM_ENABLED",
               "TELEGRAM_ADMIN_CHAT_ID")}
    config["TELEGRAM_CHANNEL_ID"] = config["TELEGRAM_CHANNEL_ID"] or os.environ.get(
        "TELEGRAM_CHAT_ID", values.get("TELEGRAM_CHAT_ID", ""))
    return config


def api_call(token, method, payload, photo=None):
    content_type = "application/json"
    body = json.dumps(payload).encode("utf-8")
    if photo is not None:
        boundary = "polataj_" + os.urandom(16).hex()
        parts = []
        for key, value in payload.items():
            parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                          % (boundary, key, value)).encode("utf-8"))
        parts.append(('--%s\r\nContent-Disposition: form-data; name="photo"; '
                      'filename="trasa.png"\r\nContent-Type: image/png\r\n\r\n'
                      % boundary).encode("utf-8") + photo + b'\r\n')
        body = b''.join(parts) + ('--%s--\r\n' % boundary).encode("utf-8")
        content_type = "multipart/form-data; boundary=" + boundary
    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/%s" % (token, method),
        data=body, headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=30 if photo is not None else 15) as response:
            result = json.load(response)
        if not isinstance(result, dict):
            print("telegram: nieprawidłowa odpowiedź API")
            return None
        if result.get("ok"):
            return result.get("result")
        print("telegram: API odrzuciło żądanie (%s)" % result.get("error_code"))
    except urllib.error.HTTPError as exc:
        if exc.code == 400 and method in ("editMessageText", "editMessageReplyMarkup"):
            try:
                error = json.loads(exc.read(16384))
                if "message is not modified" in error.get("description", ""):
                    return True
            except (OSError, ValueError, AttributeError):
                pass
        print("telegram: błąd HTTP %d" % exc.code)
    except (OSError, ValueError, http.client.HTTPException):
        print("telegram: błąd połączenia lub odpowiedzi API")
    return None


def format_alert(deal):
    esc = lambda value: html.escape(str(value), quote=True)
    return (
        '<b>NOWA OKAZJA: %s → %s</b>\n\n'
        '<b>Cena:</b> %.2f zł (w dwie strony)\n'
        '<b>Termin:</b> %s – %s\n'
        '<b>Lotniska:</b> %s → %s\n'
        '%s\n'
        '<a href="https://polataj.se/%s/">Zobacz okazje na polataj.se</a>'
        % (esc(deal["origin_city"]), esc(deal["dest_city"]), deal["price"],
           esc(deal["date_out"]), esc(deal["date_in"]),
           esc(deal["origin"]), esc(deal["dest"]),
           ('<b>Linia:</b> %s\n' % esc(deal["airline"])) if deal.get("airline") else '',
           esc(deal["port"]))
    )


def map_image(deal, label="telegram", bare=False):
    if not deal.get("dest_geo"):
        return None
    try:
        from route_map import render_route_map
        return render_route_map(deal, bare=bare)
    except (ImportError, OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
        print("%s: mapka niedostępna — wysyłam sam tekst" % label)
        return None


def send_alert(config, deal):
    text = format_alert(deal)
    photo = map_image(deal) if len(text) <= 1024 else None
    if photo is not None:
        result = api_call(config["TELEGRAM_BOT_TOKEN"], "sendPhoto", {
            "chat_id": config["TELEGRAM_CHANNEL_ID"], "caption": text,
            "parse_mode": "HTML",
        }, photo=photo)
    else:
        result = api_call(config["TELEGRAM_BOT_TOKEN"], "sendMessage", {
            "chat_id": config["TELEGRAM_CHANNEL_ID"], "text": text,
            "parse_mode": "HTML", "link_preview_options": {"is_disabled": True},
        })
    ok = isinstance(result, dict) and bool(result.get("message_id"))
    if ok and photo is not None:
        print("telegram: mapka wysłana, message_id=%s" % result["message_id"])
    return ok


def collect_candidates(root, now):
    ports = json.loads((root / "config.json").read_text(encoding="utf-8"))["ports"]
    candidates, stamps = {}, []
    for port, info in ports.items():
        for filename in ("deals.json", "far.json"):
            path = root / "docs" / port / filename
            data = json.loads(path.read_text(encoding="utf-8"))
            stamp = datetime.fromisoformat(data["generated_at"])
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            stamps.append((port, filename, data["generated_at"]))
            if not now - timedelta(hours=8) <= stamp <= now:
                continue
            for deal in data["deals"]:
                price = deal.get("price")
                if (deal.get("record_low") is not True or
                        isinstance(price, bool) or not isinstance(price, (int, float)) or
                        not math.isfinite(price) or not 0 < price <= MAX_PRICE or
                        not deal.get("date_in") or
                        deal.get("trip") == "oneway" or
                        deal["date_out"] <= now.date().isoformat()):
                    continue
                key = "%s-%s-%s-%s" % (deal["origin"], deal["dest"],
                                        deal["date_out"], deal["date_in"])
                item = {**deal, "port": port, "origin_city": info["city"]}
                if key not in candidates or price < candidates[key]["price"]:
                    candidates[key] = item
    batch = hashlib.sha256(json.dumps(stamps).encode()).hexdigest()
    return batch, candidates


def process(config, batch, candidates, state_path, now, sender=send_alert,
            allowed_ports=None, allow_deal=None, label="telegram"):
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with sqlite3.connect(state_path) as db:
            state_path.chmod(0o600)
            db.execute("CREATE TABLE IF NOT EXISTS deals ("
                       "channel TEXT, id TEXT, payload TEXT, seen_at TEXT, "
                       "sent INTEGER DEFAULT 0, PRIMARY KEY(channel,id))")
            db.execute("CREATE TABLE IF NOT EXISTS batches ("
                       "channel TEXT, batch TEXT, attempts INTEGER DEFAULT 0, "
                       "PRIMARY KEY(channel,batch))")
            channel = config.get("RECIPIENT_ID") or config["TELEGRAM_CHANNEL_ID"]
            for key, deal in candidates.items():
                db.execute("INSERT INTO deals(channel,id,payload,seen_at) VALUES(?,?,?,?) "
                           "ON CONFLICT(channel,id) DO UPDATE SET "
                           "payload=excluded.payload,seen_at=excluded.seen_at",
                           (channel, key, json.dumps(deal), now.isoformat()))
            db.execute("INSERT OR IGNORE INTO batches(channel,batch) VALUES(?,?)",
                       (channel, batch))
            db.commit()
            attempts = db.execute("SELECT attempts FROM batches WHERE channel=? AND batch=?",
                                  (channel, batch)).fetchone()[0]
            pending = db.execute("SELECT id,payload,seen_at FROM deals WHERE channel=? AND sent=0",
                                 (channel,)).fetchall()
            pending = [(key, json.loads(payload)) for key, payload, seen_at in pending
                       if datetime.fromisoformat(seen_at) >= now - timedelta(hours=24)]
            pending = [(key, deal) for key, deal in pending
                       if deal["date_out"] > now.date().isoformat()]
            sent = 0
            for key, deal in sorted(pending, key=lambda item: (item[1]["price"], item[0])):
                if allowed_ports is not None and deal.get("port") not in allowed_ports:
                    continue
                if allow_deal is not None and not allow_deal(deal):
                    continue
                if attempts >= MAX_MESSAGES:
                    break
                attempts += 1
                db.execute("UPDATE batches SET attempts=? WHERE channel=? AND batch=?",
                           (attempts, channel, batch))
                db.commit()
                if not sender(config, deal):
                    print("%s: wysyłka niepotwierdzona, ponowienie w następnym przebiegu" % label)
                    break
                db.execute("UPDATE deals SET sent=1 WHERE channel=? AND id=?", (channel, key))
                db.commit()
                sent += 1
                print("%s: wysłano %s" % (label, key))
            return sent


def publish_private(config, batch, candidates, state_path, now, subscribers_path=None,
                    sender=send_alert):
    from telegram_bot import STATE, active_subscribers, read_subscriber
    subscribers_path = subscribers_path or STATE
    sent = 0
    for chat_id, ports in active_subscribers(subscribers_path):
        selected = {key: deal for key, deal in candidates.items() if deal.get("port") in ports}
        def still_subscribed(deal, recipient=chat_id):
            current = read_subscriber(recipient, subscribers_path)
            return bool(current and not current[1] and deal.get("port") in current[0])
        target = {**config, "TELEGRAM_CHANNEL_ID": str(chat_id)}
        sent += process(target, batch, selected, state_path, now, sender,
                        allowed_ports=ports, allow_deal=still_subscribed)
    return sent


def check_config(config):
    token = config["TELEGRAM_BOT_TOKEN"]
    bot = api_call(token, "getMe", {})
    chat = api_call(token, "getChat", {"chat_id": config["TELEGRAM_CHANNEL_ID"]})
    if not bot or not chat:
        return False
    member = api_call(token, "getChatMember", {
        "chat_id": chat["id"], "user_id": bot["id"]})
    allowed = bool(member and (member.get("status") == "creator" or
                   (member.get("status") == "administrator" and
                    member.get("can_post_messages") is True)))
    print("telegram: bot=@%s, kanał=%s, publikowanie=%s" % (
        bot["username"], config["TELEGRAM_CHANNEL_ID"], "OK" if allowed else "BRAK"))
    return allowed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--state", type=Path, default=ROOT / "data/cache/telegram.sqlite")
    args = parser.parse_args()
    config = load_config()
    if not config["TELEGRAM_BOT_TOKEN"] or not config["TELEGRAM_CHANNEL_ID"]:
        print("telegram: brak TELEGRAM_BOT_TOKEN lub TELEGRAM_CHANNEL_ID")
        return 1
    if args.check:
        return 0 if check_config(config) else 1
    now = datetime.now(timezone.utc)
    batch, candidates = collect_candidates(ROOT, now)
    if not args.send and not (args.auto and config["TELEGRAM_ENABLED"] == "1"):
        print("telegram: dry-run, %d rekordów do 200 zł; limit %d na przebieg" %
              (len(candidates), MAX_MESSAGES))
        return 0
    count = process(config, batch, candidates, args.state, now)
    print("telegram: wysłano %d alertów na kanał" % count)
    private_count = publish_private(config, batch, candidates, args.state, now)
    print("telegram: wysłano %d prywatnych alertów" % private_count)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, sqlite3.Error):
        print("telegram: błąd danych lub stanu; pipeline może kontynuować")
        raise SystemExit(1)
