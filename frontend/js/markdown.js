/**
 * Markdown rendering and loading UI helpers.
 */

function markdownToHtml(md) {
    if (!md) return "";
    let html = md;

    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
        `<pre><code class="language-${lang || 'text'}">${escapeHtml(code.trim())}</code></pre>`
    );

    html = html.replace(/^\|(.+)\|\s*\n\|[-| :]+\|\s*\n((?:\|.+\|\s*\n?)*)/gm, (match, header, body) => {
        const ths = header.split("|").filter(c => c.trim()).map(c => `<th>${c.trim()}</th>`).join("");
        const rows = body.trim().split("\n").map(row => {
            const tds = row.split("|").filter(c => c.trim()).map(c => `<td>${c.trim()}</td>`).join("");
            return `<tr>${tds}</tr>`;
        }).join("");
        return `<table><thead><tr>${ths}</tr></thead><tbody>${rows}</tbody></table>`;
    });

    html = html.replace(/^#### (.+)$/gm, "<h4>$1</h4>");
    html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
    html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
    html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");
    html = html.replace(/^> (.+)$/gm, "<blockquote>$1</blockquote>");
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/^---$/gm, "<hr>");
    html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
    html = html.replace(/(<li>.*<\/li>\n?)+/g, m => `<ul>${m}</ul>`);
    html = html.replace(/^\d+\. (.+)$/gm, "<li>$1</li>");
    html = html.replace(/\n\n/g, "</p><p>");
    html = "<p>" + html + "</p>";
    html = html.replace(/<p><(h[1-4]|ul|ol|table|pre|blockquote|hr)/g, "<$1");
    html = html.replace(/<\/(h[1-4]|ul|ol|table|pre|blockquote)><\/p>/g, "</$1>");
    html = html.replace(/<p><\/p>/g, "");
    html = html.replace(/<p><hr><\/p>/g, "<hr>");
    return html;
}

function escapeHtml(text) {
    const d = document.createElement("div");
    d.textContent = text;
    return d.innerHTML;
}

function buildDocSidebar(markdown) {
    const headings = [];
    const regex = /^## (.+)$/gm;
    let match;
    while ((match = regex.exec(markdown)) !== null) {
        const title = match[1].replace(/\*\*/g, "");
        const id = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
        headings.push({ title, id });
    }
    return headings;
}

function countWords(text) {
    return text ? text.split(/\s+/).filter(w => w.length > 0).length : 0;
}

function showAgentLoading() {
    const el = document.createElement("div");
    el.className = "loading-overlay";
    el.id = "loadingOverlay";
    el.innerHTML = `
        <div class="loading-box">
            <div class="spinner-border text-primary mb-3"></div>
            <p class="fw-bold mb-1">Generating Documentation</p>
            <small class="text-muted">Single AI pass — usually 1-4 minutes</small>
            <p class="small text-muted mt-3 mb-0">
                Gemini is reading your code and writing docs.<br>
                If it takes over 5 minutes, cancel and try a smaller ZIP.
            </p>
        </div>`;
    document.body.appendChild(el);
}

function hideAgentLoading() {
    hideLoading();
}
