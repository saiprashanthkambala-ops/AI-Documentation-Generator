/**
 * Documentation workspace — persistent chat, revision history, undo/redo, and export.
 */

let currentProjectId = null;
let currentMarkdown = "";
let workspaceState = null;
let revisionModal = null;

document.addEventListener("DOMContentLoaded", () => {
    checkGeminiStatus();
    currentProjectId = getQueryParam("id");
    revisionModal = new bootstrap.Modal(document.getElementById("revisionPreviewModal"));

    document.getElementById("undoBtn")?.addEventListener("click", undoChange);
    document.getElementById("redoBtn")?.addEventListener("click", redoChange);
    document.getElementById("downloadPdfBtn")?.addEventListener("click", () => downloadDoc("pdf", "downloadPdfBtn"));
    document.getElementById("downloadJpgBtn")?.addEventListener("click", () => downloadDoc("jpg", "downloadJpgBtn"));
    document.getElementById("regenerateBtn")?.addEventListener("click", regenerateDoc);
    document.getElementById("copyBtn")?.addEventListener("click", copyDoc);
    document.getElementById("sendChatBtn")?.addEventListener("click", sendChat);

    document.getElementById("chatInput")?.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            sendChat();
        }
    });

    if (currentProjectId) loadDocumentation(currentProjectId);
});

async function loadDocumentation(projectId) {
    try {
        const project = await apiRequest("/api/projects/" + projectId);
        currentProjectId = projectId;
        document.getElementById("docTitle").textContent = project.name;
        document.getElementById("docMeta").textContent = "Uploaded " + formatDate(project.upload_date) + " · " + project.file_count + " source files · " + project.status;

        if (!project.generated_documentation) {
            document.getElementById("noDoc").innerHTML =
                '<i class="bi bi-hourglass-split" style="font-size:3rem;opacity:0.4;"></i>' +
                '<h4 class="mt-3">Documentation not generated yet</h4>' +
                '<p>Project "<strong>' + escapeHtml(project.name) + '</strong>" is ready.</p>' +
                '<button class="btn btn-primary btn-lg" onclick="generateNow(' + projectId + ')">' +
                '<i class="bi bi-stars"></i> Generate Full Documentation</button>';
            return;
        }

        await loadWorkspace();
    } catch (err) {
        showToast(err.message, "error");
    }
}

async function loadWorkspace() {
    const workspace = await apiRequest("/api/projects/" + currentProjectId + "/workspace");
    workspaceState = workspace;
    currentMarkdown = workspace.current_documentation;

    document.getElementById("noDoc").classList.add("d-none");
    document.getElementById("docView").classList.remove("d-none");
    document.getElementById("docActions").style.display = "flex";

    renderDocumentation(currentMarkdown);
    renderRevisionHistory(workspace.revisions);
    renderChatMessages(workspace.messages);
    updateRevisionButtons(workspace);
}

