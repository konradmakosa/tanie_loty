import requests
from datetime import datetime, timedelta

# Settings
API_KEY = "TWOJ_KLUCZ_TEQUILA_KIWI"  # Pobierzesz darmowo z partners.kiwi.com
ORIGIN = "WAW,WMI"                    # Warszawa Chopin + Modlin
MAX_PRICE_PLN = 250                   # Maksymalna cena w PLN za bilet w dwie strony
CURRENCY = "PLN"

# Zakres dat: od jutra przez najbliższe 60 dni
date_from = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
date_to = (datetime.now() + timedelta(days=60)).strftime("%d/%m/%Y")

endpoint = "https://tequila-api.kiwi.com/v2/search"

headers = {
    "apikey": API_KEY,
    "accept": "application/json"
}

params = {
    "fly_from": ORIGIN,
    "date_from": date_from,
    "date_to": date_to,
    "nights_in_dst_from": 2,          # Min. 2 noce na miejscu (np. weekend)
    "nights_in_dst_to": 5,            # Max. 5 nocy
    "flight_type": "round",           # Lot w dwie strony
    "curr": CURRENCY,
    "price_to": MAX_PRICE_PLN,
    "max_stopovers": 0,               # Tylko loty bezpośrednie
    "limit": 15,
    "sort": "price"
}

response = requests.get(endpoint, headers=headers, params=params)

if response.status_code == 200:
    flights = response.json().get("data", [])
    print(f"Znaleziono {len(flights)} tanich lotów z Warszawy do {MAX_PRICE_PLN} PLN:\n")
    
    for flight in flights:
        city_to = flight['cityTo']
        country_to = flight['countryTo']['name']
        price = flight['price']
        link = flight['deep_link']
        
        # Daty wylotu i powrotu
        route_out = flight['route'][0]
        departure_time = datetime.fromtimestamp(route_out['dTime']).strftime('%Y-%m-%d %H:%M')
        
        print(f"✈️  {city_to} ({country_to}) — {price} PLN")
        print(f"    Wylot: {departure_time}")
        print(f"    Link do rezerwacji: {link}")
        print("-" * 50)
else:
    print(f"Błąd API: {response.status_code}", response.text)