#!/usr/bin/env python3
"""Radar okazji do komentowania — skaner wątków (FB/Reddit/fora).

Szuka świeżych publicznych wątków, w których ludzie pytają o loty,
przesiadki, bagaż, kierunki — bez scrapowania konta (Serper.dev /
Google CSE + oficjalny JSON Reddita). Każdy wynik ocenia Gemini
(przez OpenRouter): is_relevant / score / streszczenie / szkic
komentarza. Wyniki trafiają POST-em do panel-radar/api.php na
polataj.se (nagłówek X-Ingest-Key jak reszta integracji VPS→home.pl).

Użycie:
  python3 tools/radar_scan.py              # pełny skan + upload
  python3 tools/radar_scan.py --dry-run    # bez uploadu, podgląd
  python3 tools/radar_scan.py --if-requested  # skan tylko gdy flaga
                                             # z panelu czeka

Stan: data/cache/radar.sqlite (deduplikacja URL-i).
Konfiguracja zapytań: pobierana z panelu (api.php?action=queries),
fallback na tools/radar_queries.json w repo.

Env: SERPER_API_KEY (google.serper.dev), OPENROUTER_API_KEY,
     TL_INGEST_KEY, opcjonalnie RADAR_API_URL.
"""
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from deploy import load_env  # noqa: E402

ENV_PATH = ROOT / ".env"
DB_PATH = ROOT / "data" / "cache" / "radar.sqlite"
DEFAULT_QUERIES = ROOT / "tools" / "radar_queries.json"

RADAR_API = "https://polataj.se/panel-radar/api.php"
SERPER_URL = "https://google.serper.dev/search"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_MODEL = "google/gemini-2.5-flash"
REDDIT_UA = "polataj.se radar (kontakt: kontakt@polataj.se)"

MAX_RESULTS_PER_QUERY = 10
MAX_GEMINI_PER_SCAN = 15
HTTP_TIMEOUT = 25
MAX_ITEM_AGE_DAYS = 14

# Deterministyczny filtr odsprzedaży biletów — LLM przepuszczał takie
# posty z wysokim score („sprzedam", „przepiszę" to NIE prośba o poradę).
RESALE_RE = re.compile(
    r"sprzedam|odsprzedam|odst\w*pi|przepisz\w*|przepisani\w*|"
    r"zmian\w*\s+nazwisk\w*|na inne nazwisk\w*|"
    r"bilet\w*\s+na\s+sprzeda|na\s+stronie\s+przew\w*nik", re.I)


def is_resale(text):
    # nagłówki grup „kupię / sprzedam" nie są treścią posta — wycinamy
    t = re.sub(r"(sprzedam|kupi[eę])\s*/\s*(sprzedam|kupi[eę])", "",
               text, flags=re.I)
    return bool(RESALE_RE.search(t))


# Deterministyczny filtr postów promo/ofertowych — oferty biur,
# deal-posty z emotkami itp. LLM przepuszcza je z wysokim score.
PROMO_RE = re.compile(
    r"ostatnie wolne miejsca|dost\w*pne terminy|w komentarzu r\w*nie\w*|"
    r"biuro podr\w*|zapraszam\w*\s+(do\s+)?(rezerw|kontakt|priv|"
    r"wsp\w*prac)|oferta wa\w*na|przew\w*z\s+os\w*b|"
    r"miejsca\s+na\s+inne\s+termin|odkupieni|"
    r"powitajmy|nowych cz\w*onk\w*|do\w*cz do naszej grupy", re.I)
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿⬅-⯿️]")
TITLE_JUNK = {"other posts", "posty", "ogłoszenia"}


def is_promo(text):
    return bool(PROMO_RE.search(text)) or len(EMOJI_RE.findall(text)) >= 3


def skip_post(item):
    if (item.get("title") or "").strip().lower() in TITLE_JUNK:
        return True             # artefakt Serpera — brak właściwego tytułu
    t = (item.get("title") or "") + " " + (item.get("snippet") or "")
    return is_resale(t) or is_promo(t)


