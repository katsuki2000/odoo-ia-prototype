/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, useRef, onPatched, onMounted } from "@odoo/owl";
import { markup } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { ConnectionAbortedError } from "@web/core/network/rpc_service";

const SYSTRAY_INITIAL_CONTENT = "Bonjour ! Posez votre question ou interrogez-moi sur le document actif.";
const CANCELLED_CONTENT = "Question annulée.";

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
 * Escape plain-text responses for safe rendering and preserve line breaks.
 * Answers are not interpreted as Markdown or HTML.
 */
export function formatPlainText(text) {
    if (!text) return "";
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;")
        .replace(/\n/g, "<br/>");
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
        formattedContent: markup(formatPlainText(content)),
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
            messages: [createMessage(1, "bot", SYSTRAY_INITIAL_CONTENT)],
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

    startNewConversation() {
        this.state.messages = [createMessage(1, "bot", SYSTRAY_INITIAL_CONTENT)];
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
            console.error("Erreur chargement historique MIRO AI Systray:", error);
            this.notification.add("Impossible de charger l'historique des conversations.", { type: "danger" });
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
            console.error("Erreur chargement session MIRO AI Systray:", error);
            this.notification.add("Impossible de charger cette conversation.", { type: "danger" });
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
        switch (route) {
            case "code_intelligence": return "Code Intelligence";
            case "donnees_erp": return "Données ERP";
            case "documentaire": return "Documentaire";
            case "hybride": return "Hybride";
            default: return route || "Général";
        }
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
                throw new Error("Réponse vide de l'assistant.");
            }
        } catch (error) {
            if (isRequestCancelled(error)) {
                this.state.messages.push(createMessage(this.state.nextMsgId++, "bot", CANCELLED_CONTENT, {
                    cancelled: true,
                }));
            } else {
                console.error("Erreur MIRO AI Systray:", error);
                const errMsg = "Erreur de communication avec l'assistant MIRO AI.";
                this.state.messages.push(createMessage(this.state.nextMsgId++, "bot", errMsg, {
                    confidence: 0.0,
                    evidence_status: "ERROR",
                }));
                this.notification.add("Erreur de connexion MIRO AI.", { type: "danger" });
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
