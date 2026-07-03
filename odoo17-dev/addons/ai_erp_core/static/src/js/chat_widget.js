/** @odoo-module **/
/**
 * chat_widget.js
 * ==============
 * Odoo 17 OWL chat widget for the AI ERP Core assistant.
 *
 * Features:
 *   - Renders conversation messages with role avatars
 *   - Animated "thinking" indicator while waiting for the LLM
 *   - Displays source citations with pipeline type tags
 *   - Auto-scrolls to the latest message
 *   - Suggestion chips on empty state
 *   - Ctrl+Enter or Send button to submit
 *   - Calls /ai_erp/chat JSON endpoint
 */

import { Component, useState, useRef, onMounted, onPatched } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const SUGGESTIONS = [
    "Quel est le chiffre d'affaires du client ACME cette année ?",
    "Où est implémentée la validation des factures dans le code ?",
    "Quelles sont les règles d'approbation pour les bons de commande ?",
    "Quels sont les 10 produits les plus vendus en 2024 ?",
    "Quel est le stock disponible du produit X ?",
];

const PIPELINE_LABELS = {
    doc_rag: "📄 Documents",
    code_rag: "💻 Code source",
    orm_tool: "🗃️ Données ERP",
    combined: "🔀 Combiné",
    fallback: "💬 Direct",
};

// ─────────────────────────────────────────────────────────────────────────────

class AiChatWidget extends Component {
    static template = "ai_erp_core.ChatWidget";
    static props = {
        record: { type: Object },
        readonly: { type: Boolean, optional: true },
    };

    setup() {
        this.rpc = useService("rpc");
        this.state = useState({
            messages: [],
            inputText: "",
            isThinking: false,
            conversationId: null,
            error: null,
        });

        this.messagesRef = useRef("messagesContainer");
        this.inputRef = useRef("chatInput");

        onMounted(() => this._loadExistingMessages());
        onPatched(() => this._scrollToBottom());
    }

    // ── Data loading ────────────────────────────────────────────────────────

    async _loadExistingMessages() {
        const convId = this.props.record.data.id;
        if (!convId || convId === false) return;

        this.state.conversationId = convId;
        try {
            const result = await this.rpc(`/ai_erp/conversation/${convId}/messages`, {});
            if (result.messages) {
                this.state.messages = result.messages.map((m) => ({
                    id: m.id,
                    role: m.role,
                    content: m.content,
                    pipeline_used: m.pipeline_used || "",
                    citations: m.citations || [],
                    duration_ms: m.duration_ms || 0,
                }));
            }
        } catch (e) {
            console.error("AI ERP: failed to load conversation messages", e);
        }
    }

    // ── Message sending ──────────────────────────────────────────────────────

    async sendMessage() {
        const text = this.state.inputText.trim();
        if (!text || this.state.isThinking) return;

        // Optimistically add user message
        this.state.messages.push({
            id: Date.now(),
            role: "user",
            content: text,
            pipeline_used: "",
            citations: [],
        });
        this.state.inputText = "";
        this.state.isThinking = true;
        this.state.error = null;

        try {
            const result = await this.rpc("/ai_erp/chat", {
                conversation_id: this.state.conversationId || null,
                message: text,
            });

            if (result.error) {
                this.state.error = result.error;
            } else {
                // Update conversation ID if this was a new session
                if (result.conversation_id) {
                    this.state.conversationId = result.conversation_id;
                }
                this.state.messages.push({
                    id: result.message_id || Date.now() + 1,
                    role: "assistant",
                    content: result.content,
                    pipeline_used: result.pipeline_used || "fallback",
                    citations: result.citations || [],
                    duration_ms: result.duration_ms || 0,
                });
            }
        } catch (err) {
            this.state.error = `Erreur de communication avec le serveur : ${err.message || err}`;
        } finally {
            this.state.isThinking = false;
        }
    }

    // ── UI helpers ──────────────────────────────────────────────────────────

    _scrollToBottom() {
        const el = this.messagesRef.el;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }

    onKeyDown(ev) {
        if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) {
            ev.preventDefault();
            this.sendMessage();
        }
    }

    onInput(ev) {
        this.state.inputText = ev.target.value;
        // Auto-resize textarea
        ev.target.style.height = "auto";
        ev.target.style.height = Math.min(ev.target.scrollHeight, 120) + "px";
    }

    useSuggestion(text) {
        this.state.inputText = text;
        if (this.inputRef.el) this.inputRef.el.focus();
    }

    getPipelineLabel(pipeline) {
        return PIPELINE_LABELS[pipeline] || pipeline || "";
    }

    formatDuration(ms) {
        if (!ms) return "";
        if (ms < 1000) return `${ms}ms`;
        return `${(ms / 1000).toFixed(1)}s`;
    }

    get suggestions() {
        return SUGGESTIONS;
    }

    get hasMessages() {
        return this.state.messages.filter((m) => m.role !== "system").length > 0;
    }
}

// ── OWL Template ─────────────────────────────────────────────────────────────
// Registered inline for self-containment

AiChatWidget.template = "ai_erp_core.ChatWidget";

registry.category("fields").add("ai_chat_messages", {
    component: AiChatWidget,
});

export { AiChatWidget };
