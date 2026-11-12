import assert from "node:assert/strict";
import { test } from "node:test";

import { formatMarkdown } from "../../odoo_addons/miro_ai/static/src/js/miro_ai_markdown.js";

const LIST = 'class="miro-list ps-3 mb-2"';

test("empty input gives an empty string", () => {
    assert.equal(formatMarkdown(""), "");
    assert.equal(formatMarkdown(undefined), "");
});

test("raw HTML is escaped and only strong, em and br are kept", () => {
    assert.equal(formatMarkdown("<script>alert(1)</script>"), "&lt;script&gt;alert(1)&lt;/script&gt;");
    assert.equal(formatMarkdown("a<br>b <strong>c</strong>"), "a<br/>b <strong>c</strong>");
});

test("inline formatting, and no formatting inside code", () => {
    assert.equal(formatMarkdown("**bold** and *italic*"), "<strong>bold</strong> and <em>italic</em>");
    assert.equal(formatMarkdown("`**x**`"), '<code class="miro-inline-code">**x**</code>');
    assert.equal(
        formatMarkdown("```js\n**a**\n<b>\n```"),
        '<pre class="miro-code-block"><code>**a**\n&lt;b&gt;</code></pre>'
    );
});

test("only http, https and mailto links are kept", () => {
    assert.match(formatMarkdown("[doc](https://odoo.com)"), /<a href="https:\/\/odoo.com" target="_blank"/);
    assert.equal(formatMarkdown("[x](javascript:void)"), "x");
});

test("headings", () => {
    assert.equal(formatMarkdown("## Title"), '<h5 class="miro-heading mt-2 mb-1 fw-bold">Title</h5>');
    assert.equal(formatMarkdown("### Sub"), '<h6 class="miro-heading mt-2 mb-1 fw-bold">Sub</h6>');
});

test("paragraphs keep their line breaks", () => {
    assert.equal(formatMarkdown("a\n\nb"), "a<br/><br/>b");
    assert.equal(formatMarkdown("a\r\nb"), "a<br/>b");
});

test("nested bullet list", () => {
    assert.equal(
        formatMarkdown("- a\n  - b\n- c"),
        `<ul ${LIST}><li>a<ul ${LIST}><li>b</li></ul></li><li>c</li></ul>`
    );
});

test("numbered list with sub-bullets and blank lines between items stays one list", () => {
    assert.equal(
        formatMarkdown("1. **A**\n   - x\n\n2. B"),
        `<ol ${LIST}><li><strong>A</strong><ul ${LIST}><li>x</li></ul></li><li>B</li></ol>`
    );
});

test("a numbered list that does not start at 1 keeps its number", () => {
    assert.equal(formatMarkdown("3. c"), `<ol ${LIST} start="3"><li>c</li></ol>`);
});

test("a list directly after a paragraph", () => {
    assert.equal(formatMarkdown("Intro:\n- a"), `Intro:<ul ${LIST}><li>a</li></ul>`);
});

test("table with an empty cell", () => {
    const markdown = [
        "| Company | Role | Period |",
        "| :--- | :--- | :--- |",
        "| Logan-Martin | Engineer | 1996 |",
        "| College | | 1999 |",
    ].join("\n");
    assert.equal(
        formatMarkdown(markdown),
        '<div class="miro-table-wrapper"><table class="table table-sm table-bordered miro-table">' +
            "<thead><tr><th>Company</th><th>Role</th><th>Period</th></tr></thead>" +
            "<tbody><tr><td>Logan-Martin</td><td>Engineer</td><td>1996</td></tr>" +
            "<tr><td>College</td><td></td><td>1999</td></tr></tbody></table></div>"
    );
});

test("a line with pipes but no separator row is plain text", () => {
    assert.equal(formatMarkdown("| a | b |"), "| a | b |");
});

test("table cells are escaped and formatted", () => {
    assert.match(formatMarkdown("| h |\n| --- |\n| <i>**x**</i> |"), /<td>&lt;i&gt;<strong>x<\/strong>&lt;\/i&gt;<\/td>/);
});
