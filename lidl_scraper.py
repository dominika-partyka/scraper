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
    "Accept": "application/json, text/plain, */*"
}

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

            # Podgląd struktury pierwszego produktu w logach Rendera
            if offset == 0 and len(products) > 0:
                print("--- PODGLĄD STRUKTURY PIERWSZEGO PRODUKTU ---")
                print(json.dumps(products[0], ensure_ascii=False)[:800])
                print("--------------------------------------------")

            pobrane_na_stronie = 0
            for item in products:
                if max_products and len(wszystkie_produkty) >= max_products:
                    break

                # 1. Wyciąganie nazwy ze wszystkich możliwych pól
                nazwa = ""
                keyfacts = item.get("keyfacts") if isinstance(item.get("keyfacts"), dict) else {}
                nazwa = keyfacts.get("fullTitle") or keyfacts.get("title") or ""

                if not nazwa:
                    nazwa = (
                        item.get("fullTitle")
                        or item.get("gridTitle")
                        or item.get("title")
                        or item.get("canonicalTitle")
                        or item.get("name")
                        or item.get("label")
                        or ""
                    )

                if not nazwa and isinstance(item.get("brand"), dict):
                    nazwa = item.get("brand", {}).get("name", "")

                nazwa = str(nazwa).strip()
                if not nazwa:
                    nazwa = f"Produkt {item.get('code') or item.get('itemId') or ''}"

                # 2. Wyciąganie linku
                code = str(item.get("code") or item.get("itemId") or "").strip()
                url_path = item.get("url") or item.get("canonicalUrl") or ""

                if url_path and len(url_path) > 1:
                    pelny_url = url_path if url_path.startswith("http") else f"https://www.lidl.pl{url_path}"
                elif code:
                    pelny_url = f"https://www.lidl.pl/p/p{code}"
                else:
                    continue

                pelny_url_clean = pelny_url.split('#')[0].split('?')[0]

                if pelny_url_clean in seen_urls:
                    pominiete_duplikaty += 1
                    continue

                seen_urls.add(pelny_url_clean)

                # 3. Wyciąganie ceny ze słownika lub liczby
                cena_pln = 0.0
                price_data = item.get("price") or item.get("price_V1") or item.get("prices") or {}

                if isinstance(price_data, dict):
                    val = (
                        price_data.get("price")
                        or price_data.get("current")
                        or price_data.get("value")
                        or price_data.get("rawPrice")
                        or price_data.get("amount")
                    )
                    if val is not None:
                        try:
                            cena_pln = float(val)
                        except (ValueError, TypeError):
                            cena_pln = 0.0

                    if cena_pln == 0.0:
                        fmt = (
                            price_data.get("formattedPrice")
                            or price_data.get("formatted")
                            or price_data.get("display")
                            or ""
                        )
                        match = re.search(r"(\d+[\.,]?\d*)", str(fmt))
                        if match:
                            try:
                                cena_pln = float(match.group(1).replace(",", "."))
                            except ValueError:
                                cena_pln = 0.0

                elif isinstance(price_data, (int, float)):
                    cena_pln = float(price_data)

                # 4. Wyciąganie zdjęcia
                photo_url = ""
                img_val = item.get("image")
                if isinstance(img_val, str) and img_val.startswith("http"):
                    photo_url = img_val
                elif isinstance(img_val, dict):
                    photo_url = img_val.get("src") or img_val.get("url") or ""

                if not photo_url:
                    img_v1 = item.get("image_V1")
                    if isinstance(img_v1, dict):
                        photo_url = img_v1.get("image") or ""
                    elif isinstance(img_v1, str):
                        photo_url = img_v1

                if not photo_url and isinstance(item.get("imageList"), list) and len(item["imageList"]) > 0:
                    first_img = item["imageList"][0]
                    if isinstance(first_img, str):
                        photo_url = first_img
                    elif isinstance(first_img, dict):
                        photo_url = first_img.get("image") or first_img.get("src") or ""

                if photo_url and photo_url.startswith("//"):
                    photo_url = "https:" + photo_url

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
            print(f"Błąd przetwarzania API Lidla: {e}")
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