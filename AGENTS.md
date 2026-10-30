# polataj.se — notatki projektowe

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
- **Pipeline:** VPS home.pl `entropia-vps` (31.70.120.242, Berlin),
  systemd timer `tl-search.timer` co 6 h → `/home/tl/run_search.sh`
  wykonuje `search.py <port>` + `ingest.py <port>` dla wszystkich portów,
  a na końcu commituje `docs/` + `data/history.jsonl` i pushuje
  (deploy key `tl-worker-entropia-vps`). Logi: `journalctl -u tl-search`.
  GitHub Actions `search.yml` ma wyłączony schedule — fallback ręczny.
  FTP tylko przy wdrożeniu strony/API, nie przy aktualizacji ofert.
- **Geolokalizacja:** `docs/index.html` pyta get.geojs.io (timeout 2,5 s),
  podświetla najbliższy port i kieruje odliczanie do najbliższego
  AKTYWNEGO lotniska (mapowanie ACTIVE w skrypcie). Sugestia, nie redirect.
  Event GA4: `geo_suggest`.
- **Nowy port:** dodaj wpis w `config.json → ports` (`airports`,
  `avi_origin`), katalog `docs/<port>/index.html` (kopia apki — teksty,
  canonical/og, `HOME_GEO`), przebieg `search.py <port>` +
  `ingest.py <port>` w `search.yml`, aktywuj port na mapie Leaflet
  (`docs/index.html`: wpis w `APS` → flaga `1`, `URLS`, `ACTIVE_IATA`,
  `ACTIVE`) + mapowanie `port` w `<head>` + link w `#fallback`.

## Szablon apki (od 2026-10)

- Źródło: `templates/app.html` (placeholdery `{{PORT}}`, `{{CITY}}`,
  `{{CITY_GEN}}`, `{{AIRPORTS_DESC}}`, `{{GEO_LAT}}`, `{{GEO_LON}}`,
  `{{EXAMPLE_ROUTE}}`), dane per port w `config.json → ports`.
- `python3 tools/build_pages.py` renderuje 6× `docs/<port>/index.html`.
  **Nie edytować `docs/z*/index.html` ręcznie** — zmiany robić w szablonie,
  przebudować, `deploy_site.py`, commit (pliki wynikowe są w repo).

## pSEO — statyczne strony tras (od 2026-10)

- `tools/build_seo_routes.py` (zero zależności) → `docs/loty/<miasto>-<miasto>/`
  per para (port, dest), lotniska portu scalone pod slugiem miasta.
  Szablon `templates/route.html` (placeholdery `{{TITLE}}`, `{{DESCRIPTION}}`,
  `{{CANONICAL}}`, `{{ROBOTS}}`, `{{JSONLD}}`, `{{BODY}}`).
- Dane: `deals.json`+`far.json` wszystkich portów (tylko RT), min. 30 dni
  z `data/history.jsonl`, dystans z `dest_geo`, miesiące/dni tygodnia
  z `date_out`/`weekday_out`. Trasy <3 deale i <2 próbki historii →
  `noindex,follow`.
- Generuje też `docs/loty/index.html`, `docs/sitemap.xml`, `docs/robots.txt`.
- Linkowanie statyczne: mapa (`details.mesh`) → sześć stron portów →
  pełna siatka tras (`{{ROUTE_LINKS}}` w `templates/app.html`). Katalog
  `/loty/` linkuje także do portów. `build_seo_routes.py` przebudowuje
  strony portów przez `build_pages.main(routes)`, więc siatki odświeżają
  się razem z trasami. Test osiągalności: parsować HTML bez wykonywania JS
  i sprawdzić, że każda aktywna trasa ma link ze swojej strony portu.
- Odpalany na VPS z `run_search.sh` po ingestach (co 6 h, przed commitem);
  deploy idzie `tl-deploy.timer`. Logo: `docs/assets/logo.jpg` (+`-96`),
  użyte w nagłówku pSEO i `og.png` (`make_og.py`).

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
- OW trafia do pełnego snapshotu w bazie, ale NIE do tabeli historii
  `offers` ani do alertów mailowych.
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
  Alias `alerty@polataj.se → kontakt@` założony (odpowiedzi na alerty nie
  odbijają). Opcjonalnie: `rua=mailto:kontakt@polataj.se` w DMARC.
- Tabele: `subscribers` (z `reminded_at`), `alerts_sent` (db.php automigracja
  + schema.sql).
