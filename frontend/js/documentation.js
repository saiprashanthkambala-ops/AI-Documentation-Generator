/**
 * Documentation page — enhanced viewer with TOC, stats, copy.
 */

let currentProjectId = null;
let currentMarkdown = "";

document.addEventListener("DOMContentLoaded", () => {
    checkGeminiStatus();
    currentProjectId = getQueryParam("id");
    if (currentProjectId) loadDocumentation(currentProjectId);

    document.getElementById("downloadPdfBtn")?.addEventListener("click", () => downloadDoc("pdf", "downloadPdfBtn"));
    document.getElementById("downloadJpgBtn")?.addEventListener("click", () => downloadDoc("jpg", "downloadJpgBtn"));
    document.getElementById("regenerateBtn")?.addEventListener("click", regenerateDoc);
    document.getElementById("copyBtn")?.addEventListener("click", copyDoc);
});

async function loadDocumentation(projectId) {
    try {
        const project = await apiRequest(`/api/projects/${projectId}`);
        currentProjectId = projectId;

        document.getElementById("docTitle").textContent = project.name;
        document.getElementById("docMeta").textContent =
            `Uploaded ${formatDate(project.upload_date)} · ${project.file_count} source files · ${project.status}`;

        if (!project.generated_documentation) {
            document.getElementById("noDoc").innerHTML = `
                <i class="bi bi-hourglass-split" style="font-size:3rem;opacity:0.4;"></i>
                <h4 class="mt-3">Documentation not generated yet</h4>
                <p>Project "<strong>${project.name}</strong>" is ready. Generation takes about 1–4 minutes.</p>
                <button class="btn btn-primary btn-lg" onclick="generateNow(${projectId})">
                    <i class="bi bi-stars"></i> Generate Full Documentation
                </button>`;
            return;
        }

        renderDocumentation(project.generated_documentation, project.file_count);
        document.getElementById("docActions").style.display = "flex";

    } catch (err) {
        showToast(err.message, "error");
    }
}

function renderDocumentation(markdown, fileCount) {
    currentMarkdown = markdown;

    document.getElementById("noDoc").classList.add("d-none");
    document.getElementById("docView").classList.remove("d-none");

    // Stats
    const words = countWords(markdown);
    const sections = (markdown.match(/^## /gm) || []).length;
    document.getElementById("statWords").textContent = words.toLocaleString();
    document.getElementById("statSections").textContent = sections;
    document.getElementById("statFiles").textContent = fileCount || "—";
    document.getElementById("statReadTime").textContent = Math.max(1, Math.ceil(words / 200));

    // Render content
    document.getElementById("docContent").innerHTML = markdownToHtml(markdown);

    // Build TOC sidebar
    const headings = buildDocSidebar(markdown);
    const tocNav = document.getElementById("tocNav");
    tocNav.innerHTML = headings.map(h =>
        `<a href="#${h.id}" onclick="scrollToHeading('${h.id}'); return false;">${h.title}</a>`
    ).join("");

    // Add IDs to h2 elements for scrolling
    document.querySelectorAll("#docContent h2").forEach((h2, i) => {
        if (headings[i]) h2.id = headings[i].id;
    });
}

function scrollToHeading(id) {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function generateNow(projectId) {
    showAgentLoading();
    try {
        const result = await apiRequest(`/api/projects/${projectId}/generate`, { method: "POST" });
        showToast(result.message || "Documentation generated!");
        loadDocumentation(projectId);
    } catch (err) {
        showToast(err.message, "error");
    } finally {
        hideAgentLoading();
    }
}

async function downloadDoc(format, buttonId) {
    if (!currentProjectId) return;

    const button = document.getElementById(buttonId);
    const originalHtml = button?.innerHTML;
    if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span> Exporting...';
    }

    try {
        const res = await fetch(`/api/projects/${currentProjectId}/download/${format}`);
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
        a.download = match ? match[1] : `documentation.${format}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        showToast(`Download ${format.toUpperCase()} started`);
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
    navigator.clipboard.writeText(currentMarkdown).then(() => {
        showToast("Copied to clipboard!");
    }).catch(() => showToast("Copy failed", "error"));
}

async function regenerateDoc() {
    if (!currentProjectId) return;
    if (!confirm("Regenerate documentation? Takes about 1-4 minutes.")) return;
    await generateNow(currentProjectId);
}
