const BACKEND_URL = "https://scraper-backend-lxaw.onrender.com";

let selectedStore = null;

document.addEventListener("DOMContentLoaded", () => {
    const storeCards = document.querySelectorAll(".store-card");
    const formSection = document.getElementById("form-section");
    const startBtn = document.getElementById("start-btn");
    
    const customDropdown = document.getElementById("custom-dropdown");
    const dropdownSelected = document.getElementById("dropdown-selected");
    const dropdownMenu = document.getElementById("dropdown-menu");
    const categorySelectInput = document.getElementById("category-select");

    const manualCatInput = document.getElementById("manual-cat-id");
    const maxProductsInput = document.getElementById("max-products");

    const statusSection = document.getElementById("status-section");
    const loader = document.getElementById("loader");
    const statusText = document.getElementById("status-text");
    const summaryBox = document.getElementById("summary-box");
    const sheetsBtn = document.getElementById("sheets-btn");

    // Otwieranie / zamykanie głównego menu rozwijanego
    if (dropdownSelected) {
        dropdownSelected.addEventListener("click", (e) => {
            e.stopPropagation();
            dropdownMenu.classList.toggle("hidden");
        });
    }

    // Zamknięcie menu przy kliknięciu poza nim
    document.addEventListener("click", () => {
        if (dropdownMenu) dropdownMenu.classList.add("hidden");
    });

    // Obsługa kliknięć kafelków
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

                dropdownSelected.innerText = `⌛ Pobieranie kategorii z ${storeNameNice}...`;
                dropdownMenu.innerHTML = "";
                categorySelectInput.value = "";

                try {
                    const response = await fetch(`${BACKEND_URL}/categories/${selectedStore}`);
                    const data = await response.json();

                    dropdownSelected.innerText = `-- Wybierz kategorię z listy (${storeNameNice}) --`;

                    if (data.categories && data.categories.length > 0) {
                        // Wspólne grupowanie w drzewko folderów (zarówno dla Sinsay, jak i Lidla)
                        const groups = {};
                        data.categories.forEach(cat => {
                            const parts = cat.name.split(" > ");
                            const mainGroup = parts[0] || "Inne";
                            if (!groups[mainGroup]) groups[mainGroup] = [];
                            groups[mainGroup].push({
                                id: cat.url || cat.id,
                                label: parts.length > 1 ? `↳ ${parts.slice(1).join(" > ")}` : parts[0],
                                full_name: cat.name
                            });
                        });

                        // Generowanie podlist z ptaszkami i folderami
                        Object.keys(groups).forEach(groupName => {
                            const groupDiv = document.createElement("div");
                            groupDiv.className = "tree-group";

                            const headerDiv = document.createElement("div");
                            headerDiv.className = "tree-header";
                            headerDiv.innerHTML = `<span>📁 ${groupName}</span> <span class="tree-arrow">▼</span>`;

                            // Rozwijanie / zwijanie gałęzi
                            headerDiv.addEventListener("click", (e) => {
                                e.stopPropagation();
                                groupDiv.classList.toggle("open");
                            });

                            const subContainer = document.createElement("div");
                            subContainer.className = "tree-subcategories";

                            groups[groupName].forEach(item => {
                                const itemDiv = document.createElement("div");
                                itemDiv.className = "tree-item";
                                
                                // Wyświetlamy ID dla Sinsay, a dla Lidla samą estetyczną nazwę
                                itemDiv.innerText = selectedStore === "sinsay" 
                                    ? `${item.label} (ID: ${item.id})`
                                    : item.label;

                                // Wybór konkretnej podkategorii
                                itemDiv.addEventListener("click", (e) => {
                                    e.stopPropagation();
                                    categorySelectInput.value = item.id;
                                    dropdownSelected.innerText = item.full_name;
                                    dropdownMenu.classList.add("hidden");
                                });

                                subContainer.appendChild(itemDiv);
                            });

                            groupDiv.appendChild(headerDiv);
                            groupDiv.appendChild(subContainer);
                            dropdownMenu.appendChild(groupDiv);
                        });
                    } else {
                        dropdownSelected.innerText = `⚠️ Wpisz ID / URL kategorii ręcznie poniżej`;
                    }
                } catch (err) {
                    console.error("Błąd pobierania kategorii:", err);
                    dropdownSelected.innerText = `⚠️ Wpisz ID / URL kategorii ręcznie poniżej`;
                }
            }
        });
    });

    // Uruchomienie scrapowania
    if (startBtn) {
        startBtn.addEventListener("click", () => {
            const category = manualCatInput.value.trim() || categorySelectInput.value;
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

    // Obsługa statusu i zadań
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