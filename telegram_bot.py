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
    with db:
        db.execute("BEGIN IMMEDIATE")
        if "draft_ports" not in {row[1] for row in db.execute("PRAGMA table_info(subscribers)")}:
            db.execute("ALTER TABLE subscribers ADD COLUMN draft_ports TEXT")
        db.execute("UPDATE subscribers SET draft_ports=ports WHERE draft_ports IS NULL")
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


def city_names(ports, selected):
    return ", ".join(info["city"] for port, info in ports.items() if port in selected) or "jeszcze żadne"


def menu(ports, selected, paused, draft=None):
    draft = selected if draft is None else draft
    text = ("Skąd chcesz łapać tanie loty?\n\n"
            "Wybierz jedno lub kilka miast, a ja znajdę okazje za Ciebie "
            "i wyślę je tutaj — z ceną, terminem i mapką trasy.\n\n"
            "Warszawa obejmuje Okęcie (WAW), Modlin (WMI) i Radom (RDO).\n\n"
            "Twój wybór do zapisania: %s\n"
            "Aktualnie zapisane miasta: %s\n\n"
            "Zatwierdź przyciskiem poniżej. Dopiero potwierdzenie zmienia zapis.\n"
            "Tylko rekordy do 200 zł w obie strony, maksymalnie 3 okazje po skanie co 6 h.\n"
            "polataj.se — zapisuję ID czatu i wybór miast do obsługi alertów."
            % (city_names(ports, draft), city_names(ports, selected)))
    if paused:
        text += "\nAlerty są wstrzymane; zapisanie wyboru je wznowi."
    buttons = [[{"text": ("[x] " if port in draft else "[ ] ") + city_label(port, info),
                 "callback_data": "port:" + port}] for port, info in ports.items()]
    buttons.append([{"text": "Zapisz i łap okazje" + (" (%d)" % len(draft) if draft else ""),
                     "callback_data": "save"}])
    if selected:
        buttons.append([{"text": "Ustawienia", "callback_data": "settings"}])
    return text, {"inline_keyboard": buttons}


def confirmed_menu(ports, selected, paused):
    if not selected:
        return menu(ports, selected, paused)
    text = ("Gotowe! Twoje miasta są zapisane.\n\n"
            "%s\n\nNie musisz już śledzić cen — odezwę się, gdy pojawi się "
            "nowy rekord do 200 zł w obie strony. Dostaniesz ofertę z mapką trasy.\n"
            "Skanuję co 6 h i wysyłam maksymalnie 3 okazje z Twoich miast na przebieg."
            % city_names(ports, selected))
    if paused:
        text += "\n\nAlerty są teraz wstrzymane; możesz je wznowić w ustawieniach."
    return text, {"inline_keyboard": [
        [{"text": "Zmień moje miasta", "callback_data": "ports"}],
        [{"text": "Ustawienia", "callback_data": "settings"}],
    ]}


def settings_menu(ports, selected, paused):
    text = ("Twoje ustawienia alertów\n\nMiasta: %s\nStan: %s\n\n"
            "Możesz zrobić przerwę bez utraty wybranych miast."
            % (city_names(ports, selected), "wstrzymane" if paused else "aktywne" if selected else "czekam na wybór miast"))
    return text, {"inline_keyboard": [
        [{"text": "Wznów łapanie okazji" if paused else "Wstrzymaj na chwilę",
          "callback_data": "resume" if paused else "pause"}],
        [{"text": "Wróć do moich okazji", "callback_data": "home"}],
    ]}


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
        row = db.execute("SELECT ports,paused,draft_ports FROM subscribers WHERE chat_id=?", (chat_id,)).fetchone()
        selected, paused = (set(json.loads(row[0])) & set(ports), bool(row[1])) if row else (set(), False)
        draft = set(json.loads(row[2] or row[0])) & set(ports) if row else set()
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
                draft.symmetric_difference_update({action[5:]})
            elif action == "save" and draft:
                selected, paused = draft.copy(), False
            elif action in ("/pauza", "/stop", "pause"):
                paused = True
            elif action in ("/wznow", "resume"):
                paused = False
            db.execute("UPDATE subscribers SET ports=?,paused=?,draft_ports=? WHERE chat_id=?",
                       (json.dumps(sorted(selected)), int(paused), json.dumps(sorted(draft)), chat_id))
            if action in ("settings", "/pauza", "/stop", "pause", "/wznow", "resume"):
                text, keyboard = settings_menu(ports, selected, paused)
            elif (action == "save" and draft) or (action in ("home", "/start") and selected):
                text, keyboard = confirmed_menu(ports, selected, paused)
            else:
                text, keyboard = menu(ports, selected, paused, draft)
                if action == "save":
                    text = "Wybierz najpierw przynajmniej jedno miasto.\n\n" + text
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