function renderDocumentation(markdown) {
    const words = countWords(markdown);
    const sections = (markdown.match(/^## /gm) || []).length;
    document.getElementById("statWords").textContent = words.toLocaleString();
    document.getElementById("statSections").textContent = sections;
    document.getElementById("statFiles").textContent = getFileCountFromMeta();
    document.getElementById("statReadTime").textContent = Math.max(1, Math.ceil(words / 200));

    document.getElementById("docContent").innerHTML = markdownToHtml(markdown);
    const headings = buildDocSidebar(markdown);
    document.getElementById("tocNav").innerHTML = headings.map(h =>
        '<a href="#' + h.id + '" onclick="scrollToHeading(' + JSON.stringify(h.id) + '); return false;">' +
        escapeHtml(h.title) + "</a>"
    ).join("");

    document.querySelectorAll("#docContent h2").forEach((h2, i) => {
        if (headings[i]) h2.id = headings[i].id;
    });
}

function getFileCountFromMeta() {
    const meta = document.getElementById("docMeta").textContent;
    const match = meta.match(/(\d+)\s+source files/);
    return match ? match[1] : "—";
}

function scrollToHeading(id) {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderRevisionHistory(revisions) {
    document.getElementById("revisionCount").textContent = revisions.length;
    document.getElementById("currentRevisionLabel").textContent =
        workspaceState?.current_revision_id ? "V" + getCurrentVersionNumber(workspaceState.revisions) : "V1";

    const list = document.getElementById("revisionList");
    if (!revisions.length) {
        list.innerHTML = '<div class="text-muted small py-2">No revisions yet.</div>';
        return;
    }

    list.innerHTML = revisions.map(revision => {
        const active = revision.current ? " active" : "";
        const restore = revision.current
            ? ""
            : '<button class="btn btn-sm btn-outline-secondary revision-restore" onclick="restoreRevision(' + revision.id + ')">Restore</button>';
        return '<div class="revision-item' + active + '">' +
            '<div class="revision-main">' +
            '<div class="fw-semibold">V' + revision.version_number + " · " + escapeHtml(revision.operation) + "</div>" +
            '<div class="small text-muted">' + escapeHtml(revision.summary || "Documentation revision") + "</div>" +
            '<div class="small text-muted mt-1">' + formatDate(revision.created_at) + "</div>" +
            "</div>" + restore + "</div>";
    }).join("");
}

function renderChatMessages(messages) {
    const container = document.getElementById("chatMessages");
    const items = messages.length ? messages : [{
        role: "assistant",
        content: "Hi! I can help you edit this documentation. Ask me to remove, add, replace, shorten, expand, or reorganize content. I will propose the change first, and you decide whether to apply it."
    }];
    container.innerHTML = items.map(renderChatMessage).join("");
    container.scrollTop = container.scrollHeight;
}

function renderChatMessage(message) {
    const role = message.role === "user" ? "user" : "assistant";
    let proposalHtml = "";

    if (role === "assistant" && message.proposal && message.proposal.operation !== "NO_CHANGE") {
        const applied = message.proposal.status === "APPLIED";
        proposalHtml =
            '<div class="chat-proposal">' +
            '<div class="small fw-semibold text-uppercase mb-1">' +
            escapeHtml(message.proposal.operation.replaceAll("_", " ")) +
            (applied ? " · Applied" : " · Ready to review") + "</div>" +
            '<div class="small text-muted mb-2">' + escapeHtml(message.proposal.summary || "Proposed documentation change") + "</div>" +
            (applied
                ? '<span class="badge text-bg-success">Applied in revision V' + escapeHtml(String(message.proposal.applied_revision_version || message.proposal.applied_revision_id)) + "</span>"
                : '<div class="d-flex gap-2 flex-wrap">' +
                  '<button class="btn btn-sm btn-outline-primary" onclick="previewProposal(' + message.id + ')"><i class="bi bi-eye"></i> View Change</button>' +
                  '<button class="btn btn-sm btn-primary" onclick="applyProposal(' + message.id + ')"><i class="bi bi-check2"></i> Apply Change</button>' +
                  "</div>") +
            "</div>";
    }

    return '<div class="chat-message ' + role + '">' +
        '<div class="chat-role">' + (role === "user" ? "You" : "Assistant") + "</div>" +
        '<div class="chat-bubble">' + escapeHtml(message.content || "") + "</div>" +
        proposalHtml +
        (message.created_at ? '<div class="chat-time">' + formatDate(message.created_at) + "</div>" : "") +
        "</div>";
}

async function sendChat() {
    const input = document.getElementById("chatInput");
    const button = document.getElementById("sendChatBtn");
    const message = input.value.trim();
    if (!message || !currentProjectId) return;
    input.value = "";
    button.disabled = true;
    const previous = button.innerHTML;
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Thinking...';

    try {
        await apiRequest("/api/projects/" + currentProjectId + "/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message })
        });
        await loadWorkspace();
    } catch (err) {
        input.value = message;
        showToast(err.message, "error");
    } finally {
        button.disabled = false;
        button.innerHTML = previous;
    }
}

function findChatMessage(messageId) {
    return (workspaceState?.messages || []).find(message => message.id === messageId);
}

function getCurrentVersionNumber(revisions) {
    const current = (revisions || []).find(revision => revision.current);
    return current?.version_number || 1;
}

function previewProposal(messageId) {
    const message = findChatMessage(messageId);
    if (!message?.proposal) return;
    const proposal = message.proposal;
    let html = '<div class="mb-3"><strong>Operation:</strong> ' + escapeHtml(proposal.operation.replaceAll("_", " ")) + "</div>" +
        '<div class="mb-3"><strong>Summary:</strong> ' + escapeHtml(proposal.summary || "") + "</div>";
    if (proposal.target) {
        html += '<div class="diff-label">Current text</div><pre class="diff-minus">' + escapeHtml(proposal.target) + "</pre>";
    }
    if (proposal.replacement) {
        html += '<div class="diff-label">Proposed text</div><pre class="diff-plus">' + escapeHtml(proposal.replacement) + "</pre>";
    } else if (proposal.operation === "REMOVE_TEXT" || proposal.operation === "REMOVE_SECTION") {
        html += '<div class="diff-label">Result</div><pre class="diff-plus">The selected content will be removed.</pre>';
    }
    document.getElementById("revisionPreviewBody").innerHTML = html;
    revisionModal.show();
}

async function applyProposal(messageId) {
    if (!confirm("Apply this documentation change? A new revision will be created, and the previous revision will remain available for Undo.")) return;
    try {
        await apiRequest("/api/projects/" + currentProjectId + "/chat/apply", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message_id: messageId })
        });
        showToast("Change applied successfully.");
        await loadWorkspace();
    } catch (err) {
        showToast(err.message, "error");
    }
}

