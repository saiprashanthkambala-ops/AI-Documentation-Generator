/**
 * Global application theme controller.
 * Keeps theme selection independent from generated-document styling.
 */

(() => {
    const STORAGE_KEY = "ai-doc-assistant-theme";

    function getInitialTheme() {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved === "light" || saved === "dark") return saved;
        return "dark";
    }

    function applyTheme(theme) {
        const safeTheme = theme === "light" ? "light" : "dark";
        document.body.dataset.theme = safeTheme;
        document.documentElement.style.colorScheme = safeTheme;
        localStorage.setItem(STORAGE_KEY, safeTheme);
        updateToggle(safeTheme);
    }

    function updateToggle(theme) {
        const button = document.getElementById("themeToggle");
        if (!button) return;
        const next = theme === "dark" ? "light" : "dark";
        button.innerHTML = theme === "dark"
            ? '<i class="bi bi-sun" aria-hidden="true"></i>'
            : '<i class="bi bi-moon-stars" aria-hidden="true"></i>';
        button.title = "Switch to " + next + " theme";
        button.setAttribute("aria-label", "Switch to " + next + " theme");
    }

    function mountControls() {
        const nav = document.querySelector(".navbar .navbar-nav");
        if (!nav || document.getElementById("themeToggle")) return;

        const wrap = document.createElement("div");
        wrap.className = "app-controls d-flex align-items-center gap-2 ms-1";
        wrap.innerHTML =
            '<button id="themeToggle" class="theme-toggle" type="button" aria-label="Switch theme"></button>' +
            '<a class="profile-trigger" href="/profile" title="Profile" aria-label="Open profile">' +
            '<i class="bi bi-person-circle" aria-hidden="true"></i></a>';
        nav.appendChild(wrap);

        document.getElementById("themeToggle").addEventListener("click", () => {
            const current = document.body.dataset.theme || "dark";
            applyTheme(current === "dark" ? "light" : "dark");
        });

        updateToggle(document.body.dataset.theme || "dark");
    }

    function init() {
        applyTheme(getInitialTheme());
        mountControls();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    window.AppTheme = { apply: applyTheme };
})();
