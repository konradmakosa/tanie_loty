import fcntl
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from telegram_alerts import api_call, load_config

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "data/cache/telegram_subscribers.sqlite"


def open_store(path=STATE):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    path.chmod(0o600)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(
        "CREATE TABLE IF NOT EXISTS subscribers (chat_id INTEGER PRIMARY KEY, "
        "ports TEXT NOT NULL DEFAULT '[]', paused INTEGER NOT NULL DEFAULT 0);"
        "CREATE TABLE IF NOT EXISTS bot_state (id INTEGER PRIMARY KEY, cursor INTEGER);"
        "INSERT OR IGNORE INTO bot_state VALUES(1,-1);"
        "CREATE TABLE IF NOT EXISTS outbox (update_id INTEGER PRIMARY KEY, chat_id INTEGER, "
        "method TEXT, payload TEXT, attempts INTEGER DEFAULT 0, retry_at REAL DEFAULT 0);")
    return db


def read_subscriber(chat_id, path=STATE):
    with closing(open_store(path)) as db:
        row = db.execute("SELECT ports,paused FROM subscribers WHERE chat_id=?", (chat_id,)).fetchone()
    return (set(json.loads(row[0])), bool(row[1])) if row else None


def active_subscribers(path=STATE):
    with closing(open_store(path)) as db:
        return [(row[0], set(json.loads(row[1]))) for row in
                db.execute("SELECT chat_id,ports FROM subscribers WHERE paused=0")
                if json.loads(row[1])]


def city_label(port, info):
    airports = "WAW · WMI · RDO" if port == "zwarszawy" else " · ".join(info["airports"])
    return "%s — %s" % (info["city"], airports)


def menu(ports, selected, paused):
    labels = [info["city"] for port, info in ports.items() if port in selected]
    text = ("polataj.se — Twoje prywatne alerty\n\n"
            "Kliknij jedno lub kilka miast. Wybór zapisuje się od razu.\n"
            "Warszawa obejmuje Okęcie (WAW), Modlin (WMI) i Radom (RDO).\n\n"
            "Wybrane: %s\nStan: %s\n\n"
            "Tylko nowe rekordy do 200 zł w obie strony; maksymalnie 3 oferty "
            "łącznie z Twoich miast po skanie co 6 h. Jeśli nie ma okazji, nie piszę.\n\n"
            "Zapisuję ID czatu i wybór miast do obsługi alertów. "
            "/lotniska — zmiana wyboru, /pauza, /wznow, /wypisz — usunięcie subskrypcji."
            % (", ".join(labels) or "jeszcze nic — zaznacz miasto poniżej",
               "wstrzymane" if paused else "włączone" if selected else "czeka na wybór miasta"))
    buttons = [[{"text": ("[x] " if port in selected else "[ ] ") + city_label(port, info),
                 "callback_data": "port:" + port}] for port, info in ports.items()]
    buttons.append([{"text": "Wznów alerty" if paused else "Wstrzymaj alerty",
                     "callback_data": "resume" if paused else "pause"},
                    {"text": "Wypisz mnie", "callback_data": "unsubscribe"}])
    return text, {"inline_keyboard": buttons}


