/**
 * Shared API helpers used by all pages.
 */

const API_BASE = "";
let activeLoadingCancel = null;

async function parseJsonResponse(response) {
    const text = await response.text();
    if (!text) return null;
    try {
        return JSON.parse(text);
    } catch (e) {
        throw new Error(
            text.startsWith("<") ? "Server error — try restarting the app" : text.slice(0, 200)
        );
    }
}

async function apiRequest(url, options = {}) {
    const response = await fetch(`${API_BASE}${url}`, options);
    const ct = response.headers.get("content-type") || "";

    if (!response.ok) {
        let msg = `Request failed (${response.status})`;
        if (ct.includes("application/json")) {
            try {
                const err = JSON.parse(await response.text());
                const detail = err.detail;
                if (detail && typeof detail === "object") {
                    const code = detail.code ? String(detail.code) + ": " : "";
                    msg = code + (detail.message || "Request failed");
                } else if (detail) {
                    msg = String(detail);
                }
            } catch (e) { /* not json */ }
        }
        throw new Error(msg);
    }

    if (ct.includes("text/markdown") || ct.includes("text/plain")) return response;
    return parseJsonResponse(response);
}

function showLoading(message = "Please wait...", options = {}) {
    hideLoading();
    activeLoadingCancel = typeof options.onCancel === "function" ? options.onCancel : null;

    const el = document.createElement("div");
    el.className = "loading-overlay";
    el.id = "loadingOverlay";
    el.innerHTML =
        '<div class="loading-box loading-dialog">' +
            '<button type="button" class="loading-close" id="loadingCancelBtn" aria-label="Stop current operation" title="Stop">' +
                '<i class="bi bi-x-lg" aria-hidden="true"></i>' +
            '</button>' +
            '<div class="spinner-border text-primary mb-3"></div>' +
            '<p class="fw-semibold mb-1">' + message + '</p>' +
            '<small class="text-muted">Gemini may take a moment to respond</small>' +
            '<div class="loading-cancel-note">You can stop this operation at any time.</div>' +
        '</div>';
    document.body.appendChild(el);

    document.getElementById("loadingCancelBtn")?.addEventListener("click", cancelLoading);
}

function cancelLoading() {
    const cancel = activeLoadingCancel;
    activeLoadingCancel = null;
    if (typeof cancel === "function") {
        try { cancel(); } catch (_) {}
    }
    hideLoading();
}

function hideLoading() {
    activeLoadingCancel = null;
    document.getElementById("loadingOverlay")?.remove();
}

function showToast(message, type = "success") {
    let c = document.querySelector(".toast-container");
    if (!c) {
        c = document.createElement("div");
        c.className = "toast-container";
        document.body.appendChild(c);
    }
    const bg = type === "error" ? "bg-danger" : "bg-success";
    const t = document.createElement("div");
    t.className = `toast align-items-center text-white ${bg} border-0 show`;
    t.innerHTML = `<div class="d-flex"><div class="toast-body">${message}</div>
        <button class="btn-close btn-close-white me-2 m-auto" onclick="this.closest('.toast').remove()"></button></div>`;
    c.appendChild(t);
    setTimeout(() => t.remove(), 4000);
}

function formatDate(d) {
    return new Date(d).toLocaleDateString("en-US", {
        year: "numeric", month: "short", day: "numeric",
        hour: "2-digit", minute: "2-digit",
    });
}

function getQueryParam(name) {
    return new URLSearchParams(window.location.search).get(name);
}

async function checkGeminiStatus() {
    const el = document.getElementById("geminiStatus");
    if (!el) return;
    try {
        const s = await apiRequest("/api/gemini/status");
        el.innerHTML = `<span class="status-dot ${s.configured ? 'online' : 'offline'}"></span>
            <small>${s.configured ? 'Gemini Ready' : 'Gemini Offline'}</small>`;
        el.title = s.message;
    } catch (e) {
        el.innerHTML = '<span class="status-dot offline"></span><small>Gemini Offline</small>';
    }
}

function setActiveNav(page) {
    document.querySelectorAll(".nav-link").forEach(link => {
        link.classList.toggle("active", link.dataset.page === page);
    });
}
