import argparse
import json
import re
import time
from datetime import datetime
import os
from concurrent.futures import ThreadPoolExecutor

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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}

# Główne kafelki ze strony głównej Lidla
LIDL_MAIN_TILES = [
    {"name": "Promocje", "url": "https://www.lidl.pl/q/query/wyprzedaz"},
    {"name": "Dom i wyposażenie wnętrz", "url": "https://www.lidl.pl/c/dom-i-wyposazenie-wnetrz/s10067762"},
    {"name": "Kuchnia, sprzątanie i organizacja", "url": "https://www.lidl.pl/c/kuchnia-sprzatanie-i-organizacja/s10067764"},
    {"name": "Warsztat i ogród", "url": "https://www.lidl.pl/c/warsztat-i-ogrod/s10067761"},
    {"name": "Sport i wypoczynek", "url": "https://www.lidl.pl/c/sport-i-wypoczynek/s10067763"},
    {"name": "Moda i akcesoria", "url": "https://www.lidl.pl/c/moda-i-akcesoria/s10067765"},
    {"name": "Niemowlę, dziecko i zabawki", "url": "https://www.lidl.pl/c/niemowle-dziecko-i-zabawki/s10067767"},
    {"name": "Żywność i napoje", "url": "https://www.lidl.pl/c/zywnosc-i-napoje/s10068374"},
]

DEFAULT_LIDL_CATEGORIES = [
    {"id": tile["url"], "name": f"{tile['name']} > Wszystkie produkty", "url": tile["url"]}
    for tile in LIDL_MAIN_TILES
]

def fetch_single_tile(tile):
    main_name = tile["name"]
    main_url = tile["url"]
    tile_categories = []

    # Domyślnie KAŻDA kategoria główna ma opcję "Wszystkie produkty"
    tile_categories.append({
        "id": main_url,
        "name": f"{main_name} > Wszystkie produkty",
        "url": main_url
    })

    try:
        resp = requests.get(main_url, headers=HEADERS, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Poszerzone selektory dla wszystkich typów layoutów Lidla
            sub_links = soup.select(
                "li.ux-base-slider__slide a, "
                ".odsc-link-action__element, "
                "a[class*='subnavigation'], "
                "a[class*='chip'], "
                "a[class*='category-pill'], "
                ".navigation-item a"
            )
            
            for link_el in sub_links:
                a_tag = link_el if link_el.name == "a" else link_el.find_parent("a")
                if not a_tag:
                    continue

                href = a_tag.get("href", "")
                text = a_tag.get_text(strip=True)

                # Ignorujemy puste napisy i nawigację po stronach
                if not text or len(text) < 2 or "wszystkie" in text.lower():
                    continue

                full_url = href if href.startswith("http") else f"https://www.lidl.pl{href}"
                full_name = f"{main_name} > {text}"

                if not any(c["url"] == full_url for c in tile_categories):
                    tile_categories.append({
                        "id": full_url,
                        "name": full_name,
                        "url": full_url
                    })

    except Exception as e:
        print(f"Błąd pobierania podkategorii dla {main_name}: {e}")

    return tile_categories

def get_lidl_categories():
    """Pobiera podkategorie ze wszystkich kafelków równolegle."""
    all_categories = []
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(fetch_single_tile, LIDL_MAIN_TILES)
        for tile_cats in results:
            for cat in tile_cats:
                if not any(c["url"] == cat["url"] for c in all_categories):
                    all_categories.append(cat)

    return all_categories if all_categories else DEFAULT_LIDL_CATEGORIES

def extract_lidl_products(category_url, max_products=None, progress_callback=None):
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

        # Paginacja w nowym układzie Lidla
        page_url = f"{category_url}?page={page}" if page > 1 else category_url
        print(f"Scrapuję podstronę Lidla: {page_url}")

        try:
            resp = requests.get(page_url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Wszechstronne selektory kart produktów w Lidlu
            product_cards = soup.select(
                "li.s-grid__item, "
                "article.product-grid-box, "
                "div.product-grid-box, "
                "article, "
                "div[data-product-id], "
                ".grid-box"
            )

            if not product_cards:
                break

            pobrane_na_stronie = 0
            for card in product_cards:
                if max_products and len(wszystkie_produkty) >= max_products:
                    break

                # Tytuł
                title_el = card.select_one(
                    ".product-grid-box__title, "
                    "h2, "
                    ".grid-box__title, "
                    "a.title, "
                    "[class*='title']"
                )
                nazwa = title_el.get_text(strip=True) if title_el else ""

                if not nazwa or len(nazwa) < 3:
                    continue

                # Link do produktu
                link_el = card.select_one("a[href]")
                href = link_el["href"] if link_el else ""
                pelny_url = href if href.startswith("http") else f"https://www.lidl.pl{href}"

                if pelny_url in seen_urls:
                    pominiete_duplikaty += 1
                    continue
                seen_urls.add(pelny_url)

                # Cena (wyciągamy tylko aktualną/promocyjną cenę)
                price_el = card.select_one(
                    ".price-m__price, "
                    ".m-price__price, "
                    ".grid-box__price, "
                    "[class*='price']"
                )
                cena_text = price_el.get_text(strip=True) if price_el else "0"
                
                # Bierzemy pierwszą napotkaną kwotę (żeby nie sklejać ze starą skreśloną ceną)
                match = re.search(r"\d+[\.,]?\d*", cena_text)
                cena_clean = match.group(0).replace(",", ".") if match else "0"
                try:
                    cena_pln = float(cena_clean)
                except ValueError:
                    cena_pln = 0.0

                # Zdjęcie
                img_el = card.select_one("img")
                photo_url = ""
                if img_el:
                    photo_url = img_el.get("src") or img_el.get("data-src") or img_el.get("srcset", "").split(" ")[0] or ""
                    if photo_url.startswith("//"):
                        photo_url = "https:" + photo_url

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

    return f"https://docs.google.com/spreadsheets/d/{sheet.spreadsheet.id}/edit"

def scrape_lidl_web(category_id=None, max_products=None, progress_callback=None):
    sheet = get_sheet(DEFAULT_SHEET_NAME)
    wszystkie_produkty = extract_lidl_products(category_id, max_products=max_products, progress_callback=progress_callback)
    sheet_url = write_to_sheet(sheet, wszystkie_produkty)
    return sheet_url