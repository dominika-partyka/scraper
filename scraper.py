import argparse
import json
import re
import time
from datetime import datetime
import os

import gspread
import requests
from oauth2client.service_account import ServiceAccountCredentials

try:
    import chompjs
except ImportError:
    chompjs = None

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

DEFAULT_SHEET_NAME = "Scraper"
DEFAULT_PAGE_SIZE = 100

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Referer": "https://www.sinsay.com/",
}


def get_categories_from_api():
    """Pobiera strukturę kategorii z API Sinsay lub z danych menu strony głównej."""
    url = "https://arch.sinsay.com/api/17/category/tree"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError:
                payload = None

            if isinstance(payload, dict):
                if isinstance(payload.get("tree"), list) and payload.get("tree"):
                    return payload["tree"]
                if isinstance(payload.get("categories"), list) and payload.get("categories"):
                    return payload["categories"]
                if isinstance(payload.get("items"), list) and payload.get("items"):
                    return payload["items"]
            elif isinstance(payload, list) and payload:
                return payload
    except Exception as e:
        print(f"Błąd podczas połączenia z API Sinsay: {e}")

    try:
        homepage_response = requests.get("https://www.sinsay.com/pl/pl/", headers=HEADERS, timeout=15)
        if homepage_response.status_code == 200:
            match = re.search(r'<script[^>]*id="menu-data"[^>]*>(.*?)</script>', homepage_response.text, re.S)
            if match:
                payload = json.loads(match.group(1))
                if isinstance(payload, dict):
                    return payload.get("tree") or payload.get("categories") or payload.get("items") or []
    except Exception as e:
        print(f"Błąd podczas pobierania strony Sinsay: {e}")

    return []


def extract_flat_categories(category_tree):
    flat_list = []
    nodes = category_tree if isinstance(category_tree, list) else []

    def traverse(nodes, parent_path=""):
        if not isinstance(nodes, list):
            return

        for node in nodes:
            if not isinstance(node, dict):
                continue

            cat_id = str(node.get("id") or node.get("category_id") or "")
            name = node.get("name") or node.get("label") or ""
            url_path = node.get("url") or node.get("path") or ""
            children = node.get("children") or node.get("items") or node.get("subcategories") or []

            current_path = f"{parent_path} > {name}" if parent_path else name

            if cat_id and name:
                flat_list.append({
                    "id": cat_id,
                    "name": current_path,
                    "url": url_path,
                })

            if children:
                traverse(children, current_path)

    traverse(nodes)
    return flat_list


def resolve_category(provided_category_id=None):
    tree = get_categories_from_api()
    categories = extract_flat_categories(tree)

    if provided_category_id:
        provided_id_str = str(provided_category_id).strip()
        for cat in categories:
            if cat["id"] == provided_id_str or cat["url"] == provided_id_str:
                return cat
        return {"id": provided_id_str, "url": provided_id_str}

    if categories:
        return categories[0]
    return {"id": "1769", "url": "woman/clothes/dresses"}


def parse_js_object_fallback(js_code):
    js_code = re.sub(r'([{,]\s*)([a-zA-Z0-9_]+)\s*:', r'\1"\2":', js_code)
    js_code = js_code.replace("'", '"')
    js_code = re.sub(r'!!0', 'false', js_code)
    js_code = re.sub(r'!!1', 'true', js_code)
    return json.loads(js_code)


def extract_photo_url(prod_dict):
    photo = ""
    if isinstance(prod_dict.get("img"), list) and prod_dict["img"]:
        photo = prod_dict["img"][0]
    elif isinstance(prod_dict.get("firstPhoto"), dict):
        fp = prod_dict["firstPhoto"]
        photo = fp.get("url") or fp.get("path") or ""
    elif isinstance(prod_dict.get("photos"), list) and prod_dict["photos"]:
        first_p = prod_dict["photos"][0]
        photo = first_p.get("url") if isinstance(first_p, dict) else first_p

    if isinstance(photo, str) and photo:
        if photo.startswith("//"):
            return f"https:{photo}"
        elif photo.startswith("http"):
            return photo
        else:
            return f"https://static.sinsay.com/{photo.lstrip('/')}"
            
    return ""


