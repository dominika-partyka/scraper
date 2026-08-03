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

    // Klikanie w kafelki sklepów
    storeCards.forEach(card => {
        card.addEventListener("click", async () => {
            storeCards.forEach(c => c.classList.remove("active"));
            card.classList.add("active");

            selectedStore = card.getAttribute("data-shop");

            if (selectedStore === "biedronka") {
                if (formSection) formSection.classList.add("hidden");
                if (statusSection) statusSection.classList.remove("hidden");
                if (loader) loader.style.display = "none";
                if (summaryBox) summaryBox.classList.add("hidden");
                if (statusText) statusText.innerText = `⏳ Obsługa sklepu Biedronka w trakcie przygotowywania...`;
                return;
            }

            if (selectedStore === "sinsay" || selectedStore === "lidl") {
                if (statusSection) statusSection.classList.add("hidden");
                if (formSection) formSection.classList.remove("hidden");

                const storeNameNice = selectedStore === "sinsay" ? "Sinsay" : "Lidl";

                if (categorySelect) {
                    categorySelect.innerHTML = `<option value="">⌛ Pobieranie kategorii z ${storeNameNice}...</option>`;

                    try {
                        const response = await fetch(`${BACKEND_URL}/categories/${selectedStore}`);
                        const data = await response.json();

                        categorySelect.innerHTML = `<option value="">-- Wybierz kategorię z listy (${storeNameNice}) --</option>`;

                        if (data.categories && data.categories.length > 0) {
                            if (selectedStore === "sinsay") {
                                // Grupowanie w 1 liście pod podnagłówkami (np. Kobieta, Mężczyzna)
                                const groups = {};
                                data.categories.forEach(cat => {
                                    const parts = cat.name.split(" > ");
                                    const mainGroup = parts[0] || "Inne";
                                    if (!groups[mainGroup]) groups[mainGroup] = [];
                                    groups[mainGroup].append ? null : null;
                                    groups[mainGroup].push({
                                        id: cat.id,
                                        label: parts.length > 1 ? `↳ ${parts.slice(1).join(" > ")}` : parts[0]
                                    });
                                });

                                Object.keys(groups).forEach(groupName => {
                                    const optgroup = document.createElement("optgroup");
                                    optgroup.label = `📁 ${groupName.toUpperCase()}`;
                                    
                                    groups[groupName].forEach(item => {
                                        const option = document.createElement("option");
                                        option.value = item.id;
                                        option.textContent = `${item.label} (ID: ${item.id})`;
                                        optgroup.appendChild(option);
                                    });
                                    
                                    categorySelect.appendChild(optgroup);
                                });
                            } else {
                                // Standardowa lista dla Lidla
                                data.categories.forEach(cat => {
                                    const option = document.createElement("option");
                                    option.value = cat.url || cat.id;
                                    option.textContent = cat.name;
                                    categorySelect.appendChild(option);
                                });
                            }
                        } else {
                            categorySelect.innerHTML = `<option value="">⚠️ Wpisz ID / URL kategorii ręcznie poniżej</option>`;
                        }
                    } catch (err) {
                        console.error("Błąd pobierania kategorii:", err);
                        categorySelect.innerHTML = `<option value="">⚠️ Wpisz ID / URL kategorii ręcznie poniżej</option>`;
                    }
                }
            }
        });
    });

    // Uruchomienie scrapowania
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

    // Obsługa statusu i wysyłania zadań
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
                        const statDuplicates = document.getElementById("stat-duplicates");
                        const statSaved = document.getElementById("stat-saved");

                        const totalSearched = statusData.total || statusData.current;
                        const totalSaved = statusData.current;
                        const duplicatesCount = statusData.duplicates !== undefined && statusData.duplicates > 0 
                            ? statusData.duplicates 
                            : (totalSearched - totalSaved);

                        if (statSearched) statSearched.innerText = totalSearched;
                        if (statDuplicates) statDuplicates.innerText = duplicatesCount;
                        if (statSaved) statSaved.innerText = totalSaved;

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