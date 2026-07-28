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

    // 1. Obsługa kliknięcia w kafelki sklepów
    storeCards.forEach(card => {
        card.addEventListener("click", async () => {
            // Zaznacz aktywny kafelek
            storeCards.forEach(c => c.classList.remove("active"));
            card.classList.add("active");

            selectedStore = card.getAttribute("data-shop");
            
            // Pokaż sekcję formularza
            if (formSection) formSection.classList.remove("hidden");

            // Jeśli to Sinsay, wstawmy przykładowe kategorie (lub domyślne opcje)
            if (categorySelect) {
                categorySelect.innerHTML = `
                    <option value="">-- Wybierz kategorię z listy --</option>
                    <option value="1769">Kobieta / Odzież / Sukienki (ID: 1769)</option>
                    <option value="1770">Kobieta / Odzież / Koszulki (ID: 1770)</option>
                    <option value="1771">Mężczyzna / Odzież (ID: 1771)</option>
                `;
            }
        });
    });

    // 2. Obsługa kliknięcia przycisku "Uruchom Scrapowanie"
    if (startBtn) {
        startBtn.addEventListener("click", () => {
            const category = manualCatInput.value.trim() || categorySelect.value;
            const maxProducts = maxProductsInput ? maxProductsInput.value : null;

            if (!selectedStore) {
                alert("Wybierz najpierw sklep klikając na kafelek!");
                return;
            }

            if (!category) {
                alert("Wybierz kategorię z listy lub wpisz jej ID ręcznie!");
                return;
            }

            // Rozpocznij proces
            runScraper(selectedStore, category, maxProducts);
        });
    }

    // 3. Główna funkcja uruchamiająca i sprawdzająca status
    async function runScraper(store, category, maxProducts) {
        // Pokaż sekcję statusu i ukryj stare podsumowanie
        if (statusSection) statusSection.classList.remove("hidden");
        if (loader) loader.style.display = "block";
        if (summaryBox) summaryBox.classList.add("hidden");
        if (statusText) statusText.innerText = "Inicjalizacja scrapera...";

        try {
            // Wysłanie żądania startowego do backendu
            const response = await fetch(`${BACKEND_URL}/start_scrape`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    store: store,
                    category: category,
                    max_products: maxProducts
                })
            });

            if (!response.ok) {
                throw new Error(`Serwer zwrócił błąd: ${response.status}`);
            }

            const data = await response.json();
            const taskId = data.task_id;

            // Odpytywanie o postęp co 1 sekundę
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

                        // Wypełnij statystyki
                        const statSearched = document.getElementById("stat-searched");
                        const statSaved = document.getElementById("stat-saved");
                        
                        if (statSearched) statSearched.innerText = statusData.total || statusData.current;
                        if (statSaved) statSaved.innerText = statusData.current;

                        // Ustaw bezpośredni link do arkusza Google Sheets
                        if (sheetsBtn && statusData.result_url) {
                            sheetsBtn.href = statusData.result_url;
                        }

                        // Pokaż podsumowanie
                        if (summaryBox) summaryBox.classList.remove("hidden");

                    } else if (statusData.status === "failed") {
                        clearInterval(interval);
                        if (loader) loader.style.display = "none";
                        statusText.innerText = `Wystąpił błąd: ${statusData.error || "Nieznany błąd"}`;
                    }
                } catch (err) {
                    console.error("Błąd podczas odpytywania o status:", err);
                }
            }, 1000);

        } catch (error) {
            if (loader) loader.style.display = "none";
            if (statusText) statusText.innerText = "Nie udało się połączyć z serwerem.";
            console.error(error);
        }
    }
});