- `maintenance.php` (POST, X-Ingest-Key; wołany z `ingest.py` po każdym
  porcie, idempotentny): JEDNO przypomnienie o potwierdzeniu 24–72 h po
  zapisie (`reminded_at`), usuwanie niepotwierdzonych po 14 dniach.
- Zweryfikowane na żywo 2026-10-19: mail z home.pl dochodzi, potwierdzenie
  działa (1 subskrybent potwierdzony).
- Podgląd bazy: panel home.pl → Bazy danych → phpPgAdmin (`subscribers`,
  `alerts_sent`) lub
  `curl -H "X-Ingest-Key: $TL_INGEST_KEY" https://makosa.org/tanie_loty/api/subscribers.php`.
  Usunięcie wpisu: to samo z `-X DELETE "...subscribers.php?email=adres"`.

## Telegram

- `telegram_alerts.py` (Python 3, stdlib) → bot `@polatajsebot`, kanał
  `@polataj_se`. Konfiguracja prywatna `telegram/.env` (ignorowana przez Git):
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`, `TELEGRAM_ENABLED`.
  `TELEGRAM_BOT_USERNAME` w pliku jest tylko informacyjne.
- `--check` sprawdza bota/kanał/uprawnienia bez publikacji; bez argumentów
  jest dry-run. `--auto` publikuje tylko gdy `TELEGRAM_ENABLED=1`;
  `--send` jawnie publikuje niezależnie od przełącznika. Domyślnie wyłączone.
- Filtr: RT, `record_low=true`, cena >0 i ≤200 zł, wylot po dzisiejszym dniu,
  snapshot ≤8 h. Maks. 3 próby na cały zestaw snapshotów sześciu portów dla
  kanału; prywatnie osobny limit 3 na odbiorcę łącznie z jego wybranych miast.
- Prywatne subskrypcje: `telegram_bot.py`, usługa VPS `tl-telegram.service`
  (źródło `tools/tl-telegram.service`), long polling bez webhooka. `/start`
  pokazuje przyciski miast; Warszawa to wspólny wybór WAW/WMI/RDO.
  Można zaznaczyć kilka miast; są to robocze `draft_ports`. Dopiero przycisk
  „Zapisz i łap okazje” przenosi je do potwierdzonych `ports` i włącza alerty.
  Po zapisie pozytywny ekran potwierdzenia, „Zmień moje miasta” i „Ustawienia”.
  Pauza/wznowienie tylko w ustawieniach, bez przycisku wypisania z menu.
  `/lotniska`, `/pauza` (alias `/stop`), `/wznow`. Tylko prywatne rozmowy.
  Dawna komenda `/wypisz` działa dla zgodności, ale nie jest promowana w UI.
  Wyjście z publicznego kanału nie zatrzymuje prywatnych alertów bota.
- Preferencje, kursor aktualizacji i kolejka odpowiedzi: prywatny plik
  `data/cache/telegram_subscribers.sqlite` (0600, WAL). Bez nazw/username'ów;
  tylko ID rozmowy i preferencje. Callbacki idempotentne po update_id,
  odpowiedzi ponawiane z outboxu bez ponownego przełączania wyboru.
  Po restarcie zachowane subskrypcje, szkic wyboru i kursor. Migracja dodaje
  `draft_ports` bez zmiany potwierdzonych miast ani pauzy. `/wypisz` usuwa subskrypcję;
  historia deduplikacji wysyłek pozostaje w oddzielnym `telegram.sqlite`.
- `telegram_alerts.py --auto` po kanale wysyła osobno prywatne alerty.
  Ponownie sprawdza aktualny zapis przed każdą wysyłką; nie wysyła starej
  kolejki z odznaczonych miast. Pauza nie cofa już rozpoczętego uploadu.
  `TELEGRAM_ENABLED=0` zatrzymuje publikację, ale menu bota nadal działa.
- Obsługa: `sudo systemctl restart tl-telegram.service` po zmianach kodu
  workera/configu; logi `journalctl -u tl-telegram.service`. Deploy timer nie
  restartuje tej usługi automatycznie. Po zmianach pliku unit: instalacja
  do `/etc/systemd/system/`, `sudo systemctl daemon-reload`, restart.
  Nie uruchamiać równolegle drugiego pollera ani `getUpdates` w diagnostyce.
  Nie usuwać cudzego webhooka; worker odmawia startu, jeśli webhook istnieje.
- SQLite `data/cache/telegram.sqlite` + flock chronią przed równoległą wysyłką.
  Potwierdzone wysyłki deduplikowane po kanale, lotniskach i datach; błędy
  można ponowić w kolejnych przebiegach przez 24 h. Timeout po przyjęciu posta
  przez Telegram może skutkować duplikatem (API nie ma klucza idempotencji).
- Wiadomości HTML prowadzą na stronę portu polataj.se (nie udają linku
  do serwisu, jeśli prowadzą do przewoźnika). Podgląd linku wyłączony przez
  `link_preview_options.is_disabled=true`, więc alerty nie powtarzają grafiki OG.
  Timeout API 15 s, bez logowania tokenu.
- `tools/run_search.sh` jest wersjonowaną kopią `/home/tl/run_search.sh`;
  wywołuje Telegram raz po całej pętli search/ingest, przed generowaniem pSEO.
  Zmiany skryptu należy przenieść na VPS do `/home/tl/run_search.sh`.
- Mapki tras: `route_map.py` + Pillow (na VPS pakiet Ubuntu `python3-pil`).
  Jasne kafelki Esri World Topo, współrzędne lotnisk z istniejącego
  `data/cache/airports.json` (fallback wylotu: geo portu), kierunek z `dest_geo`.
  PNG 1000×640 wysyłany przez `sendPhoto` z opisem w podpisie, bez osobnego
  podglądu linku. Atrybucja na grafice; linia to schemat połączenia, nie przebieg lotu.
  Kafelki cache'owane 7 dni w `data/cache/telegram_tiles`; pobranie 8 s/kafelek,
  budżet generowania 30 s (ostatnie żądanie może go przekroczyć o timeout).
  Przy braku mapy/Pillow/kafelków wysyłany sam tekst. Po niepotwierdzonym
  uploadzie nie wysyłać dodatkowo tekstu (ryzyko duplikatu); retry z kolejki.
  Upload zdjęcia: timeout 30 s. Do bliźniaczego serwisu przenieść także renderer
  i zainstalować Pillow; żaden dodatkowy token mapy nie jest wymagany.
- Testy: `python3 -m unittest discover -s tests -v`.
  `python3 tools/test_telegram.py` sprawdza prawdziwe API bez publikacji;
  dopiero `--send-test` publikuje oznaczony post testowy (wymaga zgody).
- Przenoszenie do bliźniaczego serwisu: osobny bot/kanał/token, własny stan
  SQLite; podmienić domenę, walutę, porty i progi w module. Szczegółowe
  polecenia i zasady są również w komentarzach prywatnego `telegram/.env`.

## Facebook i wspólna publikacja (od 2026-10)

- `social_publisher.py --auto` zastępuje pojedyncze wywołanie Telegrama w
  `tools/run_search.sh` (kopię trzeba też zainstalować jako `/home/tl/run_search.sh`).
  Wspólne świeże rekordy RT do 200 zł, maks. 3 na platformę/przebieg.
  Publiczny Telegram, prywatne alerty i Facebook to niezależne zadania
  `ThreadPoolExecutor`; wyjątek jednego nie blokuje pozostałych.
- Facebook: `facebook_publisher.py`, natywne urllib, Graph API `v24.0`.
  Własna mapka trasy z tego samego renderera co Telegram: multipart
  `POST /{page-id}/photos` (`source`, `message`, `published=true`), URL portu
  w opisie, bez osobnego parametru `link` i bez powtarzanego podglądu OG.
  Jeśli renderer nie wygeneruje mapy: `/feed` tylko z `message` i URL-em
  w tekście, bez `link` (nie zamawia załącznika linkowego). Błąd wysyłki
  zdjęcia nie uruchamia natychmiastowej drugiej publikacji tekstu, aby nie
  duplikować posta przy niepewnym wyniku połączenia. Stan aktualizowany
  po potwierdzeniu API; odpowiedź zdjęciowa normalizowana do `post_id`.
  Strona: `1393638090497267`, `https://www.facebook.com/1393638090497267`.
  Przed wysyłką `/me` musi identyfikować tę stronę. Token w Authorization,
  nigdy w URL/logu; błędy logują tylko HTTP/Graph code/subcode.
