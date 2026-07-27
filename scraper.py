import argparse
import json
import re
import time
from datetime import datetime

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


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Scrapuj produkty Sinsay do Google Sheets")
    parser.add_argument(
        "--category",
        dest="category_id",
        help="ID kategorii Sinsay (np. 1769). Jeśli nie podasz, wygenerujemy interaktywne menu.",
    )
    parser.add_argument(
        "--sheet",
        default=DEFAULT_SHEET_NAME,
        help=f"Nazwa arkusza w Google Sheets (domyślnie: {DEFAULT_SHEET_NAME})",
    )
    parser.add_argument(
        "--max-products",
        type=int,
        default=None,
        help="Maksymalna liczba produktów do pobrania.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"Rozmiar strony z API (domyślnie: {DEFAULT_PAGE_SIZE})",
    )
    return parser.parse_args(argv)


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
    if provided_category_id:
        return {"id": str(provided_category_id).strip(), "url": ""}

    print("\nPobieram aktualne kategorie z Sinsay...")
    tree = get_categories_from_api()
    categories = extract_flat_categories(tree)

    if not categories:
        category_id = input("Nie udało się pobrać listy. Podaj ID kategorii ręcznie (np. 1769): ").strip()
        return {"id": category_id, "url": ""}

    print("\n--- DOSTĘPNE KATEGORIE SINSAY ---")
    for idx, cat in enumerate(categories, start=1):
        print(f"[{idx}] {cat['name']} (ID: {cat['id']})")
    print("-----------------------------------")

    while True:
        wybor = input(f"\nWybierz numer kategorii (1-{len(categories)}): ").strip()
        if wybor.isdigit():
            num = int(wybor)
            if 1 <= num <= len(categories):
                wybrana = categories[num - 1]
                print(f"\nWybrałeś: {wybrana['name']} (ID: {wybrana['id']})")
                return wybrana

        print(f"Niepoprawny numer. Wpisz liczbę od 1 do {len(categories)}.")


def parse_js_object_fallback(js_code):
    """Fallbackowy parser, gdy chompjs nie jest zainstalowany."""
    js_code = re.sub(r'([{,]\s*)([a-zA-Z0-9_]+)\s*:', r'\1"\2":', js_code)
    js_code = js_code.replace("'", '"')
    js_code = re.sub(r'!!0', 'false', js_code)
    js_code = re.sub(r'!!1', 'true', js_code)
    return json.loads(js_code)


def extract_photo_url(prod_dict):
    """Wyciąga bezpośredni link do zdjęcia z obiektu produktu na podstawie struktury Sinsay."""
    photo = ""
    
    # 1. Najpierw sprawdzamy tablicę 'img' (dokładnie to, co wyszło w konsoli)
    if isinstance(prod_dict.get("img"), list) and prod_dict["img"]:
        photo = prod_dict["img"][0]
    # 2. Zapobiegawczo: sprawdzenie pola 'firstPhoto' lub 'images'
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

def fetch_products_with_pagination(category_url, max_products=None):
    """Pobiera pierwszą stronę z HTML, a następnie dociąga kolejne strony przez API."""
    if not category_url.startswith("http"):
        category_url = f"https://www.sinsay.com/pl/pl/{category_url.lstrip('/')}"

    print(f"Analizuję podstronę kategorii: {category_url}")
    wszystkie_produkty = []
    seen_ids = set()
    pominiete_duplikaty = 0

    try:
        response = requests.get(category_url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            return []

        match = re.search(
            r'window\.getCatalogData\s*=\s*function\(\)\s*\{\s*return\s*(\{.*?\});?\s*\};',
            response.text,
            re.S,
        )
        if not match:
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

        print(f"Liczba produktów zgłoszona przez serwer: {total_quantity}")

        # 1. Parsujemy produkty z 1. strony (z HTML)
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

        print(f"Strona 1 (HTML): pobrano {len(wszystkie_produkty)} unikalnych produktów.")

        # 2. Pętla paginacji po OFFSET
        offset = len(products_list)

        while offset < total_quantity:
            if max_products and len(wszystkie_produkty) >= max_products:
                print(f"Osiągnięto limit max_products ({max_products}).")
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

                    pobrane_w_pętli = 0
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
                        pobrane_w_pętli += 1

                    offset += page_size
                    print(f"Pobieranie... (offset {offset}/{total_quantity}) -> Łącznie unikalnych: {len(wszystkie_produkty)}")
                    time.sleep(0.4)
                else:
                    print(f"Błąd API na offset {offset}. Kod: {page_resp.status_code}")
                    break
            except Exception as e:
                print(f"Błąd podczas pobierania offset {offset}: {e}")
                break

        print("\n--- PODSUMOWANIE POBIERANIA ---")
        print(f"Przeszukano pozycji: {total_quantity}")
        print(f"Zapisano unikalnych produktów: {len(wszystkie_produkty)}")
        print(f"Odrzucono duplikatów: {pominiete_duplikaty}")
        print("-------------------------------\n")

        return wszystkie_produkty

    except Exception as e:
        print(f"Błąd podczas analizy kategorii z paginacją: {e}")

    return wszystkie_produkty


def get_sheet(sheet_name):
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
    client = gspread.authorize(creds)
    return client.open(sheet_name).sheet1


def write_to_sheet(sheet, wszystkie_produkty):
    sheet.clear()
    sheet.append_row(["Data pobrania", "Zdjęcie", "Nazwa produktu", "Cena (PLN)", "Link do produktu"])

    if wszystkie_produkty:
        # Pchamy dane przekazując USER_ENTERED, żeby Google uaktywnił wzór =IMAGE()
        sheet.append_rows(wszystkie_produkty, value_input_option="USER_ENTERED")

        # Rozszerzamy komórki automatycznie
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
                            "properties": {"pixelSize": 80},  # Wysokość wiersza na 80px
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
                            "properties": {"pixelSize": 100}, # Szerokość kolumny ze zdjęciem na 100px
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
            print("Powiększono komórki w arkuszu – zdjęcia są już czytelne!")
        except Exception as e:
            print(f"Uwaga: Nie udało się automatycznie zmienić rozmiarów komórek przez API: {e}")


def main(argv=None):
    args = parse_args(argv)
    cat_info = resolve_category(args.category_id)

    try:
        sheet = get_sheet(args.sheet)
        print("Połączono z Google Sheets!")
    except Exception as e:
        print(f"Błąd połączenia z Sheets: {e}")
        return 1

    wszystkie_produkty = []

    if isinstance(cat_info, dict) and cat_info.get("url"):
        wszystkie_produkty = fetch_products_with_pagination(cat_info["url"], max_products=args.max_products)

    if wszystkie_produkty:
        print(f"\nGotowe! Zapisuję {len(wszystkie_produkty)} wierszy ze zdjęciami do Google Sheets...")
        write_to_sheet(sheet, wszystkie_produkty)
        print("Sukces! Zapisano wszystkie produkty i dostosowano rozmiar komórek.")
    else:
        print("Brak danych do zapisania.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())