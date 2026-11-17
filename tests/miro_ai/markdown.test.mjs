import assert from "node:assert/strict";
import { test } from "node:test";

import { formatMarkdown } from "../../odoo_addons/miro_ai/static/src/js/miro_ai_markdown.js";

test("empty input gives an empty string", () => {
    assert.equal(formatMarkdown(""), "");
    assert.equal(formatMarkdown(null), "");
});

test("raw HTML is escaped, including strong, em and br", () => {
    const html = formatMarkdown('<script>alert("x")</script> <strong>a</strong><br>');
    assert.ok(!html.includes("<script>") && !html.includes("<strong>a"));
    assert.ok(html.includes("&lt;strong&gt;a&lt;/strong&gt;"));
});

test("bold, italic and inline code", () => {
    assert.equal(
        formatMarkdown("**a** *b* `c`"),
        '<strong>a</strong> <em>b</em> <code class="miro-inline-code">c</code>'
    );
});

test("no formatting inside code", () => {
    assert.equal(formatMarkdown("`**a**`"), '<code class="miro-inline-code">**a**</code>');
    assert.equal(
        formatMarkdown("```py\n**a**\n```"),
        '<pre class="miro-code-block"><code>**a**</code></pre>'
    );
});

test("an unclosed code fence stays plain text", () => {
    assert.ok(!formatMarkdown("```\nabc").includes("<pre"));
});

test("only http, https and mailto links are kept", () => {
    assert.ok(formatMarkdown("[a](https://x.io)").includes('href="https://x.io"'));
    assert.equal(formatMarkdown("[a](javascript:void)"), "a");
});

test("lines keep their line breaks and unsupported syntax stays readable", () => {
    assert.equal(formatMarkdown("a\n- b\n- c"), "a<br/>- b<br/>- c");
});