def ck(item):
    """Klucz treści do deduplikacji — ten sam post wraca pod
    różnymi owijkami google.com/goto, więc URL nie wystarcza."""
    t = re.sub(r"\W+", " ", (item.get("title") or "").lower()).strip()
    return "title:" + hashlib.sha1(t.encode("utf-8")).hexdigest()[:16]


# ---------- pomocnicze ----------

def env_get(key):
    return os.environ.get(key) or load_env(ENV_PATH).get(key)


def http_json(url, payload=None, headers=None, method=None,
              timeout=HTTP_TIMEOUT, gz=False):
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = dict(headers or {})
        headers.setdefault("Content-Type", "application/json")
        if gz:
            import gzip as gz_mod
            data = gz_mod.compress(data)
            headers["Content-Encoding"] = "gzip"
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.execute("""CREATE TABLE IF NOT EXISTS seen(
        url TEXT PRIMARY KEY,
        source TEXT,
        first_seen TEXT,
        scored INTEGER DEFAULT 0)""")
    return c


def seen_urls(conn):
    return {r[0] for r in conn.execute("SELECT url FROM seen")}


# ---------- źródła ----------

def search_serper(query, tbs, key):
    """Serper.dev — organic + data tbs (qdr:d / qdr:w)."""
    out = []
    try:
        d = http_json(SERPER_URL,
                      {"q": query, "gl": "pl", "hl": "pl",
                       "num": MAX_RESULTS_PER_QUERY,
                       "tbs": tbs or "qdr:w"},
                      headers={"X-API-KEY": key})
    except Exception as e:
        print("serper błąd: %s" % e, file=sys.stderr)
        return out
    for o in d.get("organic") or []:
        link = o.get("link") or ""
        if not link.startswith("http"):
            continue
        out.append({"url": link, "title": o.get("title") or "",
                    "snippet": o.get("snippet") or "",
                    "date": o.get("date") or "",
                    "source": source_from_url(link)})
    return out


def source_from_url(url):
    if "facebook.com" in url:
        return "facebook"
    if "reddit.com" in url:
        return "reddit"
    return "forum/www"


def collect_routes():
    """Trasy z własnymi stronami /loty/<port>-<dest>/ — faktyczne
    pokrycie serwisu (ground truth do relewancji i linków)."""
    m = {}
    loty = ROOT / "docs" / "loty"
    if not loty.is_dir():
        return m
    for d in loty.iterdir():
        if not d.is_dir() or "-" not in d.name:
            continue
        port, dest = d.name.split("-", 1)
        m.setdefault(port, []).append(dest)
    return {p: sorted(v) for p, v in m.items()}


def coverage_text(routes):
    """'warszawa: teneryfa, malaga; krakow: …' — zwarty opis pokrycia."""
    return "; ".join("%s: %s" % (p, ", ".join(ds))
                     for p, ds in sorted(routes.items()))


def reddit_token(cid, secret):
    """OAuth client_credentials — apka 'script' z reddit.com/prefs/apps."""
    import base64
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=urllib.parse.urlencode(
            {"grant_type": "client_credentials"}).encode(),
        headers={"Authorization": "Basic " + base64.b64encode(
            (cid + ":" + secret).encode()).decode(),
            "User-Agent": REDDIT_UA})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))["access_token"]


def search_reddit(sub, q, token=None):
    """JSON Reddita — wymaga tokenu OAuth (bez niego 403 na
    adresach DC). Bez tokenu zwraca [] — Reddit pokrywają
    wtedy zapytania site:reddit.com przez Serper."""
    if not token:
        return []
    url = ("https://oauth.reddit.com/r/%s/search?q=%s&restrict_sr=1"
           "&sort=new&t=week&limit=%d"
           % (sub, urllib.parse.quote(q), MAX_RESULTS_PER_QUERY))
    out = []
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": REDDIT_UA, "Authorization": "Bearer " + token})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print("reddit r/%s błąd: %s" % (sub, e), file=sys.stderr)
        return out
    for ch in (d.get("data") or {}).get("children") or []:
        p = ch.get("data") or {}
        permalink = p.get("permalink") or ""
        if not permalink:
            continue
        out.append({"url": "https://www.reddit.com" + permalink,
                    "title": p.get("title") or "",
                    "snippet": (p.get("selftext") or "")[:400],
                    "date": datetime.fromtimestamp(
                        p.get("created_utc") or 0,
                        tz=timezone.utc).date().isoformat(),
                    "source": "reddit"})
    return out


