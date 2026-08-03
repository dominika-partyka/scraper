import argparse
import json
import re
import time
from datetime import datetime
import os

import gspread
import requests
from bs4 import BeautifulSoup
from oauth2client.service_account import ServiceAccountCredentials

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

DEFAULT_SHEET_NAME = "Scraper"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9",
}

def get_lidl_categories():
    """Pobiera i strukturyzuje kategorie z Lidl.pl."""
    url = "https://www.lidl.pl"
    categories = []
    
    # Gotowe, pewne główne kategorie sklepu internetowego Lidl z podziałem na działy
    default_categories = [
        {"name": "Warsztat i auto > Narzędzia", "url": "https://www.lidl.pl/c/narzedzia/c10006766"},
        {"name": "Warsztat i auto > Warsztat", "url": "https://www.lidl.pl/c/warsztat/c10006771"},
        {"name": "Warsztat i auto > Akcesoria samochodowe", "url": "https://www.lidl.pl/c/akcesoria-samochodowe/c10006756"},
        {"name": "Dom i ogród > Meble", "url": "https://www.lidl.pl/c/meble/c10006701"},
        {"name": "Dom i ogród > Oświetlenie", "url": "https://www.lidl.pl/c/oswietlenie/c10006716"},
        {"name": "Dom i ogród > Ogród", "url": "https://www.lidl.pl/c/ogrod/c10006711"},
        {"name": "Kuchnia > AGD do kuchni", "url": "https://www.lidl.pl/c/agd-do-kuchni/c10006651"},
        {"name": "Kuchnia > Przybory kuchenne", "url": "https://www.lidl.pl/c/przybory-kuchenne/c10006661"},
        {"name": "Moda > Odzież damska", "url": "https://www.lidl.pl/c/odziez-damska/c10006601"},
        {"name": "Moda > Odzież męska", "url": "https://www.lidl.pl/c/odziez-meska/c10006611"},
        {"name": "Moda > Obuwie", "url": "https://www.lidl.pl/c/obuwie/c10006591"},
        {"name": "Sport i czas wolny > Rowery i akcesoria", "url": "https://www.lidl.pl/c/rowery-i-akcesoria/c10006821"},
        {"name": "Sport i czas wolny > Fitness i siłownia", "url": "https://www.lidl.pl/c/fitness-i-silownia/c10006811"},
        {"name": "Dziecko i zabawki > Odzież dziecięca", "url": "https://www.lidl.pl/c/odziez-dziecieca/c10006551"},
        {"name": "Dziecko i zabawki > Zabawki", "url": "https://www.lidl.pl/c/zabawki/c10006571"}
    ]

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            links = soup.find_all("a", href=True)
            scraped = []
            
            for link in links:
                href = link["href"]
                text = link.get_text(strip=True)
                if "/c/" in href and text and len(text) > 2 and not text.isdigit():
                    full_url = href if href.startswith("http") else f"https://www.lidl.pl{href}"
                    if not any(c["url"] == full_url for c in scraped):
                        # Tworzymy ścieżkę z nazwą
                        scraped.append({
                            "id": full_url,
                            "name": f"Kategorie > {text}",
                            "url": full_url
                        })
            if scraped:
                return scraped
    except Exception as e:
        print(f"Błąd pobierania kategorii Lidla: {e}")

    # Jeśli strona blokuje scraper – zwracamy przygotowaną, poukładaną listę z działami!
    for cat in default_categories:
        categories.append({
            "id": cat["url"],
            "name": cat["name"],
            "url": cat["url"]
        })
        
    return categories

