/**
 * Lightweight local profile settings page.
 * No backend authentication is introduced by this UI-only profile feature.
 */

const PROFILE_STORAGE_KEY = "ai-doc-assistant-profile";

document.addEventListener("DOMContentLoaded", () => {
    checkGeminiStatus();
    loadProfile();

    document.getElementById("profilePhoto")?.addEventListener("change", handlePhoto);
    document.getElementById("passwordToggle")?.addEventListener("click", togglePassword);
    document.getElementById("profileForm")?.addEventListener("submit", saveProfile);
});

function loadProfile() {
    const saved = localStorage.getItem(PROFILE_STORAGE_KEY);
    if (!saved) return;

    try {
        const profile = JSON.parse(saved);
        document.getElementById("profileName").value = profile.name || "";
        document.getElementById("profileEmail").value = profile.email || "";
        if (profile.photo) setPhotoPreview(profile.photo);
    } catch (_) {
        localStorage.removeItem(PROFILE_STORAGE_KEY);
    }
}

function handlePhoto(event) {
    const file = event.target.files?.[0];
    if (!file || !file.type.startsWith("image/")) {
        showToast("Please select an image file.", "error");
        return;
    }

    const reader = new FileReader();
    reader.onload = () => setPhotoPreview(reader.result);
    reader.readAsDataURL(file);
}

function setPhotoPreview(dataUrl) {
    const img = document.getElementById("profilePhotoPreview");
    const placeholder = document.getElementById("profileAvatarPlaceholder");
    img.src = dataUrl;
    img.classList.add("visible");
    placeholder.classList.add("d-none");
}

function togglePassword() {
    const input = document.getElementById("profilePassword");
    const button = document.getElementById("passwordToggle");
    if (!input || !button) return;

    const visible = input.type === "text";
    input.type = visible ? "password" : "text";
    button.setAttribute("aria-label", visible ? "Show password" : "Hide password");
    button.innerHTML = visible
        ? '<i class="bi bi-eye"></i>'
        : '<i class="bi bi-eye-slash"></i>';
}

function saveProfile(event) {
    event.preventDefault();

    const name = document.getElementById("profileName").value.trim();
    const email = document.getElementById("profileEmail").value.trim();
    const password = document.getElementById("profilePassword").value;
    const confirmPassword = document.getElementById("profilePasswordConfirm").value;
    const img = document.getElementById("profilePhotoPreview");

    if (!name) {
        showToast("Enter your name.", "error");
        return;
    }
    if (!email) {
        showToast("Enter your email.", "error");
        return;
    }
    if (password && password !== confirmPassword) {
        showToast("Passwords do not match.", "error");
        return;
    }

    const existing = localStorage.getItem(PROFILE_STORAGE_KEY);
    let oldPhoto = "";
    try { oldPhoto = JSON.parse(existing || "{}").photo || ""; } catch (_) {}

    localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify({
        name,
        email,
        photo: img.classList.contains("visible") ? img.src : oldPhoto
    }));

    showToast("Profile saved successfully.");
}
