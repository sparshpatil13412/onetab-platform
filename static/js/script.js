// ---------------------------
// DROPDOWN MENU
// ---------------------------
function toggleDropdown() {
    const menu = document.getElementById("dropdownMenu");
    menu.classList.toggle("hidden");
}

// Close dropdown if clicked outside
window.addEventListener('click', function(e) {
    const button = document.getElementById("dropdownButton");
    const menu = document.getElementById("dropdownMenu");
    if (!button.contains(e.target) && !menu.contains(e.target)) {
        menu.classList.add("hidden");
    }
});

// ---------------------------
// DELETE CONFIRMATION
// ---------------------------
function confirmDelete(id) {
    if (confirm("Delete this link?")) {
        window.location.href = "/delete/" + id;
    }
}

// ---------------------------
// COPY LINK
// ---------------------------
function copyLink(url) {
    navigator.clipboard.writeText(url)
        .then(() => showToast("Copied!"))
        .catch(() => showToast("Failed to copy"));
}

// ---------------------------
// TOAST NOTIFICATIONS
// ---------------------------
function showToast(message) {
    const toast = document.createElement("div");
    toast.className = "toast"; // styled in style.css
    toast.innerText = message;

    document.body.appendChild(toast);

    // Remove after 2 seconds
    setTimeout(() => {
        toast.remove();
    }, 2000);
}

// ---------------------------
// DASHBOARD SEARCH FILTER
// ---------------------------
function filterLinks() {
    const query = document.getElementById("search").value.toLowerCase();
    const cards = document.querySelectorAll(".card");

    cards.forEach(card => {
        const text = card.innerText.toLowerCase();
        card.style.display = text.includes(query) ? "block" : "none";
    });
}

// ---------------------------
// AUTOFOCUS FIRST INPUT
// ---------------------------
window.addEventListener('load', () => {
    const input = document.querySelector("input");
    if (input) input.focus();
});

// ---------------------------
// OPTIONAL: Enter key triggers search
// ---------------------------
const searchInput = document.getElementById("search");
if (searchInput) {
    searchInput.addEventListener("keyup", (e) => {
        if (e.key === "Enter") {
            filterLinks();
        }
    });
}