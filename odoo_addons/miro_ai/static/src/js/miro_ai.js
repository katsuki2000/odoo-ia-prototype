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
    exchangeCountLabel,
    loadHistoryErrorLabel,
    loadSessionErrorLabel,
    senderLabel,
    systrayInitialContent,
    verifyLinkLabel,
} from "@miro_ai/js/miro_ai_labels";
import { formatMarkdown } from "@miro_ai/js/miro_ai_markdown";

const POLL_INTERVAL_MS = 2000;

/**
 * True when an rpc() promise was interrupted by promise.abort() (cf.
 * cancelRequest()) rather than by a real network
 * or server failure -- lets sendMessage() skip the generic error bubble
 * and notification for a cancellation the user asked for themselves.
 */
function isRequestCancelled(error) {
    return error instanceof ConnectionAbortedError;
}

/**
 * Builds a chat message object with sensible defaults, so callers only need
 * to override what actually differs (avoids repeating the same shape
 * everywhere a message is pushed).
 */
function createMessage(id, sender, content, extra = {}) {
    return Object.assign({
        id,
        sender,
        content,
        formattedContent: markup(formatMarkdown(content)),
        cancelled: false,
    }, extra);
}

function newSessionId() {
    return "systray_session_" + Date.now();
}

/**
 * Rebuilds an ordered message list from a backend conversation history
 * (list of question/answer turns) so a past session can be resumed like
 * a fresh chat.
 */
function buildMessagesFromHistory(history) {
    const messages = [];
    let nextId = 1;
    for (const turn of history || []) {
        messages.push(createMessage(nextId++, "user", turn.question || ""));
        messages.push(createMessage(nextId++, "bot", turn.answer || ""));
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
 * Read once at mount time (cf. onMounted) --
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
        this.action = useService("action");
        this.pendingRequest = null;

        this.state = useState({
            isOpen: false,
            loading: false,
            inputQuestion: "",
            sessionId: newSessionId(),
            messages: [createMessage(1, "bot", systrayInitialContent())],
            nextMsgId: 2,
            source: "system",
            showHistory: false,
            loadingSessions: false,
            sessions: [],
        });

        this.drawerMessages = useRef("drawerMessages");
        this.drawerInput = useRef("drawerInput");

        onPatched(() => {
            if (this.drawerMessages.el) {
                this.drawerMessages.el.scrollTop = this.drawerMessages.el.scrollHeight;
            }
            this.fitInput();
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

    getVerifyLinkLabel(msg) {
        return verifyLinkLabel(msg.verifyLink.label);
    }

    /**
     * Opens in Odoo the list the agent read, under the rights of the current user.
     * The model and domain come from the backend evidence (never from the answer text).
     */
    openVerifyLink(link) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: link.label,
            res_model: link.model,
            domain: link.domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    /** Grows the question box with its content; the CSS max-height makes it scroll beyond. */
    fitInput() {
        const input = this.drawerInput.el;
        if (input) {
            input.style.height = "auto";
            input.style.height = `${input.scrollHeight + input.offsetHeight - input.clientHeight}px`;
        }
    }

    resetConversation() {
        this.state.messages = [createMessage(1, "bot", systrayInitialContent())];
        this.state.nextMsgId = 2;
        this.state.sessionId = newSessionId();
    }

    startNewConversation() {
        this.resetConversation();
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

    /**
     * Stops waiting for the answer (cf. rpc_service.js promise.abort()).
     * Only unblocks the UI client-side -- the backend keeps computing the
     * answer until its result expires, this is not a true kill-switch.
     */
    cancelRequest() {
        this.cancelled = true;
        if (this.pendingRequest && typeof this.pendingRequest.abort === "function") {
            this.pendingRequest.abort();
        }
    }

    /**
     * Submits the question, then polls /miro_ai/ask_result until the answer is ready.
     */
    async askAndWait(rpcPayload) {
        this.cancelled = false;
        this.pendingRequest = this.rpc("/miro_ai/ask", rpcPayload);
        const submitted = await this.pendingRequest;
        if (!submitted.job_id) {
            return submitted;
        }
        for (;;) {
            await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
            if (this.cancelled) {
                throw new ConnectionAbortedError("Request cancelled by the user.");
            }
            this.pendingRequest = this.rpc("/miro_ai/ask_result", {
                job_id: submitted.job_id,
                session_id: submitted.session_id,
            });
            const result = await this.pendingRequest;
            if (result.status !== "pending") {
                return { session_id: submitted.session_id, ...result };
            }
        }
    }

    selectSource(name) {
        this.state.source = name;
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
            source_mode: this.state.source,
        };

        try {
            const response = await this.askAndWait(rpcPayload);

            if (response && response.answer) {
                this.state.messages.push(createMessage(this.state.nextMsgId++, "bot", response.answer, {
                    verifyLink: response.verify_link || null,
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
                this.state.messages.push(createMessage(this.state.nextMsgId++, "bot", errMsg));
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
