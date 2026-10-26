/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, useRef, onPatched, onMounted } from "@odoo/owl";
import { markup } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { ConnectionAbortedError } from "@web/core/network/rpc_service";
import {
    cancelledContent,
    communicationErrorLabel,
    connectionErrorLabel,
    evidenceLabel,
    exchangeCountLabel,
    loadHistoryErrorLabel,
    loadSessionErrorLabel,
    routeLabel,
    senderLabel,
    systrayInitialContent,
} from "@miro_ai/js/miro_ai_labels";

/**
 * True when an rpc() promise was interrupted by promise.abort() (cf.
 * cancelRequest() in both chat components) rather than by a real network
 * or server failure -- lets sendMessage() skip the generic error bubble
 * and notification for a cancellation the user asked for themselves.
 */
function isRequestCancelled(error) {
    return error instanceof ConnectionAbortedError;
}

/**
 * Shared Markdown Formatter for MIRO AI responses.
 * Converts headings, code blocks, lists, links, and bold/italic safely.
 */
export function formatMarkdown(text) {
    if (!text) return "";
    let html = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");


    const ALLOWED_HTML_TAGS_RE = /&lt;(\/?)(strong|em|br)\s*\/?&gt;/gi;
    html = html.replace(ALLOWED_HTML_TAGS_RE, (match, closingSlash, tagName) => {
        const tag = tagName.toLowerCase();
        if (tag === "br") {
            return "<br/>";
        }
        return closingSlash ? `</${tag}>` : `<${tag}>`;
    });

    // Fenced code blocks
    html = html.replace(/```(?:[a-zA-Z0-9_-]+)?\n?([\s\S]*?)```/g, (match, code) => {
        return `<pre class="miro-code-block"><code>${code.trim()}</code></pre>`;
    });

    // Inline code
    html = html.replace(/`([^`\n]+)`/g, `<code class="miro-inline-code">$1</code>`);

    // Headings
    html = html.replace(/^###\s+(.*)$/gm, `<h6 class="miro-heading mt-2 mb-1 font-weight-bold">$1</h6>`);
    html = html.replace(/^##\s+(.*)$/gm, `<h5 class="miro-heading mt-2 mb-1 font-weight-bold">$1</h5>`);

    // Bold and Italic
    html = html.replace(/\*\*([^*\n]+)\*\*/g, `<strong>$1</strong>`);
    html = html.replace(/\*([^*\n]+)\*/g, `<em>$1</em>`);

    // Markdown Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, `<a href="$2" target="_blank" rel="noopener noreferrer" class="miro-link font-weight-bold">$1</a>`);

    // Unordered lists
    html = html.replace(/(?:^|\n)([-*]\s+.+(?:\n[-*]\s+.+)*)/g, (match, listBlock) => {
        const items = listBlock.trim().split(/\n/).map(line => {
            const itemText = line.replace(/^[-*]\s+/, '');
            return `<li>${itemText}</li>`;
        }).join('');
        return `<ul class="miro-list pl-3 mb-2">${items}</ul>`;
    });

    // Line breaks outside <pre> and <ul>
    const parts = html.split(/(<pre[\s\S]*?<\/pre>|<ul[\s\S]*?<\/ul>)/g);
    for (let i = 0; i < parts.length; i++) {
        if (!parts[i].startsWith('<pre') && !parts[i].startsWith('<ul')) {
            parts[i] = parts[i].replace(/\n/g, '<br/>');
        }
    }
    return parts.join('');
}

/**
 * Builds a chat message object with sensible defaults for all optional
 * verification fields (sources, route, plan, etc.), so callers only need
 * to override what actually differs (avoids repeating the same shape
 * everywhere a message is pushed).
 */
function createMessage(id, sender, content, extra = {}) {
    return Object.assign({
        id,
        sender,
        content,
        formattedContent: markup(formatMarkdown(content)),
        sources: [],
        route: null,
        confidence: 1.0,
        evidence_status: null,
        omitted_for_authorization: [],
        investigation_plan: null,
        cancelled: false,
    }, extra);
}

/**
 * Rebuilds an ordered message list from a backend conversation history
 * (list of question/answer turns) so a past session can be resumed like
 * a fresh chat. Shared between the fullscreen assistant and the systray
 * drawer, which both persist/replay history the same way.
 */
function buildMessagesFromHistory(history) {
    const messages = [];
    let nextId = 1;
    for (const turn of history || []) {
        messages.push(createMessage(nextId++, "user", turn.question || ""));
        messages.push(createMessage(nextId++, "bot", turn.answer || "", {
            sources: turn.sources || [],
            route: turn.route || null,
            confidence: turn.confidence !== undefined && turn.confidence !== null ? turn.confidence : 1.0,
            evidence_status: turn.evidence_status || null,
            omitted_for_authorization: turn.omitted_for_authorization || [],
            investigation_plan: turn.investigation_plan || null,
        }));
    }
    return { messages, nextId };
}

/**
 * Formats an Odoo UTC "create_date" ISO string (naive, no timezone suffix)
 * for display in the user's local time.
 */
function formatSessionDate(isoString) {
    if (!isoString) return "";
    try {
        const date = new Date(isoString.endsWith("Z") ? isoString : isoString + "Z");
        return date.toLocaleString();
    } catch (e) {
        return isoString;
    }
}

/**
 * Reads the Odoo backend header's actual rendered background color
 * (whatever it resolves to: default brand purple, a custom per-company
 * theme color, a future theme module override, etc.) and exposes it as
 * a CSS custom property on the document root, so MIRO AI's send button
 * and user-message bubbles can match it via var(--miro-brand-color, ...)
 * instead of a color hardcoded here that would drift from the real theme.
 * Read once at mount time (cf. onMounted in both chat components) --
 * does not track live theme/company changes mid-session.
 */
function applyBrandColorFromHeader() {
    const navbar = document.querySelector(".o_main_navbar");
    if (!navbar) {
        return;
    }
    const bg = window.getComputedStyle(navbar).backgroundColor;
    if (bg) {
        document.documentElement.style.setProperty("--miro-brand-color", bg);
    }
}


/**
 * Systray Navbar Menu Item Component.
 * Embedded in the top navbar; toggles a floating quick-chat drawer.
 */
export class MiroAiSystray extends Component {
    static template = "miro_ai.SystrayItem";

    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");
        this.pendingRequest = null;

        this.state = useState({
            isOpen: false,
            loading: false,
            inputQuestion: "",
            sessionId: "systray_session_" + Date.now(),
            messages: [createMessage(1, "bot", systrayInitialContent())],
            nextMsgId: 2,
            sourceMode: null,
            showHistory: false,
            loadingSessions: false,
            sessions: [],
        });

        this.drawerMessages = useRef("drawerMessages");

        onPatched(() => {
            if (this.drawerMessages.el) {
                this.drawerMessages.el.scrollTop = this.drawerMessages.el.scrollHeight;
            }
        });

        onMounted(() => applyBrandColorFromHeader());
    }

    formatSessionDate(isoString) {
        return formatSessionDate(isoString);
    }

    getSenderLabel(msg) {
        return senderLabel(msg.sender);
    }

    getExchangeCountLabel(count) {
        return exchangeCountLabel(count);
    }

    getEvidenceLabel(count) {
        return evidenceLabel(count);
    }

    startNewConversation() {
        this.state.messages = [createMessage(1, "bot", systrayInitialContent())];
        this.state.nextMsgId = 2;
        this.state.sessionId = "systray_session_" + Date.now();
        this.state.showHistory = false;
    }

    toggleHistory() {
        this.state.showHistory = !this.state.showHistory;
        if (this.state.showHistory) {
            this.loadSessions();
        }
    }

    async loadSessions() {
        this.state.loadingSessions = true;
        try {
            const sessions = await this.rpc("/miro_ai/sessions", {});
            this.state.sessions = sessions || [];
        } catch (error) {
            console.error("MIRO AI Systray: loading the history failed:", error);
            this.notification.add(loadHistoryErrorLabel(), { type: "danger" });
        } finally {
            this.state.loadingSessions = false;
        }
    }

    async loadSession(sessionId) {
        if (!sessionId || this.state.loading) {
            return;
        }
        this.state.loading = true;
        try {
            const history = await this.rpc("/miro_ai/history", { session_id: sessionId });
            const { messages, nextId } = buildMessagesFromHistory(history);
            if (messages.length) {
                this.state.messages = messages;
                this.state.nextMsgId = nextId;
            }
            this.state.sessionId = sessionId;
            this.state.showHistory = false;
        } catch (error) {
            console.error("MIRO AI Systray: loading the session failed:", error);
            this.notification.add(loadSessionErrorLabel(), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    toggleDrawer() {
        this.state.isOpen = !this.state.isOpen;
    }

    closeDrawer() {
        this.state.isOpen = false;
    }

    onKeyDown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
    }

    getRouteBadgeClass(route) {
        switch (route) {
            case "code_intelligence": return "badge-code-intelligence";
            case "donnees_erp": return "badge-donnees-erp";
            case "documentaire": return "badge-documentaire";
            case "hybride": return "badge-hybride";
            default: return "badge-secondary";
        }
    }

    getRouteLabel(route) {
        return routeLabel(route);
    }

    getConfidencePercent(confidence) {
        if (confidence === null || confidence === undefined) return 100;
        return Math.round(confidence * 100);
    }

    /**
     * Aborts the in-flight /miro_ai/ask request (cf. rpc_service.js
     * promise.abort()). Only unblocks the UI client-side -- the Odoo
     * worker's blocking call to the FastAPI RAG backend keeps running
     * server-side until it returns, this is not a true kill-switch.
     */
    cancelRequest() {
        if (this.pendingRequest && typeof this.pendingRequest.abort === "function") {
            this.pendingRequest.abort();
        }
    }

    toggleSourceMode(mode) {
        this.state.sourceMode = this.state.sourceMode === mode ? null : mode;
    }

    async sendMessage() {
        const question = this.state.inputQuestion.trim();
        if (!question || this.state.loading) {
            return;
        }

        this.state.messages.push(createMessage(this.state.nextMsgId++, "user", question));
        this.state.inputQuestion = "";
        this.state.loading = true;

        const rpcPayload = {
            question: question,
            session_id: this.state.sessionId,
        };
        // Explicit source chosen by the user ("documentation" | "systeme"); null = automatic routing.
        if (this.state.sourceMode) {
            rpcPayload.source_mode = this.state.sourceMode;
        }

        const rpcPromise = this.rpc("/miro_ai/ask", rpcPayload);
        this.pendingRequest = rpcPromise;

        try {
            const response = await rpcPromise;

            if (response && response.answer) {
                this.state.messages.push(createMessage(this.state.nextMsgId++, "bot", response.answer, {
                    sources: response.sources || [],
                    route: response.route || null,
                    confidence: response.confidence !== undefined ? response.confidence : 1.0,
                    evidence_status: response.evidence_status || null,
                    omitted_for_authorization: response.omitted_for_authorization || [],
                    investigation_plan: response.investigation_plan || null,
                }));
                if (response.session_id) {
                    this.state.sessionId = response.session_id;
                }
            } else {
                throw new Error("Empty answer from the assistant.");
            }
        } catch (error) {
            if (isRequestCancelled(error)) {
                this.state.messages.push(createMessage(this.state.nextMsgId++, "bot", cancelledContent(), {
                    cancelled: true,
                }));
            } else {
                console.error("MIRO AI Systray error:", error);
                const errMsg = communicationErrorLabel();
                this.state.messages.push(createMessage(this.state.nextMsgId++, "bot", errMsg, {
                    confidence: 0.0,
                    evidence_status: "ERROR",
                }));
                this.notification.add(connectionErrorLabel(), { type: "danger" });
            }
        } finally {
            this.pendingRequest = null;
            this.state.loading = false;
        }
    }
}

export const miroAiSystrayItem = {
    Component: MiroAiSystray,
};

registry.category("systray").add("miro_ai.SystrayItem", miroAiSystrayItem, { sequence: 40 });
