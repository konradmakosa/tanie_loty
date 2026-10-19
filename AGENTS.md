# Polataj.se — notatki projektowe

## Stan (po migracji na home.pl + polataj.se)

- **Domena główna:** `https://polataj.se/` (mapa lotnisk) → `/zwarszawy/` (apka).
- **Hosting:** home.pl, serwer `entropia`, FTP root `/makosa.org`, strona w `/makosa.org/polataj`.
- **DNS:** `polataj.se` wydelegowana na dns.home.pl/dns2/dns3 (rejestracja w OVH, bez poczty).
- **SSL:** homeSSL Start dla polataj.se + www (do 2027-10-18), auto-instalacja.
- **Przekierowania:** `.htaccess` w `docs/` wymusza HTTPS i `www → bez www`
  (tylko dla hostów polataj.se; `makosa.org/polataj` nietknięte).
  `loty.makosa.org` (GitHub Pages) przekierowuje skryptem w `<head>` —
  Pages nie robi 301 serwerowych.
- **GA4:** jeden tag `G-CTFYNF714B` dla wszystkich domen; rozróżnienie po
  wymiarze Hostname. Historia nienaruszona.
- **Pipeline:** GitHub Actions co 6 h: `search.py` → ingest do bazy (PHP API
  na `makosa.org/tanie_loty/api`) → `deploy_site.py` (FTP na home.pl) →
  commit danych do `docs/zwarszawy/`.

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
3. **Geolokalizacja** jako miękka sugestia lotniska (NIE twardy redirect —
   mobilne IP często pokazują Warszawę). Opcje: MaxMind GeoLite2 na home.pl
   lub Cloudflare przed stroną. Wybór użytkownika (localStorage) i tak
   najważniejszy.
4. **Drugie lotnisko** (np. Kraków): `search.py` parametryzować po porcie,
   ścieżki `/zkrakowa/`, osobne `deals.json`; mapa: aktywować znacznik.
5. **Niezależność od GitHub Actions:** przepisać `search.py` na PHP
   i puścić z crona home.pl (panel: „Zadania cron"). GitHub zostaje tylko
   jako repo kodu.
6. Drobne: `favicon.ico` (404), ewentualnie `og.png` pod markę Polataj.se.
7. **Search Console:** jeśli używana — dodać usługę Domain dla polataj.se,
   w starej „Change of Address".
