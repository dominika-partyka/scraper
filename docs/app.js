// Podmień poniższy URL na adres ze swojego Rendera po wdrożeniu!
const API_URL = "https://TWÓJ-SERWER-ON-RENDER.onrender.com"; 

let selectedShop = null;

document.querySelectorAll('.store-card').forEach(card => {
    card.addEventListener('click', () => {
        document.querySelectorAll('.store-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');
        
        selectedShop = card.dataset.shop;
        loadCategories(selectedShop);
    });
});

async function loadCategories(shop) {
    const formSec = document.getElementById('form-section');
    const select = document.getElementById('category-select');
    
    formSec.classList.remove('hidden');
    select.innerHTML = '<option value="">-- Pobieranie kategorii... --</option>';

    try {
        const res = await fetch(`${API_URL}/api/categories?shop=${shop}`);
        const data = await res.json();

        select.innerHTML = '<option value="">-- Wybierz kategorię --</option>';
        data.categories.forEach(cat => {
            const opt = document.createElement('option');
            opt.value = cat.id;
            opt.textContent = cat.name;
            select.appendChild(opt);
        });
    } catch (err) {
        select.innerHTML = '<option value="">Błąd pobierania kategorii</option>';
    }
}

document.getElementById('start-btn').addEventListener('click', async () => {
    const catSelect = document.getElementById('category-select').value;
    const manualCat = document.getElementById('manual-cat-id').value.trim();
    const maxProds = document.getElementById('max-products').value;

    const finalCatId = manualCat || catSelect;

    if (!finalCatId) {
        alert("Wybierz kategorię z listy lub wpisz jej ID!");
        return;
    }

    document.getElementById('form-section').classList.add('hidden');
    document.getElementById('status-section').classList.remove('hidden');
    document.getElementById('summary-box').classList.add('hidden');
    document.getElementById('loader').classList.remove('hidden');
    document.getElementById('status-text').textContent = "Pobieranie produktów i zapis do Google Sheets...";

    try {
        const res = await fetch(`${API_URL}/api/scrape`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                shop: selectedShop,
                category_id: finalCatId,
                max_products: maxProds ? parseInt(maxProds) : null
            })
        });

        const data = await res.json();

        if (res.ok && data.success) {
            document.getElementById('loader').classList.add('hidden');
            document.getElementById('status-text').textContent = "✅ Proces zakończony sukcesem!";
            
            document.getElementById('stat-searched').textContent = data.stats.searched;
            document.getElementById('stat-duplicates').textContent = data.stats.duplicates;
            document.getElementById('stat-saved').textContent = data.stats.saved;
            
            document.getElementById('summary-box').classList.remove('hidden');
        } else {
            throw new Error(data.detail || "Coś poszło nie tak.");
        }
    } catch (err) {
        document.getElementById('loader').classList.add('hidden');
        document.getElementById('status-text').textContent = `❌ Błąd: ${err.message}`;
    }
});