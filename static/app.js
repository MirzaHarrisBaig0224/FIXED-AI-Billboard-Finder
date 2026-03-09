const promptEl = document.getElementById("prompt");
const findBtn = document.getElementById("findBtn");
const loadingOverlay = document.getElementById("loadingOverlay");
const resultsModal = document.getElementById("resultsModal");
const closeModalBtn = document.getElementById("closeModalBtn");
const resultsGrid = document.getElementById("resultsGrid");
const pageShell = document.getElementById("pageShell");
const intentSummary = document.getElementById("intentSummary");

function showLoading() {
    loadingOverlay.classList.remove("hidden");
    pageShell.classList.add("blurred");
    findBtn.disabled = true;
}

function hideLoading() {
    loadingOverlay.classList.add("hidden");
    findBtn.disabled = false;
}

function showModal() {
    resultsModal.classList.remove("hidden");
    pageShell.classList.add("blurred");
}

function hideModal() {
    resultsModal.classList.add("hidden");
    pageShell.classList.remove("blurred");
}

function formatPrice(value) {
    const num = Number(value || 0);
    return `PKR ${num.toLocaleString()}`;
}

function formatViews(value) {
    const num = Number(value || 0);
    return num.toLocaleString();
}

function buildImageSrc(path) {
    if (!path || path.trim() === "") {
        return "https://via.placeholder.com/800x500?text=Billboard";
    }

    if (path.startsWith("http://") || path.startsWith("https://") || path.startsWith("/")) {
        return path;
    }

    return `/${path}`;
}

function renderCards(items) {
    if (!items || !items.length) {
        resultsGrid.innerHTML = `
            <div class="empty-state">
                <h3>No matching billboards found</h3>
                <p>Try a different campaign prompt or check if approved data exists in your database.</p>
            </div>
        `;
        return;
    }

    resultsGrid.innerHTML = items.map(item => `
        <div class="card">
            <img class="card-image" src="${buildImageSrc(item.image_path)}" alt="${item.name}" onerror="this.src='https://via.placeholder.com/800x500?text=Billboard';">

            <div class="card-body">
                ${item.tag ? `<div class="card-tag">★ ${item.tag}</div>` : ""}

                <h3 class="card-title">${item.name || "Untitled Billboard"}</h3>
                <p class="card-location">${item.location || "Location not available"}, ${item.city || ""}</p>

                <div class="stats">
                    <div class="stat">
                        <span class="stat-label">Views / Month</span>
                        <span class="stat-value">${formatViews(item.views)}</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">Rate / Month</span>
                        <span class="stat-value">${formatPrice(item.price)}</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">Size</span>
                        <span class="stat-value">${item.width || 0} × ${item.height || 0}</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">Type</span>
                        <span class="stat-value">${item.type || "N/A"}</span>
                    </div>
                </div>

                <div class="card-footer">
                    <span class="lighting-pill">${item.lighting || "Lighting N/A"}</span>
                    <button class="availability-btn" type="button">View Availability</button>
                </div>
            </div>
        </div>
    `).join("");
}

function buildIntentSummary(intent, count) {
    const pieces = [];

    if (intent.city) pieces.push(`City: ${intent.city}`);
    if (intent.budget_preference && intent.budget_preference !== "neutral") pieces.push(`Budget: ${intent.budget_preference}`);
    if (intent.visibility_priority) pieces.push(`Visibility: ${intent.visibility_priority}`);
    if (intent.size_priority) pieces.push(`Size priority: ${intent.size_priority}`);
    if (intent.lighting_required) pieces.push(`Lighting required`);
    if (intent.premium_preference) pieces.push(`Premium preference`);

    return `${count} billboard${count === 1 ? "" : "s"} matched. ${pieces.join(" • ")}`;
}

async function findBillboards() {
    const prompt = promptEl.value.trim();

    if (!prompt) {
        alert("Please enter a campaign prompt first.");
        return;
    }

    showLoading();

    try {
        const res = await fetch("/recommend", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ prompt })
        });

        const data = await res.json();

        if (!res.ok || !data.success) {
            throw new Error(data.message || "Something went wrong.");
        }

        renderCards(data.billboards);
        intentSummary.textContent = buildIntentSummary(data.intent, data.count);

        hideLoading();
        showModal();
    } catch (error) {
        hideLoading();
        pageShell.classList.remove("blurred");
        alert(error.message || "Failed to fetch recommendations.");
    }
}

findBtn.addEventListener("click", findBillboards);

closeModalBtn.addEventListener("click", hideModal);

resultsModal.addEventListener("click", (e) => {
    if (e.target.classList.contains("modal-backdrop")) {
        hideModal();
    }
});