- Prywatny `facebook/.env`, tryb 600, poza Gitem: `FB_PAGE_ID`,
  `FB_PAGE_ACCESS_TOKEN` (alias dawnego `FACEBOOK_ACCESS_TOKEN`),
  `FB_GRAPH_VERSION=v24.0`, `FACEBOOK_ENABLED=1` (0 = wyłączone).
  Wymagany Page Access Token, nie token użytkownika, oraz uprawnienia
  `pages_manage_posts` i `pages_read_engagement`. Błąd 190: odświeżyć token.
  Bez pliku domyślnie wyłączone. Nie kopiować sekretów do dokumentacji/repo.
- Facebook ma osobny stan `data/cache/facebook.sqlite` (600) i lock;
  Telegram nadal używa dotychczasowego stanu, bez ponownej publikacji
  wysłanych ofert. Ponowienia i ważność 24 h jak w module Telegrama.
- Sprawdzenie bez publikacji: `python3 facebook_publisher.py`.
  `python3 social_publisher.py` = dry-run. Test publiczny (wyłącznie za zgodą):
  `python3 social_publisher.py --send-test`, opcjonalnie `--platform facebook`
  lub `--platform telegram`, aby nie powtarzać testu drugiej platformy.
  Test nie trafia do prywatnych subskrybentów ani do deduplikacji prawdziwych ofert.
