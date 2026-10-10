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

Strona będzie pod `https://<użytkownik>.github.io/<repo>/`.

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
