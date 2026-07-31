from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import uuid
from scraper import scrape_sinsay_web, get_categories_from_api, extract_flat_categories

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

tasks = {}

def run_scraping_task(task_id: str, store: str, category: str, max_products: int = None):
    def update_progress(current, total, duplicates=0):
        tasks[task_id]["current"] = current
        tasks[task_id]["total"] = total
        tasks[task_id]["duplicates"] = duplicates

    try:
        tasks[task_id]["status"] = "running"
        sheet_url = scrape_sinsay_web(
            category_id=category, 
            max_products=max_products, 
            progress_callback=update_progress
        )
            
        tasks[task_id]["status"] = "completed"
        tasks[task_id]["result_url"] = sheet_url
    except Exception as e:
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["error"] = str(e)

@app.get("/categories/{store}")
def get_categories(store: str):
    if store == "sinsay":
        try:
            tree = get_categories_from_api()
            flat_categories = extract_flat_categories(tree)
            return {"categories": flat_categories}
        except Exception as e:
            print(f"Błąd pobierania kategorii: {e}")
            return {"categories": []}
    return {"categories": []}

@app.post("/start_scrape")
def start_scrape(data: dict, background_tasks: BackgroundTasks):
    store = data.get("store")
    category = data.get("category")
    max_products = data.get("max_products")
    
    if max_products and str(max_products).isdigit():
        max_products = int(max_products)
    else:
        max_products = None

    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "status": "pending",
        "current": 0,
        "total": 0,
        "duplicates": 0,
        "result_url": None,
        "error": None
    }
    
    background_tasks.add_task(run_scraping_task, task_id, store, category, max_products)
    return {"task_id": task_id}

@app.get("/status/{task_id}")
def get_status(task_id: str):
    task = tasks.get(task_id)
    if not task:
        return {"status": "not_found"}
    return task