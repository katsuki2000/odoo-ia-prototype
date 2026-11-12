/** @odoo-module **/

const SAFE_LINK_RE = /^(https?:\/\/|mailto:)/i;
const FENCE_RE = /^```/;
const HEADING_RE = /^(#{2,3})\s+(.*)$/;
const LIST_ITEM_RE = /^(\s*)([-*]|\d+\.)\s+(.*)$/;
const TABLE_ROW_RE = /^\s*\|.*\|\s*$/;
const TABLE_SEPARATOR_RE = /^\s*\|(\s*:?-+:?\s*\|)+\s*$/;
const ALLOWED_TAG_RE = /&lt;(\/?)(strong|em|br)\s*\/?&gt;/gi;
const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };

const escapeHtml = (text) => text.replace(/[&<>"']/g, (char) => HTML_ESCAPES[char]);

function formatSpans(text) {
    return text
        .replace(ALLOWED_TAG_RE, (match, closing, tag) =>
            tag.toLowerCase() === "br" ? "<br/>" : `<${closing}${tag.toLowerCase()}>`
        )
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

function formatList(items) {
    const stack = [];
    let html = "";
    for (const item of items) {
        const [, spaces, marker, content] = LIST_ITEM_RE.exec(item);
        const indent = spaces.length;
        const tag = marker.endsWith(".") ? "ol" : "ul";
        while (stack.length && stack.at(-1).indent > indent) {
            html += `</li></${stack.pop().tag}>`;
        }
        if (stack.at(-1)?.indent === indent) {
            html += "</li>";
            if (stack.at(-1).tag !== tag) {
                html += `</${stack.pop().tag}>`;
            }
        }
        if ((stack.at(-1)?.indent ?? -1) < indent) {
            const number = parseInt(marker, 10);
            const start = number > 1 ? ` start="${number}"` : "";
            html += `<${tag} class="miro-list ps-3 mb-2"${start}>`;
            stack.push({ indent, tag });
        }
        html += `<li>${formatInline(content)}`;
    }
    while (stack.length) {
        html += `</li></${stack.pop().tag}>`;
    }
    return html;
}

const splitCells = (row) => row.trim().replace(/^\||\|$/g, "").split("|");

const tableRow = (row, tag) =>
    `<tr>${splitCells(row).map((cell) => `<${tag}>${formatInline(cell.trim())}</${tag}>`).join("")}</tr>`;

function formatTable([header, , ...body]) {
    return (
        '<div class="miro-table-wrapper"><table class="table table-sm table-bordered miro-table">' +
        `<thead>${tableRow(header, "th")}</thead>` +
        `<tbody>${body.map((row) => tableRow(row, "td")).join("")}</tbody></table></div>`
    );
}

// Each reader returns [html, index of the next line], or null when the block does not start at `start`.
function readCodeBlock(lines, start) {
    if (!FENCE_RE.test(lines[start])) {
        return null;
    }
    let end = start + 1;
    while (end < lines.length && !FENCE_RE.test(lines[end])) {
        end++;
    }
    const code = lines.slice(start + 1, end).join("\n");
    return [`<pre class="miro-code-block"><code>${code}</code></pre>`, end + 1];
}

function readHeading(lines, start) {
    const match = HEADING_RE.exec(lines[start]);
    if (!match) {
        return null;
    }
    const tag = match[1].length === 2 ? "h5" : "h6";
    return [`<${tag} class="miro-heading mt-2 mb-1 fw-bold">${formatInline(match[2])}</${tag}>`, start + 1];
}

function readTable(lines, start) {
    if (!TABLE_ROW_RE.test(lines[start]) || !TABLE_SEPARATOR_RE.test(lines[start + 1] ?? "")) {
        return null;
    }
    let end = start + 2;
    while (end < lines.length && TABLE_ROW_RE.test(lines[end])) {
        end++;
    }
    return [formatTable(lines.slice(start, end)), end];
}

function readList(lines, start) {
    if (!LIST_ITEM_RE.test(lines[start])) {
        return null;
    }
    const items = [];
    let end = start;
    while (end < lines.length) {
        if (LIST_ITEM_RE.test(lines[end])) {
            items.push(lines[end++]);
        } else if (!lines[end].trim() && LIST_ITEM_RE.test(lines[end + 1] ?? "")) {
            end++;
        } else {
            break;
        }
    }
    return [formatList(items), end];
}

const BLOCK_READERS = [readCodeBlock, readHeading, readTable, readList];

/**
 * Converts the Markdown subset described in core/markdown_format.py to HTML.
 * Every character is escaped first, so only the tags generated here reach the page.
 */
export function formatMarkdown(text) {
    if (!text) {
        return "";
    }
    const lines = escapeHtml(text).split(/\r?\n/);
    const blocks = [];
    let paragraph = [];
    const flushParagraph = () => {
        const content = paragraph.join("\n").trim();
        if (content) {
            blocks.push(content.split("\n").map(formatInline).join("<br/>"));
        }
        paragraph = [];
    };
    let index = 0;
    while (index < lines.length) {
        let block = null;
        for (const reader of BLOCK_READERS) {
            block = reader(lines, index);
            if (block) {
                break;
            }
        }
        if (block) {
            flushParagraph();
            blocks.push(block[0]);
            index = block[1];
        } else {
            paragraph.push(lines[index++]);
        }
    }
    flushParagraph();
    return blocks.join("");
}
