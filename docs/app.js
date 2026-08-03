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
                    const groups = {};
                    
                    data.categories.forEach(cat => {
                        const parts = cat.name.split(" > ");
                        const mainGroup = parts[0] || "Inne";
                        if (!groups[mainGroup]) groups[mainGroup] = [];
                        
                        groups[mainGroup].push({
                            id: cat.id,
                            url: cat.url || cat.id,
                            label: parts.length > 1 ? `↳ ${parts.slice(1).join(" > ")}` : parts[0],
                            full_name: cat.name
                        });
                    });

                    Object.keys(groups).forEach(groupName => {
                        const groupDiv = document.createElement("div");
                        groupDiv.className = "tree-group";

                        const headerDiv = document.createElement("div");
                        headerDiv.className = "tree-header";
                        headerDiv.innerHTML = `<span>📁 ${groupName}</span> <span class="tree-arrow">▼</span>`;

                        headerDiv.addEventListener("click", (e) => {
                            e.stopPropagation();
                            groupDiv.classList.toggle("open");
                        });

                        const subContainer = document.createElement("div");
                        subContainer.className = "tree-subcategories";

                        groups[groupName].forEach(item => {
                            const itemDiv = document.createElement("div");
                            itemDiv.className = "tree-item";
                            
                        // Dla Sinsay dajemy Nazwę + mniejszy, wyszarzony ID w nawiasie
                            if (selectedStore === "sinsay") {
                                itemDiv.innerHTML = `${item.label} <span class="cat-id">(ID: ${item.id})</span>`;
                            } else {
                                itemDiv.innerText = item.label;
                            }

                            itemDiv.addEventListener("click", (e) => {
                                e.stopPropagation();
                                // Zapisujemy URL lub ID do wysłania do backendu
                                categorySelectInput.value = item.url || item.id;
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