async function undoChange() {
    try {
        const response = await apiRequest("/api/projects/" + currentProjectId + "/chat/undo", { method: "POST" });
        showToast(response.message);
        await loadWorkspace();
    } catch (err) {
        showToast(err.message, "error");
    }
}

async function redoChange() {
    try {
        const response = await apiRequest("/api/projects/" + currentProjectId + "/chat/redo", { method: "POST" });
        showToast(response.message);
        await loadWorkspace();
    } catch (err) {
        showToast(err.message, "error");
    }
}

async function restoreRevision(revisionId) {
    const selected = (workspaceState?.revisions || []).find(item => item.id === revisionId);
    const versionLabel = selected?.version_number || revisionId;
    if (!confirm("Restore revision V" + versionLabel + "? The current revision will remain in history.")) return;
    try {
        const response = await apiRequest("/api/projects/" + currentProjectId + "/chat/restore/" + revisionId, { method: "POST" });
        showToast(response.message);
        await loadWorkspace();
    } catch (err) {
        showToast(err.message, "error");
    }
}

function updateRevisionButtons(workspace) {
    document.getElementById("undoBtn").disabled = !workspace.can_undo;
    document.getElementById("redoBtn").disabled = !workspace.can_redo;
}

async function generateNow(projectId) {
    showLoading("Generating documentation with Gemini...");
    try {
        const result = await apiRequest("/api/projects/" + projectId + "/generate", { method: "POST" });
        showToast(result.message || "Documentation generated!");
        await loadDocumentation(projectId);
    } catch (err) {
        showToast(err.message, "error");
    } finally {
        hideLoading();
    }
}

async function downloadDoc(format, buttonId) {
    if (!currentProjectId) return;
    const button = document.getElementById(buttonId);
    const originalHtml = button?.innerHTML;
    if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Exporting...';
    }
    try {
        const res = await fetch("/api/projects/" + currentProjectId + "/download/" + format);
        if (!res.ok) {
            let message = "Export failed";
            try {
                const payload = await res.json();
                message = payload.detail || message;
            } catch (_) {}
            throw new Error(message);
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        const disp = res.headers.get("Content-Disposition") || "";
        const match = disp.match(/filename="([^"]+)"/i);
        a.download = match ? match[1] : "documentation." + format;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        showToast("Download " + format.toUpperCase() + " started");
    } catch (err) {
        showToast(err.message, "error");
    } finally {
        if (button) {
            button.disabled = false;
            button.innerHTML = originalHtml;
        }
    }
}

function copyDoc() {
    if (!currentMarkdown) return;
    navigator.clipboard.writeText(currentMarkdown).then(() => showToast("Copied to clipboard!"))
        .catch(() => showToast("Copy failed", "error"));
}

async function regenerateDoc() {
    if (!currentProjectId) return;
    if (!confirm("Regenerate documentation? The new document will become a new revision, and previous revisions will remain available.")) return;
    await generateNow(currentProjectId);
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll("\"", "&quot;")
        .replaceAll("'", "&#039;");
}