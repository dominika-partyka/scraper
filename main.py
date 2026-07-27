import json
import os
import re
import time
from datetime import datetime
from typing import List, Optional

import gspread
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from oauth2client.service_account import ServiceAccountCredentials
from pydantic import BaseModel

try:
    import chompjs
except ImportError:
    chompjs = None

app = FastAPI(title="Multi-Store Scraper API")

# Konfiguracja CORS (umożliwia połączenie ze stroną na GitHub Pages)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
FIXED_SHEET_NAME = "Scraper"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Referer": "https://www.sinsay.com/",
}

def get_gspread_client():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
    else:
        if not os.path.exists("credentials.json"):
            raise HTTPException(status_code=500, detail="Brak credentials.json!")
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
    return gspread.authorize(creds)

# --- BASE SCRAPER CLASS ---
class BaseScraper:
    def get_categories(self) -> List[dict]:
        raise NotImplementedError

    def scrape_products(self, category_id: str, max_products: Optional[int]) -> dict:
        raise NotImplementedError

# --- SINSAY SCRAPER ---
class SinsayScraper(BaseScraper):
    def extract_photo_url(self, prod_dict):
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

    def get_categories(self) -> List[dict]:
        tree = []
        try:
            res = requests.get("https://arch.sinsay.com/api/17/category/tree", headers=HEADERS, timeout=10)
            if res.status_code == 200:
                payload = res.json()
                tree = payload.get("tree") or payload.get("categories") or payload.get("items") or []
        except Exception:
            pass

        if not tree:
            try:
                hp = requests.get("https://www.sinsay.com/pl/pl/", headers=HEADERS, timeout=10)
                if hp.status_code == 200:
                    m = re.search(r'<script[^>]*id="menu-data"[^>]*>(.*?)</script>', hp.text, re.S)
                    if m:
                        payload = json.loads(m.group(1))
                        tree = payload.get("tree") or payload.get("categories") or payload.get("items") or []
            except Exception:
                pass

        flat_list = []
        def traverse(nodes, parent_path=""):
            if not isinstance(nodes, list):
                return
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                cat_id = str(node.get("id") or node.get("category_id") or "")
                name = node.get("name") or node.get("label") or ""
                children = node.get("children") or node.get("items") or node.get("subcategories") or []
                curr_path = f"{parent_path} > {name}" if parent_path else name
                if cat_id and name:
                    flat_list.append({"id": cat_id, "name": curr_path})
                if children:
                    traverse(children, curr_path)

        traverse(tree)
        return flat_list

    def scrape_products(self, category_id: str, max_products: Optional[int]) -> dict:
        cat_url = f"https://www.sinsay.com/pl/pl/category-{category_id}"
        all_products = []
        seen_ids = set()
        duplicates_count = 0

        res = requests.get(cat_url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            raise Exception("Nie udało się pobrać strony kategorii Sinsay.")

        m = re.search(r'window\.getCatalogData\s*=\s*function\(\)\s*\{\s*return\s*(\{.*?\});?\s*\};', res.text, re.S)
        if not m:
            raise Exception("Nie odnaleziono katalogu produktów.")

        js_str = m.group(1)
        data = chompjs.parse_js_object(js_str) if chompjs else json.loads(js_str)
        products_list = data.get("products", [])
        total_quantity = data.get("productsQuantity", len(products_list))
        real_cat_id = data.get("categoryId", category_id)
        page_size = data.get("pageSize", 120)

        for prod in products_list:
            p_id = prod.get("id")
            if p_id in seen_ids:
                duplicates_count += 1
                continue
            seen_ids.add(p_id)
            price_raw = prod.get("final_price") or prod.get("price")
            price_pln = float(str(price_raw).replace(",", ".")) if price_raw else 0.0
            u_val = prod.get("url") or ""
            full_url = u_val if str(u_val).startswith("http") else f"https://www.sinsay.com/pl/pl/{str(u_val).lstrip('/')}"
            photo_url = self.extract_photo_url(prod)

            all_products.append([
                datetime.today().strftime("%Y-%m-%d"),
                f'=IMAGE("{photo_url}")' if photo_url else "",
                prod.get("name"),
                price_pln,
                full_url,
            ])

        offset = len(products_list)
        while offset < total_quantity:
            if max_products and len(all_products) >= max_products:
                break
            api_url = f"https://arch.sinsay.com/api/17/category/{real_cat_id}/productsWithoutFilters?flags[showMerchantProducts]=1&offset={offset}&pageSize={page_size}"
            p_resp = requests.get(api_url, headers=HEADERS, timeout=15)
            if p_resp.status_code == 200:
                next_prods = p_resp.json().get("products", [])
                if not next_prods:
                    break
                for prod in next_prods:
                    p_id = prod.get("id")
                    if p_id in seen_ids:
                        duplicates_count += 1
                        continue
                    seen_ids.add(p_id)
                    price_raw = prod.get("final_price") or prod.get("price")
                    price_pln = float(str(price_raw).replace(",", ".")) if price_raw else 0.0
                    u_val = prod.get("url") or ""
                    full_url = u_val if str(u_val).startswith("http") else f"https://www.sinsay.com/pl/pl/{str(u_val).lstrip('/')}"
                    photo_url = self.extract_photo_url(prod)

                    all_products.append([
                        datetime.today().strftime("%Y-%m-%d"),
                        f'=IMAGE("{photo_url}")' if photo_url else "",
                        prod.get("name"),
                        price_pln,
                        full_url,
                    ])
                offset += page_size
                time.sleep(0.3)
            else:
                break

        if max_products:
            all_products = all_products[:max_products]

        # Save to Google Sheets
        client = get_gspread_client()
        sheet = client.open(FIXED_SHEET_NAME).sheet1
        sheet.clear()
        sheet.append_row(["Data pobrania", "Zdjęcie", "Nazwa produktu", "Cena (PLN)", "Link do produktu"])

        if all_products:
            sheet.append_rows(all_products, value_input_option="USER_ENTERED")
            total_rows = len(all_products) + 1
            body = {
                "requests": [
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": sheet.id, "dimension": "ROWS", "startIndex": 1, "endIndex": total_rows},
                            "properties": {"pixelSize": 80},
                            "fields": "pixelSize",
                        }
                    },
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": sheet.id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
                            "properties": {"pixelSize": 100},
                            "fields": "pixelSize",
                        }
                    },
                ]
            }
            try:
                sheet.spreadsheet.batch_update(body)
            except Exception:
                pass

        return {
            "searched": total_quantity,
            "duplicates": duplicates_count,
            "saved": len(all_products)
        }

