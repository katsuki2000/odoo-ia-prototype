/** @odoo-module **/

const SAFE_LINK_RE = /^(https?:\/\/|mailto:)/i;
const FENCED_CODE_RE = /```(?:[\w-]+)?\n?([\s\S]*?)```/;
const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };

const escapeHtml = (text) => text.replace(/[&<>"']/g, (char) => HTML_ESCAPES[char]);

function formatSpans(text) {
    return text
        .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
        .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, label, url) =>
            SAFE_LINK_RE.test(url.trim())
                ? `<a href="${url.trim()}" target="_blank" rel="noopener noreferrer" class="miro-link fw-bold">${label}</a>`
                : label
        );
}

function formatInline(text) {
    return text
        .split(/(`[^`\n]+`)/)
        .map((part, index) =>
            index % 2 ? `<code class="miro-inline-code">${part.slice(1, -1)}</code>` : formatSpans(part)
        )
        .join("");
}

/**
 * Renders the plain-text subset described in core/markdown_format.py.
 * Every character is escaped first, so only the tags generated here reach the page.
 */
export function formatMarkdown(text) {
    if (!text) {
        return "";
    }
    return escapeHtml(text)
        .split(new RegExp(FENCED_CODE_RE, "g"))
        .map((part, index) =>
            index % 2
                ? `<pre class="miro-code-block"><code>${part.trim()}</code></pre>`
                : formatInline(part.trim()).replace(/\n/g, "<br/>")
        )
        .join("");
}
