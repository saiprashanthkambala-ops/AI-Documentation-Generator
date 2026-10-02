/**
 * Upload page — ZIP upload, extract, and trigger AI generation.
 */

let uploadedProjectId = null;
let selectedZipFile = null;

document.addEventListener("DOMContentLoaded", () => {
    checkGeminiStatus();
    setupUploadZone();
    document.getElementById("uploadForm").addEventListener("submit", handleUpload);
    document.getElementById("generateBtn").addEventListener("click", handleGenerate);
});

function setupUploadZone() {
    const zone = document.getElementById("uploadZone");
    const input = document.getElementById("zipInput");

    zone.addEventListener("click", () => input.click());
    input.addEventListener("change", () => {
        if (input.files.length > 0) selectFile(input.files[0]);
    });

    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("dragover"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
    zone.addEventListener("drop", (e) => {
        e.preventDefault();
        zone.classList.remove("dragover");
        if (e.dataTransfer.files.length > 0) selectFile(e.dataTransfer.files[0]);
    });
}

function selectFile(file) {
    if (!file.name.toLowerCase().endsWith(".zip")) {
        showToast("Please select a .zip file", "error");
        return;
    }
    selectedZipFile = file;
    const el = document.getElementById("selectedFile");
    el.textContent = file.name + " (" + (file.size / 1024).toFixed(1) + " KB)";
    el.classList.remove("d-none");
}

async function handleUpload(e) {
    e.preventDefault();

    const name = document.getElementById("projectName").value.trim();
    if (!name) { showToast("Enter a project name", "error"); return; }
    if (!selectedZipFile) { showToast("Select a ZIP file", "error"); return; }

    const formData = new FormData();
    formData.append("name", name);
    formData.append("zip_file", selectedZipFile);

    showLoading("Uploading and extracting files...");

    try {
        const result = await fetch("/api/upload", { method: "POST", body: formData });
        const text = await result.text();
        let data;
        try {
            data = JSON.parse(text);
        } catch (e) {
            throw new Error("Server error — please restart the app and try again");
        }
        if (!result.ok) throw new Error(data.detail || "Upload failed");

        uploadedProjectId = data.id;

        document.getElementById("uploadMessage").textContent = data.message;
        document.getElementById("fileCount").textContent = data.file_count;
        document.getElementById("fileList").textContent = data.file_list;
        document.getElementById("postUpload").classList.remove("d-none");
        document.getElementById("uploadBtn").disabled = true;

        showToast("ZIP uploaded successfully!");

    } catch (err) {
        showToast(err.message, "error");
    } finally {
        hideLoading();
    }
}

async function handleGenerate() {
    if (!uploadedProjectId) return;

    const controller = new AbortController();
    showLoading("Generating documentation with Gemini...", {
        onCancel: () => controller.abort()
    });

    try {
        const type = document.getElementById('docType')?.value || 'README';
        const result = await apiRequest(`/api/projects/${uploadedProjectId}/generate?doc_type=${encodeURIComponent(type)}`, {
            method: "POST",
            signal: controller.signal
        });

        showToast(result.message || "Documentation generated!");
        window.location.href = `/documentation?id=${uploadedProjectId}`;

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