# ---------- Gemini (OpenRouter) ----------

SCORE_PROMPT = """Oceniasz publiczny wątek internetowy pod kątem naturalnego, \
pomocnego komentarza z linkiem do polataj.se (polski skaner tanich lotów \
z polskich lotnisk: Warszawa, Kraków, Gdańsk, Poznań, Wrocław, Katowice). \
Serwis pokrywa głównie EUROPĘ (Ryanair, Wizz, easyJet, LOT) + wybrane \
dalekie okazje.

Aktualne strony tras serwisu (slugi /loty/<port>-<dest>/):
{routes}

Wątek:
Tytuł: {title}
Źródło: {source}
Treść/snippet: {snippet}

Odpowiedz WYŁĄCZNIE poprawnym JSON-em (bez markdown, bez komentarza):
{{
 "is_relevant": true|false,
 "relevance_score": 1-10,
 "variants": [
  {{"style": "koleżeńska", "text": "1-2 zdania, luźno, jak znajomy"}},
  {{"style": "merytoryczna", "text": "najpierw konkretna pomoc, \
potem nienachalny link"}},
  {{"style": "konkretna", "text": "wplata pasującą podstronę polataj.se"}}
 ]
}}

Reguły is_relevant=false: reklama, spam, oferta biura podróży lub linii, \
post konkurencyjnego serwisu okazji, ref-link, treść niezwiązana \
z podróżami lotniczymi, język inny niż polski (chyba że wyraźnie Polak), \
ODSPRZEDAŻ/PRZEPISANIE biletów lub ogłoszenie „sprzedam/odstąpię/ \
przepiszę bilety" (to nie prośba o poradę — autor już ma bilety). \
is_relevant=true tylko gdy realna osoba prosi o poradę/inspirację \
dotyczącą lotów.

relevance_score oceń pod kątem dopasowania do pokrycia serwisu: \
kierunek z listy tras lub ogólne „tanie loty z Polski/w Europie" \
→ wysoki score (7-10); kierunek egzotyczny/daleki SPOZA listy \
(Azja, USA, Australia, Ameryki) → max 4 — serwis rzadko tam pomoże, \
chyba że pytanie jest ogólne o metodę szukania okazji. \
Ważne: wątek dotyczący wylotu WYŁĄCZNIE z miasta spoza naszych 6 \
portów (np. Rzeszów, Szczecin, Łódź, Lublin, Bydgoszcz, Radom, \
Olsztyn, Zielona Góra) → max 4, chyba że autor wprost dopuszcza \
wylot z naszego portu lub pyta ogólnie.

variants: trzy RÓŻNE wersje komentarza do tego wątku z linkiem do \
polataj.se. Linki ZAWSZE pełne, z https:// (https://polataj.se, \
https://polataj.se/loty/…, https://polataj.se/zwarszawy/…) — \
sam „polataj.se" nie zamienia się w klikalny link na forum/FB. \
„koleżeńska" — 1-2 zdania, bardzo krótka (styl np. \
„Wyszukasz tu https://polataj.se — skanują tanie loty \
z polskich lotnisk"). \
„merytoryczna" — 2-3 zdania: najpierw konkretna pomoc z pytaniem \
autora, potem nienachalny link jako narzędzie. \
„konkretna" — wplata pasujący pełny URL do wątku: trasę \
https://polataj.se/loty/<port>-<dest>/ WYŁĄCZNIE gdy para \
port-dest jest na liście tras powyżej (użyj dokładnego sluga), \
port https://polataj.se/zwarszawy/ /zkrakowa/ /zgdanska/ \
/zpoznania/ /zwroclawia/ /zkatowic/ albo samo https://polataj.se. \
Jeśli wylot w wątku jest z miasta SPOZA tych 6 portów — nie \
wciskaj trasy/portu, użyj samo https://polataj.se. \
Każda max 3 zdania."""