- Hit Detector (`hit_detector.py`): progi `price<=60 zł` LUB `price<=typical_price*0.3`,
  skanuje WSZYSTKIE oferty z `deals.json`, `far.json` i `oneway.json` (RT i OW,
  bez limitu 200 zł); tytuł pokazuje „w dwie strony”/„w jedną stronę”,
  LINK = link zakupu oferty, fallback na stronę portu.
  Zgrupowane po trasie, najtańsza oferta + do 3 przykładowych dat; szablon bloków
  „TYTUŁ/CENA/LINK/OPIS” pod Pepper.pl wysyłany tylko na `TELEGRAM_ADMIN_CHAT_ID`
  (prywatny czat admina w `telegram/.env`). Osobny stan `data/cache/hits_admin.sqlite`,
  osobny lock, limit 3/przebieg jak kanał; niezależne zadanie w `social_publisher`
  — błąd nie blokuje kanału, FB ani prywatnych alertów.
- Wspólne ikony/linki: `tools/social_links.py`, wspólny CSS
  `docs/assets/social.css` (adres `?v=<hash pliku>`). Ikony kanału Telegram
  i Facebooka, rozdzielone od rozwijanej sekcji „Alerty z moich miast”
  (z ikoną Telegrama), która prowadzi do `https://t.me/polatajsebot` i tłumaczy
  Start → wybór miast → „Zapisz i łap okazje”. Bez zewnętrznych widgetów, SDK
  ani pikseli śledzących.
- Szablon portu ma `{{SOCIAL_LINKS}}` w `.alerts`, bezpośrednio pod formularzem
  mailowym — tam również nie dublować linków. `build_pages.refresh_social_links()`
  odświeża stare HTML-e bez duplikatów; główna używa wariantu
  `data-home="true"` z lekkim, klikalnym overlayem nad mapą (`pointer-events:auto`
  tylko na panelu). W bardzo niskim widoku kompresuje się do ikon/„Bot”, a rozwinięcie
  rozszerza panel. Podstrony pSEO/stopki mają zwykły blok `data-home="false"`.
  `deploy_site.py` musi wgrywać `.css` zawsze, bo podmiana stylu może mieć
  ten sam rozmiar pliku.

## Wspólne opisy publikacji

- Opisy AI dla Telegrama (publicznego, prywatnego i admina), Facebooka oraz
  każdej oferty digestu/hitu Wykopa pochodzą z `hit_detector.description()`.
  Bez powitań (zwłaszcza „Siemka!”), bez linków w opisie, z nawiązaniem do
  miasta docelowego. Cena, daty i link pozostają w szablonach kanałów.
- Wykop pomija pusty zestaw ofert bez publikacji i zmiany limitów. Digest
  wybiera różne trasy ze wszystkich świeżych ofert, nie tylko rekordów RT ≤200 zł.

## Social / branding

- `docs/og.png` (1200×630) to aktualna grafika dostarczona ręcznie:
  jasna mapa i kolorowe pinezki. Nie regenerować jej przez `tools/make_og.py`
  bez uzgodnienia — ten archiwalny generator nadpisuje ją starszym projektem.
- `build_pages.og_image_url()` dodaje do adresu OG `?v=<hash zawartości>`.
  `build_pages.refresh_og_metadata()` odświeża wszystkie istniejące HTML-e,
  również starsze strony tras; jest uruchamiane przez `build_pages.py`.
  Generator pSEO używa tego samego adresu. Po podmianie obrazka można wykonać
  samo odświeżenie: `python3 -c "from tools.build_pages import refresh_og_metadata; refresh_og_metadata()"`.
  Cache już opublikowanych podglądów komunikatorów może wymagać osobnego odświeżenia.
