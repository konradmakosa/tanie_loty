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

## Szablon apki (od 2026-10)

- Źródło: `templates/app.html` (placeholdery `{{PORT}}`, `{{CITY}}`,
  `{{CITY_GEN}}`, `{{AIRPORTS_DESC}}`, `{{GEO_LAT}}`, `{{GEO_LON}}`,
  `{{EXAMPLE_ROUTE}}`), dane per port w `config.json → ports`.
- `python3 tools/build_pages.py` renderuje 6× `docs/<port>/index.html`.
  **Nie edytować `docs/z*/index.html` ręcznie** — zmiany robić w szablonie,
  przebudować, `deploy_site.py`, commit (pliki wynikowe są w repo).

## Loty w jedną stronę (eksperyment, od 2026-10)

- Zakładka „One way" (`#wjedna`) na każdej stronie portu; plik
  `docs/<port>/oneway.json`. Koperta: `config.json → oneway`
  (≤79 zł LCC / ≤249 zł full, bezpośrednie, 120 dni) + `oneway.far`
  (poza Europą: ≤1200 zł, ≤1 przesiadka, 270 dni) — w tej samej zakładce,
  select „Zasięg: wszystko/Europa/Daleko"; rekordy dalekie mają `far: true`
  (flaga nadawana po kraju kierunku po scaleniu).
- `search.py`: Ryanair `oneWayFares/…/cheapestPerDay` + Travelpayouts
  `one_way=true` (direct) + `one_way=true, direct=false` dla dalekich;
  rekordy mają `trip: "oneway"`, `date_in: null`. GA4 `select_deal.far`.
  Historia w `data/history.jsonl` z `"trip":"oneway"` — mediany RT i OW
  liczone osobno; OW bez plików `history/*.json` i bez typical_price.
- OW NIE idzie do ingest/bazy ani do alertów mailowych.
- GA4: `view_tab {tab: "wjedna"}`, `select_deal {trip: "oneway"|"return",
  tab}`. **Żeby widzieć w raportach: zarejestrować wymiary niestandardowe
  `tab` i `trip`** (Administracja → Definicje niestandardowe → wymiar
  zdarzenia). Decyzja po 2–3 tyg.: jeśli OW < ~10% `select_deal` — usunąć.

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
- Wysyłka: PHP `mail()` z home.pl, From `alerty@polataj.se`. Poczta domeny
  skonfigurowana 2026-10-22 (support home.pl): MX `entropia.home.pl`, SPF
  `ip4:79.96.54.14 a mx -all`, **DKIM** `dkim._domainkey` (serwer podpisuje
  mail() automatycznie), DMARC `p=quarantine`. Zweryfikowane w Gmailu:
  dkim/spf/dmarc = pass (Return-Path to `entropia@makosa.org`, DMARC
  przechodzi po DKIM — nie ruszać). `MAIL_DEBUG_DIR` w config.php → .eml
  do plików (testy lokalne, sqlite).
- Kontakt: skrzynka `kontakt@polataj.se` (50 MB, przekierowanie na
  konrad@makosa.org). Adres w HTML składany z JS ze stałej `CONTACT`
  (templates/app.html, docs/index.html, docs/prywatnosc/index.html).
  TODO po stronie panelu: alias `alerty@polataj.se → kontakt@`, ewentualnie
  `rua=mailto:kontakt@polataj.se` w DMARC.
- Tabele: `subscribers`, `alerts_sent` (db.php automigracja + schema.sql).
- Zweryfikowane na żywo 2026-10-19: mail z home.pl dochodzi, potwierdzenie
  działa (1 subskrybent potwierdzony).
- Podgląd bazy: panel home.pl → Bazy danych → phpPgAdmin (`subscribers`,
  `alerts_sent`) lub
  `curl -H "X-Ingest-Key: $TL_INGEST_KEY" https://makosa.org/tanie_loty/api/subscribers.php`.

## Social / branding

- `docs/og.png` (1200×630) generowany przez `tools/make_og.py` (Pillow,
  czcionki systemowe macOS; czyta granicę Polski z `docs/index.html`).
  Nowy port → dopisać do `PORTS`/`ROUTES` i odpalić ponownie.

## Deploy

- Frontend: `python3 deploy_site.py` (wymaga TL_FTP_*, TL_WEB_DIR=/makosa.org).
  `.html`/`.json`/`.htaccess` wgrywane zawsze; reszta po rozmiarze.
  `docs/CNAME` nie jest wgrywany na home.pl.
- API: `python3 deploy.py` lub workflow `deploy-api.yml`.

## Zrobione (2026-10)

- Migracja na home.pl + polataj.se, SSL, przekierowania, GA4 (URL strumienia
  → polataj.se), geolokalizacja (miękka), 6 portów + Radom w Warszawie,
  nowe `og.png`, linki zakupu bez Aviasales, alerty e-mail.

## Do zrobienia

1. **GA4:** zarejestrować wymiary `tab` i `trip`; po 2–3 tyg. ocenić
   zakładkę „W jedną stronę" (zostaje / do usunięcia).
2. **Zamiennik źródła cen** za Travelpayouts (Wizz/LOT/„Daleko") — dziś brak
   darmowej alternatywy; obserwować. Bez niego zostaje sam Ryanair.
3. **Monetyzacja** (kolejność): lista mailowa rośnie → przy >5k UU/mies.
   aplikować do afiliacji Skyscanner (impact.com; hotele/auta też tam) →
   ewentualnie płatne alerty własne (kierunek/kryteria).
4. **Alerty — rozwój:** własne kryteria (kraj, max cena), digest dzienny
   zamiast per przebieg (DKIM/SPF/DMARC już działają), Brevo/SMTP
   gdy dostarczalność zacznie szwankować. Monitorować `alerts_sent`.
5. **Niezależność od GitHub Actions:** przepisać `search.py` na PHP
   i puścić z crona home.pl (panel: „Zadania cron"). GitHub zostaje tylko
   jako repo kodu.
6. **loty.makosa.org:** gdy Google przeczyta canonical — wyłączyć GitHub
   Pages / CNAME.
7. **Kolejne porty** wg `geo_suggest`: Rzeszów (baza Ryanaira) najsensowniejszy;
   Szczecin/Łódź/Bydgoszcz/Lublin mają po kilka tras. Radom (RDO): żadne
   źródło nie zwraca dziś cen — sprawdzać okresowo.
8. **Search Console:** usługa Domain dla polataj.se, w starej „Change of Address".
9. Drobne: odświeżyć cache podglądu FB/LinkedIn dla og.png.
