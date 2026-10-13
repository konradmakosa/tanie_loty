# Tanie loty z Warszawy

Prosty łowca okazji: skrypt pobiera najtańsze loty w obie strony z warszawskich
lotnisk (Modlin WMI + Okęcie WAW) z publicznego API Ryanaira i zapisuje je do
`docs/deals.json`. Plik `docs/index.html` wyświetla je jako listę kart —
można go hostować za darmo na GitHub Pages.

Źródłem danych jest tylko Ryanair — API Kiwi Tequila jest zamknięte dla nowych
partnerów, dlatego stary `kiwi.py` nie działa (zostaje w repo jako archiwum).

## Uruchomienie lokalne

Wymaga tylko Pythona 3.9+ (zero zewnętrznych bibliotek):

```bash
python3 search.py
python3 -m http.server -d docs 8000
```

Potem otwórz http://localhost:8000 w przeglądarce.

## Uruchomienie na GitHubu

1. Utwórz prywatne lub publiczne repo i wypchnij kod (`git push`).
2. **Settings → Pages → Source: Deploy from a branch → main / `/docs`**.
3. **Settings → Actions → General → Workflow permissions: Read and write**
   (żeby workflow mógł commitować wyniki).
4. Workflow `Szukaj tanich lotów` uruchamia się co 6 h (oraz ręcznie przez
   „Run workflow") i commituje `docs/deals.json` + historię cen.

Strona będzie pod `https://<użytkownik>.github.io/<repo>/` (tu: własna domena `loty.makosa.org` przez plik `docs/CNAME`).

## Drugie źródło: Aviasales (Travelpayouts)

Oprócz Ryanaira skrypt potrafi pobierać ceny wszystkich linii (Wizz Air,
LOT, easyJet itd.) z darmowego API Travelpayouts/Aviasales.

1. Załóż darmowe konto na [travelpayouts.com](https://www.travelpayouts.com).
2. Token znajdziesz w **Narzędzia → API**
   (`travelpayouts.com/programs/100/tools/api`); marker (ID partnera) — w panelu.
3. **Lokalnie:** skopiuj `.env.example` do `.env` i wklej token
   (`.env` jest ignorowane przez git).
4. **Na GitHubu:** Settings → Secrets and variables → Actions →
   New repository secret `TRAVELPAYOUTS_TOKEN`
   (opcjonalnie też `TRAVELPAYOUTS_MARKER`).

Bez tokena źródło jest po prostu pomijane (działa sam Ryanair).
Uwaga: ceny Aviasales pochodzą z cache z ostatnich 48 h — warto je
sprawdzić ponownie przy zakupie.

## Ustawienia w przeglądarce

Strona ma zakładkę **Ustawienia** (cena, liczba nocy, dni wylotu/powrotu,
horyzont, lotniska, kraje, tylko bezpośrednie). Filtry zapisują się
w `localStorage` — czyli per urządzenie i przeglądarka, bez serwera.
`config.json` pełni rolę „koperty" wyszukiwania: skrypt zbiera szerszy
zestaw ofert, a strona zawęża go do preferencji użytkownika.

Zakładka **Daleko** pokazuje okazje poza Europą (max 1 przesiadka
w każdą stronę, dane z Aviasales) — osobne filtry w Ustawieniach.
Jej „koperta" to sekcja `far` w `config.json`
(`max_price_pln`, `min_nights`/`max_nights`, `days_ahead`,
`max_transfers_each_way`).

## Historia cen

Skrypt zapisuje najniższą cenę każdej trasy z każdego uruchomienia —
w `data/history.jsonl` (surowe, do mediany/rekordów) oraz jako wykresowe
`docs/history/{ORIGIN}-{DEST}.json` (punkt `[czas, cena, miesiąc wylotu]`,
przycinane do 400 dni). Na karcie widać „typową cenę" — medianę
z ostatnich 90 dni — i rozwijany mini-wykres historii trasy.

### Baza PostgreSQL / MySQL (opcjonalna)

Katalog `server/` to API PHP (PDO — PostgreSQL lub MySQL w produkcji,
wybór `TL_DB_TYPE` w `.env`; SQLite lokalnie)
wgrywane na hosting przez `deploy.py` (FTP/FTP_TLS, flaga `--dry-run`
dla podglądu). Endpointy: `ingest.php` (POST + `X-Ingest-Key`, gzip),
`history.php?route=XXX-YYY`, `typical.php?tab=`. GitHub Actions
po każdym wyszukiwaniu uruchamia `ingest.py` — bez sekretów
`TL_API_BASE`/`TL_INGEST_KEY` krok wypisuje „pomijam" i nic nie blokuje.
Dostępy (baza `TL_DB_*`, FTP `TL_FTP_*`, `TL_WEB_DIR`) trzymane są
w `.env` — nie wchodzą do repozytorium. Strona używa API, gdy
odpowiada; bez niego działa na statycznych plikach.

Strona ma wpięte Google Analytics 4 (ID w `docs/index.html`, zdarzenia:
kliknięcie oferty, zapis ustawień, zmiana zakładki) — by je usunąć lub
zmienić, wystarczy skasować/podmienić blok `gtag` w `<head>`.

## Konfiguracja — `config.json`

| Klucz | Znaczenie |
|---|---|
| `airports` | kody IATA lotnisk wylotu |
| `max_price_pln` | maks. cena biletu w obie strony |
| `min_nights` / `max_nights` | długość pobytu |
| `days_ahead` | jak daleko do przodu szukać wylotów |
| `record_low_ratio` | cena ≤ `ratio` × mediana = „rekordowo tanio" |
| `record_low_min_samples` | min. liczba obserwacji w historii, by liczyć rekord |

Historia cen zapisywana jest w `data/history.jsonl` (przycinana do 180 dni),
więc badge „REKORDOWO TANIO" zacznie działać dopiero po kilku uruchomieniach.
