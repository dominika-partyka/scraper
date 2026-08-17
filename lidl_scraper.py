import argparse
import json
import re
import time
from datetime import datetime
import os
import urllib.parse
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
    "Accept": "application/json, text/plain, */*"
}

# Usunięto 'Żywność i napoje' z listy głównych kafelków
LIDL_MAIN_TILES = [
    {"name": "Promocje", "url": "https://www.lidl.pl/q/query/wyprzedaz"},
    {"name": "Dom i wyposażenie wnętrz", "url": "https://www.lidl.pl/c/dom-i-wyposazenie-wnetrz/s10067762"},
    {"name": "Kuchnia, sprzątanie i organizacja", "url": "https://www.lidl.pl/c/kuchnia-sprzatanie-i-organizacja/s10067764"},
    {"name": "Warsztat i ogród", "url": "https://www.lidl.pl/c/warsztat-i-ogrod/s10067761"},
    {"name": "Sport i wypoczynek", "url": "https://www.lidl.pl/c/sport-i-wypoczynek/s10067763"},
    {"name": "Moda i akcesoria", "url": "https://www.lidl.pl/c/moda-i-akcesoria/s10067765"},
    {"name": "Niemowlę, dziecko i zabawki", "url": "https://www.lidl.pl/c/niemowle-dziecko-i-zabawki/s10067767"},
]

DEFAULT_LIDL_CATEGORIES = [
    {"id": tile["url"], "name": f"{tile['name']} > Wszystkie produkty", "url": tile["url"]}
    for tile in LIDL_MAIN_TILES
]

def fetch_single_tile(tile):
    main_name = tile["name"]
    main_url = tile["url"]
    tile_categories = []

    tile_categories.append({
        "id": main_url,
        "name": f"{main_name} > Wszystkie produkty",
        "url": main_url
    })

    try:
        resp = requests.get(main_url, headers=HEADERS, timeout=6)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            sub_links = soup.select("li.ux-base-slider__slide a, a.ANavigationPill, a.odsc-link-action")
            
            for link_el in sub_links:
                a_tag = link_el if link_el.name == "a" else link_el.find_parent("a")
                if not a_tag:
                    continue

                href = a_tag.get("href", "")
                text = a_tag.get_text(strip=True)

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
    all_categories = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(fetch_single_tile, LIDL_MAIN_TILES)
        for tile_cats in results:
            for cat in tile_cats:
                if not any(c["url"] == cat["url"] for c in all_categories):
                    all_categories.append(cat)
    return all_categories if all_categories else DEFAULT_LIDL_CATEGORIES

def parse_price_value(val):
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        match = re.search(r"(\d+[\.,]?\d*)", val)
        if match:
            try:
                return float(match.group(1).replace(",", "."))
            except ValueError:
                return 0.0
    return 0.0

def find_price_deep(obj):
    if not isinstance(obj, dict):
        return 0.0

    priority_keys = ["price", "current", "discountedPrice", "rawPrice", "value", "strikethroughPrice", "amount"]
    for k in priority_keys:
        if k in obj and obj[k] is not None:
            v = parse_price_value(obj[k])
            if v > 0:
                return v

    text_keys = ["formattedPrice", "formatted", "display", "text"]
    for k in text_keys:
        if k in obj and obj[k]:
            v = parse_price_value(str(obj[k]))
            if v > 0:
                return v

    for k, v in obj.items():
        if "price" in k.lower() and isinstance(v, dict):
            sub_p = find_price_deep(v)
            if sub_p > 0:
                return sub_p

    return 0.0