def extract_lidl_products(category_url, max_products=None, progress_callback=None):
    """Scrapuje produkty z podanej kategorii na Lidl.pl."""
    if not category_url.startswith("http"):
        category_url = f"https://www.lidl.pl{category_url}"

    wszystkie_produkty = []
    seen_urls = set()
    pominiete_duplikaty = 0

    page = 1
    total_estimated = 100

    while True:
        if max_products and len(wszystkie_produkty) >= max_products:
            break

        page_url = f"{category_url}?page={page}" if page > 1 else category_url
        print(f"Scrapuję podstronę Lidla: {page_url}")

        try:
            resp = requests.get(page_url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            product_cards = soup.select("article, .product-grid-box, div[data-product-id]")

            if not product_cards:
                break

            pobrane_na_stronie = 0
            for card in product_cards:
                if max_products and len(wszystkie_produkty) >= max_products:
                    break

                title_el = card.select_one(".product-grid-box__title, h2, .grid-box__title, a.title")
                nazwa = title_el.get_text(strip=True) if title_el else ""

                if not nazwa:
                    continue

                link_el = card.select_one("a[href]")
                href = link_el["href"] if link_el else ""
                pelny_url = href if href.startswith("http") else f"https://www.lidl.pl{href}"

                if pelny_url in seen_urls:
                    pominiete_duplikaty += 1
                    continue
                seen_urls.add(pelny_url)

                price_el = card.select_one(".price-m__price, .m-price__price, .grid-box__price")
                cena_text = price_el.get_text(strip=True) if price_el else "0"
                cena_clean = re.sub(r"[^\d,\.]", "", cena_text).replace(",", ".")
                try:
                    cena_pln = float(cena_clean)
                except ValueError:
                    cena_pln = 0.0

                img_el = card.select_one("img")
                photo_url = ""
                if img_el:
                    photo_url = img_el.get("src") or img_el.get("data-src") or ""
                
                image_formula = f'=IMAGE("{photo_url}")' if photo_url else ""

                wszystkie_produkty.append([
                    datetime.today().strftime("%Y-%m-%d"),
                    image_formula,
                    nazwa,
                    cena_pln,
                    pelny_url,
                ])
                pobrane_na_stronie += 1

            if progress_callback:
                progress_callback(len(wszystkie_produkty), max(total_estimated, len(wszystkie_produkty)), pominiete_duplikaty)

            if pobrane_na_stronie == 0:
                break

            page += 1
            time.sleep(0.4)

        except Exception as e:
            print(f"Błąd podczas scrapowania Lidla (strona {page}): {e}")
            break

    return wszystkie_produkty

def get_sheet(sheet_name):
    json_creds_raw = (
        os.getenv("GOOGLE_CREDENTIALS_JSON") 
        or os.getenv("GOOGLE_CREDENTIALS") 
        or os.getenv("GCP_SA_KEY")
    )
    if json_creds_raw:
        creds_dict = json.loads(json_creds_raw)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
    else:
        creds_file = "credentials.json"
        creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, SCOPE)

    client = gspread.authorize(creds)
    return client.open(sheet_name).sheet1

def write_to_sheet(sheet, wszystkie_produkty):
    sheet.clear()
    sheet.append_row(["Data pobrania", "Zdjęcie", "Nazwa produktu", "Cena (PLN)", "Link do produktu"])

    if wszystkie_produkty:
        sheet.append_rows(wszystkie_produkty, value_input_option="USER_ENTERED")
        total_rows = len(wszystkie_produkty) + 1
        try:
            body = {
                "requests": [
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet.id,
                                "dimension": "ROWS",
                                "startIndex": 1,
                                "endIndex": total_rows,
                            },
                            "properties": {"pixelSize": 80},
                            "fields": "pixelSize",
                        }
                    },
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet.id,
                                "dimension": "COLUMNS",
                                "startIndex": 1,
                                "endIndex": 2,
                            },
                            "properties": {"pixelSize": 100},
                            "fields": "pixelSize",
                        }
                    },
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet.id,
                                "startRowIndex": 1,
                                "endRowIndex": total_rows,
                                "startColumnIndex": 1,
                                "endColumnIndex": 2,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "horizontalAlignment": "CENTER",
                                    "verticalAlignment": "MIDDLE",
                                }
                            },
                            "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment)",
                        }
                    },
                ]
            }
            sheet.spreadsheet.batch_update(body)
        except Exception as e:
            print(f"Wymiary komórek error: {e}")

    return f"https://docs.google.com/spreadsheets/d/{sheet.spreadsheet.id}/edit"

def scrape_lidl_web(category_id=None, max_products=None, progress_callback=None):
    sheet = get_sheet(DEFAULT_SHEET_NAME)
    wszystkie_produkty = extract_lidl_products(category_id, max_products=max_products, progress_callback=progress_callback)
    sheet_url = write_to_sheet(sheet, wszystkie_produkty)
    return sheet_url