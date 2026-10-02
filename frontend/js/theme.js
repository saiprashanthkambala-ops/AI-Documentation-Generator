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
        button.textContent = theme === "dark" ? "☼" : "☾";
        button.title = "Switch to " + next + " theme";
        button.setAttribute("aria-label", "Switch to " + next + " theme");
    }

    function mountToggle() {
        const nav = document.querySelector(".navbar .navbar-nav");
        if (!nav || document.getElementById("themeToggle")) return;

        const wrap = document.createElement("div");
        wrap.className = "d-flex align-items-center ms-1";
        wrap.innerHTML = '<button id="themeToggle" class="theme-toggle" type="button" aria-label="Switch theme"></button>';
        nav.appendChild(wrap);

        document.getElementById("themeToggle").addEventListener("click", () => {
            const current = document.body.dataset.theme || "dark";
            applyTheme(current === "dark" ? "light" : "dark");
        });

        updateToggle(document.body.dataset.theme || "dark");
    }

    function init() {
        applyTheme(getInitialTheme());
        mountToggle();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    window.AppTheme = { apply: applyTheme };
})();