def score_item(item, key, routes_text=""):
    """Gemini: is_relevant/score/variants albo None."""
    prompt = SCORE_PROMPT.format(
        routes=routes_text or "(brak danych o trasach)",
        title=item["title"][:300], source=item["source"],
        snippet=item["snippet"][:900])
    try:
        d = http_json(OPENROUTER_URL, {
            "model": GEMINI_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1100, "temperature": 0.4},
            headers={"Authorization": "Bearer " + key})
        text = (d["choices"][0]["message"].get("content") or "").strip()
    except Exception as e:
        print("gemini błąd: %s" % e, file=sys.stderr)
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        j = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(j.get("is_relevant"), bool):
        return None
    return j


# ---------- panel API ----------

def api_call(action, key, payload=None, method=None, gz=False):
    """Zapytanie do panel-radar/api.php (X-Ingest-Key)."""
    url = RADAR_API + "?action=" + action
    return http_json(url, payload, method=method, gz=gz,
                     headers={"X-Ingest-Key": key})


def load_queries(key):
    """Zapytania z panelu; fallback na plik w repo."""
    try:
        d = api_call("queries", key)
        if d.get("queries") is not None:
            print("radar: zapytania z panelu")
            return d
    except Exception as e:
        print("radar: panel queries niedostępne (%s) — fallback repo"
              % e, file=sys.stderr)
    return json.loads(DEFAULT_QUERIES.read_text(encoding="utf-8"))


def scan_requested(key):
    try:
        return bool(api_call("scan_flag", key).get("pending"))
    except Exception:
        return False


def _clean(o):
    """Usuwa niewłaściwe znaki UTF-8 (samotne surogaty itp.) —
    PHP json_decode zwraca null na takich stringach → 400."""
    if isinstance(o, str):
        return o.encode("utf-8", "ignore").decode("utf-8")
    if isinstance(o, list):
        return [_clean(x) for x in o]
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    return o


def upload(items, key, routes=None):
    payload = _clean({"items": items, "routes": routes or {}})
    try:
        # gzip: home.pl obcina php://input przy 16 KB
        return api_call("upload", key, payload=payload, method="POST",
                        gz=True)
    except urllib.error.HTTPError as e:
        print("radar: upload HTTP %s: %s"
              % (e.code, e.read()[:300]), file=sys.stderr)
        try:
            (ROOT / "data" / "cache" / "radar_payload_fail.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=1),
                encoding="utf-8")
            print("radar: payload zapisany w data/cache/"
                  "radar_payload_fail.json", file=sys.stderr)
        except Exception:
            pass
        raise


# ---------- główna pętla ----------

def collect(cfg, serper_key):
    items = []
    for q in cfg.get("queries") or []:
        if not serper_key:
            break
        items += search_serper(q.get("q") or "", q.get("tbs"), serper_key)
        time.sleep(0.3)
    token = None
    cid, sec = env_get("REDDIT_CLIENT_ID"), env_get("REDDIT_SECRET")
    if cid and sec and (cfg.get("reddit") or []):
        try:
            token = reddit_token(cid, sec)
        except Exception as e:
            print("reddit oauth błąd: %s" % e, file=sys.stderr)
    elif cfg.get("reddit") and not serper_key:
        print("reddit: brak REDDIT_CLIENT_ID/SECRET i SERPER_API_KEY"
              " — pomijam", file=sys.stderr)
    for r in cfg.get("reddit") or []:
        items += search_reddit(r.get("sub") or "", r.get("q") or "",
                               token=token)
        time.sleep(0.5)
    return items