- `deploy_site.py` wgrywa `og.png` zawsze, przed HTML-ami, również przy tej
  samej wielkości pliku; zapobiega pomijaniu zmienionej grafiki i publikacji
  nowych metadanych przed obrazem. Pozostałe zasady transferu bez zmian.
- Kolory punktów głównej mapy: `docs/index.html → AP_COLORS` (dopisać przy
  aktywacji nowego miasta). Nieaktywne punkty szare; geosugestia powiększa
  punkt i obwódkę, ale zachowuje kolor miasta. Etykiety ciemne, bez cienia.
  Test: `node tests/test_homepage_map.js`. Pozostałe strony zachowują ciemny styl.

## Deploy

- **Deploy działa z VPS** (`entropia-vps`): timer `tl-deploy.timer` co 5 min
  odpala `/home/tl/deploy.sh` — `git pull`, `deploy.py` gdy zmieniło się
  `server/` lub `deploy.py`, `deploy_site.py` zawsze przy nowym HEAD.
  Marker ostatniego deploya: `/home/tl/.tl_deployed`. Logi:
  `journalctl -u tl-deploy`. Push na `main` → na serwerze w ≤5 min.
  Cały deploy (API + strona) trwa ~1–2 min z VPS vs ~25 min z GH Actions.
- Frontend: `python3 deploy_site.py` (wymaga TL_FTP_*, TL_WEB_DIR=/makosa.org).
  `.html`/`.json`/`.htaccess` wgrywane zawsze; reszta po rozmiarze.
  `docs/CNAME` nie jest wgrywany na home.pl.
- API: `python3 deploy.py` (ręcznie na VPS lub lokalnie z `.env`).
- **GitHub = tylko repo.** Workflowy usunięte (2026-10-26) — deploy i
  wyszukiwanie działają wyłącznie na VPS.
- Pełne oferty (`deals`, `far`, `oneway`) są zapisywane atomowo dla portu
  w `deal_snapshots` przez POST `snapshot.php` (X-Ingest-Key).
  `ingest.py` przesyła gzip podzielony na porcje ≤6 KB, bo home.pl ucina
  większe body; `snapshot_parts` zbiera porcje i dopiero cały komplet
  zastępuje snapshot. Niedokończony transfer nie zmienia widoku strony.
  GET `snapshot.php?port=<slug>` zwraca trzy zakładki; frontend pobiera
  je z API, a przy błędzie używa statycznych JSON-ów z ostatniego deployu.
  Starszy przebieg nie nadpisuje nowszego. Relacyjne `offers` i
  `route_daily` nadal przechowują historię RT i służą wykresom/typowym cenom.
  Testy: `python3 -m unittest discover -s tests -v` oraz
  `node tests/test_frontend_snapshot.js`.
- Wdrożenie zmiany źródła danych: najpierw API (`deploy-api.yml`), potem
  zasilić sześć portów aktualnymi snapshotami, zweryfikować GET dla każdego
  i dopiero włączyć frontend czytający API. Przebieg `search.yml` musi
  pomyślnie zapisać snapshoty; błąd ingestu zatrzymuje przebieg.
- **Preferowany deploy strony: `gh workflow run deploy-api.yml`** (robi
  API + stronę z aktualnego `main`). Lokalny FTP-TLS bywa blokowany przez
  firewall sieci (kanał danych PASV w TLS → timeout) — wtedy tylko Actions.
  Uwaga: przebieg `search.yml` też wgrywa stronę na końcu, ze swojego
  checkoutu — commit po jego starcie może zostać nadpisany; wtedy
  odpalić `deploy-api.yml` po jego zakończeniu.

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
5. ~~**Niezależność od GitHub Actions**~~ — zrobione 2026-10-25: wyszukiwanie
   działa na VPS home.pl (`tl-search.timer`). GitHub zostaje tylko jako repo
   + awaryjny `workflow_dispatch`.
6. **loty.makosa.org:** gdy Google przeczyta canonical — wyłączyć GitHub
   Pages / CNAME.
7. **Kolejne porty** wg `geo_suggest`: Rzeszów (baza Ryanaira) najsensowniejszy;
   Szczecin/Łódź/Bydgoszcz/Lublin mają po kilka tras. Radom (RDO): żadne
   źródło nie zwraca dziś cen — sprawdzać okresowo.
8. **Search Console:** usługa Domain dla polataj.se, w starej „Change of Address".
9. Drobne: odświeżyć cache podglądu FB/LinkedIn dla og.png.
