/**
 * History page — list all uploaded projects.
 */

document.addEventListener("DOMContentLoaded", () => {
    checkGeminiStatus();
    loadHistory();
});

async function loadHistory() {
    const tbody = document.getElementById("historyBody");
    const empty = document.getElementById("emptyHistory");

    try {
        const projects = await apiRequest("/api/projects");

        if (projects.length === 0) {
            document.getElementById("historyTable").classList.add("d-none");
            empty.classList.remove("d-none");
            return;
        }

        tbody.innerHTML = projects.map(p => {
            const statusBadge = p.status === "completed"
                ? '<span class="badge bg-success">Completed</span>'
                : p.status === "failed"
                ? '<span class="badge bg-danger">Failed</span>'
                : '<span class="badge bg-warning text-dark">Uploaded</span>';

            return `<tr class="history-row">
                <td class="fw-semibold">${esc(p.name)}</td>
                <td>${formatDate(p.upload_date)}</td>
                <td>${p.file_count}</td>
                <td>${statusBadge}</td>
                <td>
                    ${p.has_documentation
                        ? `<a href="/documentation?id=${p.id}" class="btn btn-sm btn-primary me-1"><i class="bi bi-eye"></i> View</a>`
                        : `<button class="btn btn-sm btn-outline-primary me-1" onclick="generateDoc(${p.id})"><i class="bi bi-stars"></i> Generate</button>`
                    }
                    <button class="btn btn-sm btn-outline-danger" onclick="deleteProject(${p.id}, '${esc(p.name)}')">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            </tr>`;
        }).join("");
        const history = document.getElementById('docHistory');
        const all = (await Promise.all(projects.map(async p => (await apiRequest(`/api/projects/${p.id}/documentation-versions`)).map(d => ({...d, project:p})) ))).flat();
        history.innerHTML = all.length ? all.map(d => `<div class="col-md-6"><div class="border rounded p-2"><strong>${esc(d.project.name)}</strong> · ${esc(d.doc_type)}<br><small>${formatDate(d.created_at)} · ${esc(d.status)} · Project version ${d.project_version_id || 'unknown'}</small><br><a class="btn btn-sm btn-outline-primary mt-1" href="/documentation?id=${d.project.id}">Open project</a></div></div>`).join('') : '<p class="text-muted">No documentation versions yet.</p>';

    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-danger">${err.message}</td></tr>`;
    }
}

async function generateDoc(id) {
    const controller = new AbortController();
    showLoading("Generating documentation with Gemini...", {
        onCancel: () => controller.abort()
    });
    try {
        const result = await apiRequest(`/api/projects/${id}/generate`, {
            method: "POST",
            signal: controller.signal
        });
        showToast(result.message || "Done!");
        window.location.href = `/documentation?id=${id}`;
    } catch (err) {
        if (err?.name === "AbortError") {
            showToast("Documentation generation stopped.", "error");
        } else {
            showToast(err.message, "error");
        }
    } finally {
        hideLoading();
    }
}

async function deleteProject(id, name) {
    if (!confirm(`Delete project "${name}"?`)) return;
    try {
        await apiRequest(`/api/projects/${id}`, { method: "DELETE" });
        showToast("Project deleted");
        loadHistory();
    } catch (err) {
        showToast(err.message, "error");
    }
}

function esc(text) {
    const d = document.createElement("div");
    d.textContent = text;
    return d.innerHTML;
}