def fetch_products_with_pagination(category_url, max_products=None, progress_callback=None):
    if not category_url.startswith("http"):
        category_url = f"https://www.sinsay.com/pl/pl/{category_url.lstrip('/')}"

    print(f"Analizuję podstronę kategorii: {category_url}")
    wszystkie_produkty = []
    seen_ids = set()
    pominiete_duplikaty = 0

    try:
        response = requests.get(category_url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            print(f"Błąd HTTP: {response.status_code}")
            return []

        match = re.search(
            r'window\.getCatalogData\s*=\s*function\(\)\s*\{\s*return\s*(\{.*?\});?\s*\};',
            response.text,
            re.S,
        )
        if not match:
            print("Nie znaleziono window.getCatalogData w HTML strony!")
            return []

        js_object_str = match.group(1)
        if chompjs:
            data = chompjs.parse_js_object(js_object_str)
        else:
            data = parse_js_object_fallback(js_object_str)

        products_list = data.get("products", [])
        total_quantity = data.get("productsQuantity", len(products_list))
        real_cat_id = data.get("categoryId")
        page_size = data.get("pageSize", 120)

        # Powiadomienie na start (0 produktów, total_quantity, 0 duplikatów)
        if progress_callback:
            progress_callback(0, total_quantity, 0)

        # 1. Parsowanie produktów z 1. strony (HTML)
        for prod in products_list:
            prod_id = prod.get("id")
            if prod_id in seen_ids:
                pominiete_duplikaty += 1
                continue
            seen_ids.add(prod_id)

            nazwa = prod.get("name")
            cena_raw = prod.get("final_price") or prod.get("price")
            cena_pln = float(str(cena_raw).replace(",", ".")) if cena_raw else 0.0

            url_val = prod.get("url") or ""
            pelny_url = url_val if str(url_val).startswith("http") else f"https://www.sinsay.com/pl/pl/{str(url_val).lstrip('/')}"

            photo_url = extract_photo_url(prod)
            image_formula = f'=IMAGE("{photo_url}")' if photo_url else ""

            wszystkie_produkty.append([
                datetime.today().strftime("%Y-%m-%d"),
                image_formula,
                nazwa,
                cena_pln,
                pelny_url,
            ])

        # Powiadomienie po parsowaniu 1. strony z uwzględnieniem duplikatów
        if progress_callback:
            progress_callback(len(wszystkie_produkty), total_quantity, pominiete_duplikaty)

        # 2. Pętla API po offsetach
        offset = len(products_list)

        while offset < total_quantity:
            if max_products and len(wszystkie_produkty) >= max_products:
                break

            api_url = (
                f"https://arch.sinsay.com/api/17/category/{real_cat_id}/productsWithoutFilters"
                f"?flags[showMerchantProducts]=1&offset={offset}&pageSize={page_size}"
            )

            try:
                page_resp = requests.get(api_url, headers=HEADERS, timeout=15)
                if page_resp.status_code == 200:
                    page_data = page_resp.json()
                    next_products = page_data.get("products", [])

                    if not next_products:
                        break

                    for prod in next_products:
                        prod_id = prod.get("id")
                        if prod_id in seen_ids:
                            pominiete_duplikaty += 1
                            continue
                        seen_ids.add(prod_id)

                        nazwa = prod.get("name")
                        cena_raw = prod.get("final_price") or prod.get("price")
                        cena_pln = float(str(cena_raw).replace(",", ".")) if cena_raw else 0.0

                        url_val = prod.get("url") or ""
                        pelny_url = url_val if str(url_val).startswith("http") else f"https://www.sinsay.com/pl/pl/{str(url_val).lstrip('/')}"

                        photo_url = extract_photo_url(prod)
                        image_formula = f'=IMAGE("{photo_url}")' if photo_url else ""

                        wszystkie_produkty.append([
                            datetime.today().strftime("%Y-%m-%d"),
                            image_formula,
                            nazwa,
                            cena_pln,
                            pelny_url,
                        ])

                    offset += page_size

                    # Powiadomienie w pętli z aktualną liczbą duplikatów
                    if progress_callback:
                        progress_callback(len(wszystkie_produkty), total_quantity, pominiete_duplikaty)

                    time.sleep(0.3)
                else:
                    break
            except Exception as e:
                print(f"Błąd API: {e}")
                break

        return wszystkie_produkty

    except Exception as e:
        print(f"Błąd główny scrapowania: {e}")
        return wszystkie_produkty


def get_sheet(sheet_name):
    # Odczytujemy JSON bezpośrednio ze zmiennej środowiskowej na Renderze
    json_creds_raw = (
        os.getenv("GOOGLE_CREDENTIALS_JSON") 
        or os.getenv("GOOGLE_CREDENTIALS") 
        or os.getenv("GCP_SA_KEY")
    )
    
    if json_creds_raw:
        # Konwersja ze tekstu JSON na słownik w pamięci
        creds_dict = json.loads(json_creds_raw)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
    else:
        # Fallback dla lokalnego uruchamiania na komputerze
        creds_file = "credentials.json"
        if not os.path.exists(creds_file):
            raise FileNotFoundError(
                "Nie znaleziono zmiennej GOOGLE_CREDENTIALS_JSON na Renderze ani pliku credentials.json lokalnie."
            )
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
            print(f"Uwaga wymiary komórek: {e}")

    return f"https://docs.google.com/spreadsheets/d/{sheet.spreadsheet.id}/edit"


def scrape_sinsay_web(category_id=None, max_products=None, progress_callback=None):
    cat_info = resolve_category(category_id)
    sheet = get_sheet(DEFAULT_SHEET_NAME)

    wszystkie_produkty = []
    if isinstance(cat_info, dict) and cat_info.get("url"):
        wszystkie_produkty = fetch_products_with_pagination(
            cat_info["url"], max_products=max_products, progress_callback=progress_callback
        )

    sheet_url = write_to_sheet(sheet, wszystkie_produkty)
    return sheet_url