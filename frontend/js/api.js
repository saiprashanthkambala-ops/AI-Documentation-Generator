/**
 * Shared API helpers used by all pages.
 */

const API_BASE = "";
let activeLoadingCancel = null;
let loadingTimer = null;
let loadingProgressPoller = null;
let loadingStartedAt = 0;
let loadingPercent = 0;
let loadingStage = "Preparing your project...";

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

function formatElapsedTime(totalSeconds) {
    const s = Math.max(0, Math.floor(Number(totalSeconds) || 0));
    const mins = Math.floor(s / 60);
    const secs = String(s % 60).padStart(2, "0");
    return String(mins).padStart(2, "0") + ":" + secs;
}

function showLoading(message = "Please wait...", options = {}) {
    hideLoading();
    activeLoadingCancel = typeof options.onCancel === "function" ? options.onCancel : null;
    loadingStartedAt = Date.now();
    loadingPercent = 0;
    loadingStage = "Preparing project...";

    const el = document.createElement("div");
    el.className = "loading-overlay";
    el.id = "loadingOverlay";

    const closeButton = activeLoadingCancel
        ? '<button type="button" class="loading-close" id="loadingCancelBtn" aria-label="Stop current operation" title="Stop">' +
              '<i class="bi bi-x-lg" aria-hidden="true"></i>' +
          '</button>'
        : "";
    const cancelNote = activeLoadingCancel
        ? '<div class="loading-cancel-note">You can stop this operation at any time.</div>'
        : "";
    const safeMessage = String(message).replace(/[&<>"']/g, character => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[character]);

    el.innerHTML =
        '<div class="loading-box loading-dialog">' +
            closeButton +
            '<div class="loading-progress-heading">' +
                '<p class="fw-semibold mb-0" id="loadingMessage">' + safeMessage + '</p>' +
                '<strong id="loadingPercent">0%</strong>' +
            '</div>' +
            '<div class="loading-progress-track" role="progressbar" aria-label="Estimated progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">' +
                '<div class="loading-progress-fill" id="loadingProgressBar" style="width:0%"></div>' +
            '</div>' +
            '<div class="loading-progress-details">' +
                '<span>Current stage: <strong id="loadingStage" class="fw-medium">' + loadingStage + '</strong></span>' +
                '<span>Elapsed time: <strong id="loadingElapsed" class="fw-medium">00:00</strong></span>' +
            '</div>' +
            '<small class="loading-progress-note">Estimated progress while Gemini is drafting. The timer shows actual elapsed time.</small>' +
            cancelNote +
        '</div>';
    document.body.appendChild(el);

    document.getElementById("loadingCancelBtn")?.addEventListener("click", cancelLoading);

    const updateElapsed = () => {
        const seconds = Math.max(0, (Date.now() - loadingStartedAt) / 1000);
        const timer = document.getElementById("loadingElapsed");
        if (timer) timer.textContent = formatElapsedTime(seconds);

        // Smoothly interpolate estimated progress while generation request is in flight
        // without ever claiming completion before the server finishes.
        const estimate = Math.min(88, Math.floor(15 + seconds * 3.5));
        if (loadingPercent < estimate && loadingPercent < 88) {
            updateLoadingProgress(estimate, loadingStage || "Gemini is generating documentation...");
        }
    };
    loadingTimer = window.setInterval(updateElapsed, 500);
    updateElapsed();

    if (options.progressUrl) {
        const pollProgress = async () => {
            try {
                const response = await fetch(API_BASE + options.progressUrl, { cache: "no-store" });
                if (!response.ok) return;
                const progress = await response.json();
                if (progress.status === "running") {
                    updateLoadingProgress(
                        Math.max(loadingPercent, Math.min(92, Number(progress.progress) || 0)),
                        progress.stage || loadingStage
                    );
                    if (typeof progress.elapsed_seconds === "number") {
                        const timer = document.getElementById("loadingElapsed");
                        if (timer) timer.textContent = formatElapsedTime(progress.elapsed_seconds);
                    }
                } else if (progress.status === "completed") {
                    updateLoadingProgress(100, progress.stage || "Generation completed");
                    if (progress.elapsed_seconds) {
                        const timer = document.getElementById("loadingElapsed");
                        if (timer) timer.textContent = formatElapsedTime(progress.elapsed_seconds);
                    }
                    if (loadingTimer) window.clearInterval(loadingTimer);
                    if (loadingProgressPoller) window.clearInterval(loadingProgressPoller);
                } else if (progress.status === "failed" || progress.status === "cancelled") {
                    loadingStage = progress.stage || (progress.status === "cancelled" ? "Cancelled" : "Generation failed");
                    const stage = document.getElementById("loadingStage");
                    if (stage) stage.textContent = loadingStage;
                    if (loadingTimer) window.clearInterval(loadingTimer);
                    if (loadingProgressPoller) window.clearInterval(loadingProgressPoller);
                }
            } catch (_) {
                // Progress polling is supplementary; the main generation request owns errors.
            }
        };
        pollProgress();
        loadingProgressPoller = window.setInterval(pollProgress, 500);
    }
}

function updateLoadingProgress(percent, stage) {
    const bounded = Math.max(0, Math.min(100, Number(percent) || 0));
    loadingPercent = Math.max(loadingPercent, bounded);
    if (stage) loadingStage = String(stage);

    const label = document.getElementById("loadingPercent");
    const bar = document.getElementById("loadingProgressBar");
    const track = bar?.parentElement;
    const stageLabel = document.getElementById("loadingStage");
    if (label) label.textContent = Math.round(loadingPercent) + "%";
    if (bar) bar.style.width = loadingPercent + "%";
    if (track) track.setAttribute("aria-valuenow", String(Math.round(loadingPercent)));
    if (stageLabel) stageLabel.textContent = loadingStage;
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
    if (loadingTimer) window.clearInterval(loadingTimer);
    if (loadingProgressPoller) window.clearInterval(loadingProgressPoller);
    loadingTimer = null;
    loadingProgressPoller = null;
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