def extract_lidl_products(category_url, max_products=None, progress_callback=None):
    wszystkie_produkty = []
    seen_urls = set()
    pominiete_duplikaty = 0
    offset = 0

    clean_path = category_url.replace("https://www.lidl.pl/", "").replace("http://www.lidl.pl/", "").strip("/")
    if clean_path.startswith("h/") or clean_path.startswith("c/"):
        category_slug = clean_path[2:]
    else:
        category_slug = clean_path

    while True:
        if max_products and len(wszystkie_produkty) >= max_products:
            break

        api_url = (
            f"https://www.lidl.pl/q/api/category/{category_slug}"
            f"?offset={offset}&fetchsize=48&locale=pl_PL&assortment=PL&version=2.1.0"
        )

        try:
            resp = requests.get(api_url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                print(f"Błąd API Lidla: Status {resp.status_code}")
                break

            data = resp.json()
            products = data.get("items", [])

            if not products or not isinstance(products, list):
                break

            pobrane_na_stronie = 0

            for item in products:
                if max_products and len(wszystkie_produkty) >= max_products:
                    break

                gridbox = item.get("gridbox", {}) if isinstance(item.get("gridbox"), dict) else {}
                grid_data = gridbox.get("data", {}) if isinstance(gridbox.get("data"), dict) else item

                # Pomiń kategorie spożywcze, jeśli przypadkowo trafią do pętli
                category_type = str(grid_data.get("category", "")).lower()
                if "food" in category_type or "zywnosc" in category_type:
                    continue

                # 1. Nazwa
                brand_obj = grid_data.get("brand", {})
                brand_name = brand_obj.get("name", "") if isinstance(brand_obj, dict) else ""
                raw_title = (
                    grid_data.get("title")
                    or grid_data.get("fullTitle")
                    or grid_data.get("gridTitle")
                    or grid_data.get("name")
                    or ""
                ).strip()

                if brand_name and raw_title and not raw_title.lower().startswith(brand_name.lower()):
                    nazwa = f"{brand_name} {raw_title}"
                else:
                    nazwa = raw_title or brand_name or f"Produkt {item.get('code', '')}"

                # 2. URL
                canonical_path = grid_data.get("canonicalPath") or grid_data.get("canonicalUrl") or grid_data.get("url") or ""
                code = str(item.get("code") or grid_data.get("code") or "").strip()
                if canonical_path:
                    pelny_url = canonical_path if canonical_path.startswith("http") else f"https://www.lidl.pl{canonical_path}"
                elif code:
                    pelny_url = f"https://www.lidl.pl/p/p{code}"
                else:
                    continue

                pelny_url_clean = pelny_url.split('#')[0].split('?')[0]

                if pelny_url_clean in seen_urls:
                    pominiete_duplikaty += 1
                    continue

                seen_urls.add(pelny_url_clean)

                # 3. Odczyt Ceny z API
                cena_pln = 0.0
                price_sources = [
                    grid_data.get("price"),
                    grid_data.get("price_V1"),
                    grid_data.get("gridPrice"),
                    grid_data.get("priceDiscount"),
                    item.get("price"),
                    grid_data
                ]

                for src in price_sources:
                    if isinstance(src, dict):
                        cena_pln = find_price_deep(src)
                        if cena_pln > 0:
                            break

                # 4. Zdjęcie z doświetleniem tła dla Google Sheets
                photo_url = grid_data.get("image") or grid_data.get("gridImage") or ""
                if isinstance(photo_url, dict):
                    photo_url = photo_url.get("src") or photo_url.get("url") or ""

                if not photo_url and isinstance(grid_data.get("imageList"), list) and len(grid_data["imageList"]) > 0:
                    first_img = grid_data["imageList"][0]
                    if isinstance(first_img, str):
                        photo_url = first_img
                    elif isinstance(first_img, dict):
                        photo_url = first_img.get("image") or first_img.get("src") or ""

                if photo_url and photo_url.startswith("//"):
                    photo_url = "https:" + photo_url

                if photo_url:
                    encoded_url = urllib.parse.quote(photo_url, safe='')
                    photo_url = f"https://images.weserv.nl/?url={encoded_url}&bg=white&output=jpg"

                image_formula = f'=IMAGE("{photo_url}")' if photo_url else ""

                wszystkie_produkty.append([
                    datetime.today().strftime("%Y-%m-%d"),
                    image_formula,
                    nazwa,
                    cena_pln,
                    pelny_url_clean,
                ])
                pobrane_na_stronie += 1

            if progress_callback:
                progress_callback(len(wszystkie_produkty), max(1, len(wszystkie_produkty)), pominiete_duplikaty)

            if pobrane_na_stronie == 0:
                break

            offset += 48
            time.sleep(0.2)

        except Exception as e:
            print(f"Błąd: {e}")
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