def apply_update(db, update, ports):
    update_id = update["update_id"]
    callback = update.get("callback_query")
    message = (callback or {}).get("message") or update.get("message") or {}
    chat = message.get("chat", {})
    with db:
        cursor = db.execute("SELECT cursor FROM bot_state WHERE id=1").fetchone()[0]
        if update_id <= cursor:
            return
        db.execute("UPDATE bot_state SET cursor=? WHERE id=1", (update_id,))
        if (chat.get("type") != "private" or not isinstance(chat.get("id"), int) or
                (callback and callback.get("from", {}).get("id") != chat["id"])):
            return
        chat_id = chat["id"]
        command = message.get("text", "").split(maxsplit=1)[0].split("@")[0] if message.get("text") else ""
        action = callback.get("data", "") if callback else command
        row = db.execute("SELECT ports,paused FROM subscribers WHERE chat_id=?", (chat_id,)).fetchone()
        selected, paused = (set(json.loads(row[0])) & set(ports), bool(row[1])) if row else (set(), False)
        if action == "/start":
            db.execute("INSERT OR IGNORE INTO subscribers(chat_id) VALUES(?)", (chat_id,))
            row = True
        if action in ("/wypisz", "unsubscribe"):
            db.execute("DELETE FROM subscribers WHERE chat_id=?", (chat_id,))
            text, keyboard = "Usunięto subskrypcję. Nie dostaniesz kolejnych alertów. Powrót: /start.", {"inline_keyboard": []}
        elif not row:
            text, keyboard = "Wyślij /start, aby wybrać miasta i uruchomić prywatne alerty.", {"inline_keyboard": []}
        else:
            if action.startswith("port:") and action[5:] in ports:
                port = action[5:]
                selected.symmetric_difference_update({port})
            elif action in ("/pauza", "/stop", "pause"):
                paused = True
            elif action in ("/wznow", "resume"):
                paused = False
            db.execute("UPDATE subscribers SET ports=?,paused=? WHERE chat_id=?",
                       (json.dumps(sorted(selected)), int(paused), chat_id))
            text, keyboard = menu(ports, selected, paused)
        payload = {"chat_id": chat_id, "text": text, "reply_markup": keyboard,
                   "link_preview_options": {"is_disabled": True}}
        method = "sendMessage"
        if callback:
            payload["message_id"] = message["message_id"]
            method = "editMessageText"
        db.execute("DELETE FROM outbox WHERE chat_id=?", (chat_id,))
        db.execute("INSERT INTO outbox(update_id,chat_id,method,payload) VALUES(?,?,?,?)",
                   (update_id, chat_id, method, json.dumps(payload)))


def flush_outbox(db, token, api=api_call):
    rows = db.execute("SELECT update_id,method,payload,attempts FROM outbox "
                      "WHERE attempts<10 AND retry_at<=? ORDER BY update_id LIMIT 25", (time.time(),)).fetchall()
    for update_id, method, payload, attempts in rows:
        result = api(token, method, json.loads(payload))
        with db:
            if result is not None:
                db.execute("DELETE FROM outbox WHERE update_id=?", (update_id,))
                print("telegram-bot: menu dostarczone", flush=True)
            else:
                db.execute("UPDATE outbox SET attempts=attempts+1,retry_at=? WHERE update_id=?",
                           (time.time() + min(300, 5 * 2 ** attempts), update_id))
                print("telegram-bot: odpowiedź niepotwierdzona, zaplanowano ponowienie", flush=True)


def main():
    config = load_config()
    token = config["TELEGRAM_BOT_TOKEN"]
    if not token:
        raise RuntimeError("brak tokenu bota")
    ports = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["ports"]
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with STATE.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        webhook = api_call(token, "getWebhookInfo", {})
        if webhook is None or webhook.get("url"):
            raise RuntimeError("nie potwierdzono braku webhooka — polling nie został uruchomiony")
        with open_store() as db:
            print("telegram-bot: obsługa prywatnych wiadomości uruchomiona", flush=True)
            while True:
                flush_outbox(db, token)
                cursor = db.execute("SELECT cursor FROM bot_state WHERE id=1").fetchone()[0]
                updates = api_call(token, "getUpdates", {"offset": cursor + 1, "timeout": 10, "limit": 50,
                                                       "allowed_updates": ["message", "callback_query"]})
                if updates is None:
                    time.sleep(5)
                    continue
                for update in updates:
                    apply_update(db, update, ports)
                    callback_id = update.get("callback_query", {}).get("id")
                    if callback_id:
                        api_call(token, "answerCallbackQuery", {"callback_query_id": callback_id})
                flush_outbox(db, token)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error):
        print("telegram-bot: błąd konfiguracji, stanu lub uruchomienia; szczegóły prywatne nie są logowane", flush=True)
        raise SystemExit(1)