def run(dry=False, only_if_requested=False):
    env = load_env(ENV_PATH)
    key = env_get("TL_INGEST_KEY")
    serper_key = env_get("SERPER_API_KEY")
    or_key = env_get("OPENROUTER_API_KEY")

    if only_if_requested:
        if not key or not scan_requested(key):
            print("radar: brak żądania — pomijam")
            return 0
        print("radar: żądanie z panelu — skanuję")

    cfg = load_queries(key) if key else \
        json.loads(DEFAULT_QUERIES.read_text(encoding="utf-8"))

    found = collect(cfg, serper_key)
    print("radar: %d wyników z wyszukiwarek" % len(found))

    conn = db()
    known = seen_urls(conn)
    fresh, batch_cks = [], set()
    for i in found:
        if i["url"] in known or ck(i) in known or ck(i) in batch_cks:
            continue
        batch_cks.add(ck(i))
        fresh.append(i)
    print("radar: %d nowych URL-i" % len(fresh))

    routes = collect_routes()
    routes_text = coverage_text(routes)
    print("radar: pokrycie — %d tras (%d portów)"
          % (sum(len(v) for v in routes.values()), len(routes)))

    scored = 0
    new_items = []
    for it in fresh[:MAX_GEMINI_PER_SCAN]:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO seen(url, source, first_seen, scored)"
            " VALUES(?,?,?,1)", (it["url"], it["source"], now))
        conn.execute(
            "INSERT OR IGNORE INTO seen(url, source, first_seen, scored)"
            " VALUES(?,?,?,1)", (ck(it), it["source"], now))
        if skip_post(it):
            continue        # odsprzedaż/promo — bez scoringu
        j = score_item(it, or_key, routes_text) if or_key else None
        scored += 1
        if j and j.get("is_relevant") and \
                (j.get("relevance_score") or 0) >= 6 and \
                not skip_post(it):
            it["score"] = j.get("relevance_score")
            it["variants"] = [
                {"style": str(v.get("style") or "wariant")[:30],
                 "text": re.sub(r"(?<!//)\bpolataj\.se",
                                "https://polataj.se",
                                str(v.get("text") or ""))[:600]}
                for v in (j.get("variants") or [])[:3]
                if v.get("text")]
            it["found_at"] = datetime.now(timezone.utc).isoformat()
            new_items.append(it)
        time.sleep(0.4)
    # reszta nowych URL-i też idzie do bazy seen (bez oceny —
    # nie chcemy ich re-skanować ani palić na nie Gemini)
    for it in fresh[MAX_GEMINI_PER_SCAN:]:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO seen(url, source, first_seen, scored)"
            " VALUES(?,?,?,0)", (it["url"], it["source"], now))
        conn.execute(
            "INSERT OR IGNORE INTO seen(url, source, first_seen, scored)"
            " VALUES(?,?,?,0)", (ck(it), it["source"], now))
    conn.commit()

    # scal z istniejącymi items (fetch aktualnych z panelu)
    existing = []
    if key:
        try:
            ex = api_call("items_raw", key)
            existing = ex.get("items") or []
        except Exception:
            existing = []
    cutoff = (datetime.now(timezone.utc).timestamp()
              - MAX_ITEM_AGE_DAYS * 86400)
    new_urls = {n["url"] for n in new_items}
    new_cks = {ck(n) for n in new_items}
    keep = []
    for i in existing:
        if i.get("url") in new_urls or ck(i) in new_cks:
            continue
        if skip_post(i) or (i.get("score") or 0) < 6:
            continue            # stare odsprzedaże/promo/słabe — precz
        try:
            ts = datetime.fromisoformat(
                i.get("found_at") or "").timestamp()
        except ValueError:
            ts = 0
        if ts and ts < cutoff:
            continue            # starsze niż 14 dni — odpadają
        if ck(i) in {ck(k) for k in keep}:
            continue            # duplikat treści w istniejących
        keep.append(i)
    items = new_items + keep
    items.sort(key=lambda x: (-(x.get("score") or 0),
                              x.get("found_at") or ""))
    items = items[:60]

    print("radar: %d ocenionych, %d relevantnych, %d łącznie w panelu"
          % (scored, len(new_items), len(items)))

    if dry:
        for i in items[:10]:
            print("---", i["source"], i.get("score"), i["url"])
            print("   ", i["title"][:80])
            print("   ", (i.get("reply") or "")[:120])
        return 0
    if key:
        r = upload(items, key, routes)
        print("radar: upload → %s" % r)
    else:
        print("radar: brak TL_INGEST_KEY — pomijam upload",
              file=sys.stderr)
    conn.close()
    return 0


def main():
    dry = "--dry-run" in sys.argv
    flag = "--if-requested" in sys.argv
    return run(dry=dry, only_if_requested=flag)


if __name__ == "__main__":
    sys.exit(main())
