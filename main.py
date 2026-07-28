from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import uuid
from scraper import scrape_sinsay_web

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Słownik na aktywne zadania w pamięci
tasks = {}

def run_scraping_task(task_id: str, store: str, category: str):
    def update_progress(current, total):
        tasks[task_id]["current"] = current
        tasks[task_id]["total"] = total

    try:
        tasks[task_id]["status"] = "running"
        
        # Wywołanie nowej funkcji ze scraper.py
        sheet_url = scrape_sinsay_web(category_id=category, progress_callback=update_progress)
            
        tasks[task_id]["status"] = "completed"
        tasks[task_id]["result_url"] = sheet_url
    except Exception as e:
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["error"] = str(e)

@app.post("/start_scrape")
def start_scrape(data: dict, background_tasks: BackgroundTasks):
    store = data.get("store")
    category = data.get("category")
    
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "status": "pending",
        "current": 0,
        "total": 0,
        "result_url": None,
        "error": None
    }
    
    background_tasks.add_task(run_scraping_task, task_id, store, category)
    return {"task_id": task_id}

@app.get("/status/{task_id}")
def get_status(task_id: str):
    task = tasks.get(task_id)
    if not task:
        return {"status": "not_found"}
    return task