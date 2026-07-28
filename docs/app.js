const BACKEND_URL = "https://scraper-backend-lxaw.onrender.com";

async function startScraping(store, category) {
    const statusText = document.getElementById("status-text");
    const spinner = document.getElementById("spinner");
    const resultContainer = document.getElementById("result");

    if (spinner) spinner.style.display = "block";
    if (statusText) statusText.innerText = "Inicjalizacja pobierania...";
    if (resultContainer) resultContainer.innerHTML = "";

    try {
        // 1. Zleć zadanie na backendzie
        const response = await fetch(`${BACKEND_URL}/start_scrape`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ store: store, category: category })
        });
        
        const data = await response.json();
        const taskId = data.task_id;

        // 2. Odpytuj backend co 1 sekundę o postęp
        const interval = setInterval(async () => {
            const statusResponse = await fetch(`${BACKEND_URL}/status/${taskId}`);
            const statusData = await statusResponse.json();

            if (statusData.status === "running") {
                if (statusData.total > 0) {
                    statusText.innerText = `Pobrano ${statusData.current} / ${statusData.total} produktów...`;
                } else {
                    statusText.innerText = `Pobrano ${statusData.current} produktów...`;
                }
            } else if (statusData.status === "completed") {
                clearInterval(interval);
                if (spinner) spinner.style.display = "none";
                statusText.innerText = "Pobieranie zakończone!";
                
                resultContainer.innerHTML = `
                    <p>Gotowe! Oto Twój arkusz:</p>
                    <a href="${statusData.result_url}" target="_blank" style="padding: 10px 20px; background-color: #21a366; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block; margin-top: 10px;">Otwórz Google Sheets</a>
                `;
            } else if (statusData.status === "failed") {
                clearInterval(interval);
                if (spinner) spinner.style.display = "none";
                statusText.innerText = `Błąd: ${statusData.error}`;
            }
        }, 1000);

    } catch (error) {
        if (spinner) spinner.style.display = "none";
        if (statusText) statusText.innerText = "Wystąpił błąd podczas połączenia z serwerem.";
        console.error(error);
    }
}