# --- PLACEHOLDERY POD LIDLA I BIEDRONKĘ ---
class LidlScraper(BaseScraper):
    def get_categories(self) -> List[dict]:
        return [{"id": "lidl-demo", "name": "Lidl - Funkcja w trakcie przygotowywania"}]
    def scrape_products(self, category_id: str, max_products: Optional[int]) -> dict:
        raise HTTPException(status_code=501, detail="Scraper dla Lidla nie jest jeszcze gotowy.")

class BiedronkaScraper(BaseScraper):
    def get_categories(self) -> List[dict]:
        return [{"id": "biedronka-demo", "name": "Biedronka - Funkcja w trakcie przygotowywania"}]
    def scrape_products(self, category_id: str, max_products: Optional[int]) -> dict:
        raise HTTPException(status_code=501, detail="Scraper dla Biedronki nie jest jeszcze gotowy.")

# REGESTR SCRAPERÓW
SCRAPERS = {
    "sinsay": SinsayScraper(),
    "lidl": LidlScraper(),
    "biedronka": BiedronkaScraper(),
}

class ScrapePayload(BaseModel):
    shop: str
    category_id: str
    max_products: Optional[int] = None

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/categories")
def get_categories(shop: str):
    scraper = SCRAPERS.get(shop.lower())
    if not scraper:
        raise HTTPException(status_code=400, detail="Nieznany sklep")
    return {"categories": scraper.get_categories()}

@app.post("/api/scrape")
def run_scrape(payload: ScrapePayload):
    scraper = SCRAPERS.get(payload.shop.lower())
    if not scraper:
        raise HTTPException(status_code=400, detail="Nieznany sklep")
    try:
        stats = scraper.scrape_products(payload.category_id, payload.max_products)
        return {"success": True, "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))