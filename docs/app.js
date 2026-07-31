const BACKEND_URL = "https://scraper-backend-lxaw.onrender.com";

let selectedStore = null;

document.addEventListener("DOMContentLoaded", () => {
    const storeCards = document.querySelectorAll(".store-card");
    const formSection = document.getElementById("form-section");
    const startBtn = document.getElementById("start-btn");
    const categorySelect = document.getElementById("category-select");
    const manualCatInput = document.getElementById("manual-cat-id");
    const maxProductsInput = document.getElementById("max-products");

    const statusSection = document.getElementById("status-section");
    const loader = document.getElementById("loader");
    const statusText = document.getElementById("status-text");
    const summaryBox = document.getElementById("summary-box");
    const sheetsBtn = document.getElementById("sheets-btn");

    // 1. Wybór kafelka
    storeCards.forEach(card => {
        card.addEventListener("click", async () => {
            storeCards.forEach(c => c.classList.remove("active"));
            card.classList.add("active");

            selectedStore = card.getAttribute("data-shop");

            if (selectedStore === "lidl" || selectedStore === "biedronka") {
                if (formSection) formSection.classList.add("hidden");
                if (statusSection) statusSection.classList.remove("hidden");
                if (loader) loader.style.display = "none";
                if (summaryBox) summaryBox.classList.add("hidden");
                
                const storeName = selectedStore === "lidl" ? "Lidl" : "Biedronka";
                if (statusText) statusText.innerText = `⏳ Obsługa sklepu ${storeName} w trakcie przygotowywania...`;
                return;
            }

            if (selectedStore === "sinsay") {
                if (statusSection) statusSection.classList.add("hidden");
                if (formSection) formSection.classList.remove("hidden");

                if (categorySelect) {
                    categorySelect.innerHTML = `<option value="">⌛ Pobieranie aktualnych kategorii z Sinsay...</option>`;

                    try {
                        const response = await fetch(`${BACKEND_URL}/categories/sinsay`);
                        const data = await response.json();

                        categorySelect.innerHTML = `<option value="">-- Wybierz kategorię z listy --</option>`;

                        if (data.categories && data.categories.length > 0) {
                            data.categories.forEach(cat => {
                                const option = document.createElement("option");
                                option.value = cat.id; // wysyłamy ID lub url
                                option.textContent = `${cat.name} (ID: ${cat.id})`;
                                categorySelect.appendChild(option);
                            });
                        } else {
                            categorySelect.innerHTML = `<option value="">⚠️ Wpisz numer ID ręcznie poniżej (np. 1769)</option>`;
                        }
                    } catch (err) {
                        console.error("Błąd pobierania kategorii:", err);
                        categorySelect.innerHTML = `<option value="">⚠️ Wpisz numer ID ręcznie poniżej (np. 1769)</option>`;
                    }
                }
            }
        });
    });

    // 2. Kliknięcie start
    if (startBtn) {
        startBtn.addEventListener("click", () => {
            const category = manualCatInput.value.trim() || categorySelect.value;
            const maxProducts = maxProductsInput ? maxProductsInput.value : null;

            if (!selectedStore) {
                alert("Wybierz sklep klikając na kafelek!");
                return;
            }

            if (!category) {
                alert("Wybierz kategorię z listy lub wpisz jej ID / ścieżkę ręcznie!");
                return;
            }

            runScraper(selectedStore, category, maxProducts);
        });
    }

    // 3. Proces scrapowania
    async function runScraper(store, category, maxProducts) {
        if (statusSection) statusSection.classList.remove("hidden");
        if (loader) loader.style.display = "block";
        if (summaryBox) summaryBox.classList.add("hidden");
        if (statusText) statusText.innerText = "Inicjalizacja scrapera...";

        try {
            const response = await fetch(`${BACKEND_URL}/start_scrape`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    store: store,
                    category: category,
                    max_products: maxProducts
                })
            });

            const data = await response.json();
            const taskId = data.task_id;

            const interval = setInterval(async () => {
                try {
                    const statusRes = await fetch(`${BACKEND_URL}/status/${taskId}`);
                    const statusData = await statusRes.json();

                    if (statusData.status === "running") {
                        if (statusData.total > 0) {
                            statusText.innerText = `Pobrano ${statusData.current} / ${statusData.total} produktów...`;
                        } else {
                            statusText.innerText = `Pobrano ${statusData.current} produktów...`;
                        }
                    } else if (statusData.status === "completed") {
                        clearInterval(interval);
                        if (loader) loader.style.display = "none";
                        statusText.innerText = "Pobieranie zakończone pomyślnie!";

                        const statSearched = document.getElementById("stat-searched");
                        const statSaved = document.getElementById("stat-saved");

                        if (statSearched) statSearched.innerText = statusData.total || statusData.current;
                        if (statSaved) statSaved.innerText = statusData.current;

                        if (sheetsBtn && statusData.result_url) {
                            sheetsBtn.href = statusData.result_url;
                        }

                        if (summaryBox) summaryBox.classList.remove("hidden");

                    } else if (statusData.status === "failed") {
                        clearInterval(interval);
                        if (loader) loader.style.display = "none";
                        statusText.innerText = `Wystąpił błąd: ${statusData.error || "Błąd podczas scrapowania"}`;
                    }
                } catch (err) {
                    console.error("Błąd statusu:", err);
                }
            }, 1000);

        } catch (error) {
            if (loader) loader.style.display = "none";
            if (statusText) statusText.innerText = "Nie udało się połączyć z serwerem.";
        }
    }
});