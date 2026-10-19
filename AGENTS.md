# Polataj.se — notatki projektowe

## Stan (po migracji na home.pl + polataj.se)

- **Domena główna:** `https://polataj.se/` (mapa lotnisk) → `/zwarszawy/`
  + `/zkrakowa/` `/zgdanska/` `/zpoznania/` `/zwroclawia/` `/zkatowic/`
  (apki per port — aktywne: WAW/WMI, KRK, GDN, POZ, WRO, KTW).
- **Hosting:** home.pl, serwer `entropia`, FTP root `/makosa.org`, strona w `/makosa.org/polataj`.
- **DNS:** `polataj.se` wydelegowana na dns.home.pl/dns2/dns3 (rejestracja w OVH, bez poczty).
- **SSL:** homeSSL Start dla polataj.se + www (do 2027-10-18), auto-instalacja.
- **Przekierowania:** `.htaccess` w `docs/` wymusza HTTPS i `www → bez www`
  (tylko dla hostów polataj.se; `makosa.org/polataj` nietknięte).
  `loty.makosa.org` (GitHub Pages) przekierowuje skryptem w `<head>` —
  Pages nie robi 301 serwerowych.
- **GA4:** jeden tag `G-CTFYNF714B` dla wszystkich domen; rozróżnienie po
  wymiarze Hostname. Historia nienaruszona.
- **Pipeline:** GitHub Actions co 6 h: `search.py <port>` dla każdego portu
  z `config.json → ports` → `ingest.py <port>` do bazy (PHP API
  na `makosa.org/tanie_loty/api`) → `deploy_site.py` (FTP na home.pl) →
  commit danych do `docs/<port>/`.
- **Geolokalizacja:** `docs/index.html` pyta get.geojs.io (timeout 2,5 s),
  podświetla najbliższy port i kieruje odliczanie do najbliższego
  AKTYWNEGO lotniska (mapowanie ACTIVE w skrypcie). Sugestia, nie redirect.
  Event GA4: `geo_suggest`.
- **Nowy port:** dodaj wpis w `config.json → ports` (`airports`,
  `avi_origin`), katalog `docs/<port>/index.html` (kopia apki — teksty,
  canonical/og, `HOME_GEO`), przebieg `search.py <port>` +
  `ingest.py <port>` w `search.yml`, aktywuj `<a class="ap on" data-ap=…>`
  na mapie + dopisz do mapowań `port` (head) i `ACTIVE`.

## Linki zakupu (od 2025-10)

- Użytkownik NIE trafia do Aviasales. `search.py: buy_link()` → strona linii
  (Ryanair, Wizz, LOT, easyJet, LEGACY_LINKS), fallback **Skyscanner**
  (neutralny deep link, bez afiliacji). Loty z przesiadkami → zawsze Skyscanner.
- Travelpayouts zostaje tylko jako źródło cen w backendzie (`TRAVELPAYOUTS_TOKEN`);
  `TRAVELPAYOUTS_MARKER` nieużywany. Ryzyko: ich Data API jest formalnie dla
  partnerów afiliacyjnych — szukać zamiennika źródła cen Wizz/LOT/„Daleko".
- Monetyzacja: afiliacja Skyscanner (impact.com) wymaga >5k UU/mies.; API
  Skyscannera >100k — poza zasięgiem. Plan: hotele/auta pod okazją, alerty.

## Alerty e-mail (double opt-in)

- Formularz na każdej stronie portu → `server/subscribe.php` (form-urlencoded,
  honeypot `hp`, ponowny mail potwierdzający najwcześniej po 10 min) →
  `confirm.php?t=` → redirect `/<port>/?alert=ok`; `unsubscribe.php?t=`
  (GET/POST one-click) → `?alert=wypisano`.
- `ingest.py <port>` po ingescie POST-uje `record_low` do `notify.php`
  (X-Ingest-Key); nowe `deal_id` lądują w `alerts_sent` ZAWSZE (także bez
  subskrybentów), mail (max 12 najtańszych) do potwierdzonych z portu.
- Wysyłka: PHP `mail()` z home.pl, From `alerty@polataj.se` (SPF polataj.se
  `v=spf1 a mx ~all` obejmuje IP serwera). Brak DKIM. `MAIL_DEBUG_DIR`
  w config.php → .eml do plików (testy lokalne, sqlite).
- Tabele: `subscribers`, `alerts_sent` (db.php automigracja + schema.sql).

## Deploy

- Frontend: `python3 deploy_site.py` (wymaga TL_FTP_*, TL_WEB_DIR=/makosa.org).
  `.html`/`.json`/`.htaccess` wgrywane zawsze; reszta po rozmiarze.
  `docs/CNAME` nie jest wgrywany na home.pl.
- API: `python3 deploy.py` lub workflow `deploy-api.yml`.

## Do zrobienia

1. **GA4:** zmienić URL strumienia `loty.makosa.org` → `polataj.se`
   (Admin → Data streams → Stream URL). Historia zostaje.
2. **loty.makosa.org:** gdy redirect skryptowy się sprawdzi i Google
   przeczyta canonical — rozważyć wyłączenie GitHub Pages / CNAME.
3. ~~Geolokalizacja~~ — zrobione (geojs + miękka sugestia).
4. ~~Drugie lotnisko (Kraków)~~ — zrobione: `/zkrakowa/`, `search.py
   zkrakowa`, znacznik KRK aktywny na mapie. Kolejne wg danych
   `geo_suggest`. Apka per port to wciąż kopia pliku — przy 3. porcie
   warto zrobić wspólny szablon + config JS.
5. **Niezależność od GitHub Actions:** przepisać `search.py` na PHP
   i puścić z crona home.pl (panel: „Zadania cron"). GitHub zostaje tylko
   jako repo kodu.
6. Drobne: `favicon.ico` (404), ewentualnie `og.png` pod markę Polataj.se.
7. **Search Console:** jeśli używana — dodać usługę Domain dla polataj.se,
   w starej „Change of Address".

## Podgląd subskrybentów

- Panel home.pl → Bazy danych → phpPgAdmin → tabela `subscribers` / `alerts_sent`.
- Lub: `curl -H "X-Ingest-Key: $TL_INGEST_KEY" https://makosa.org/tanie_loty/api/subscribers.php`
  (liczniki + lista; klucz z `.env`).
