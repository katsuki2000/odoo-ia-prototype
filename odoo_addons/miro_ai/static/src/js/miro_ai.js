/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, useRef, onPatched, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

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
 * Fullscreen Client Action Assistant Component.
 */
export class MiroAiAssistant extends Component {
    static template = "miro_ai.AssistantClientAction";

    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");
        this.actionService = useService("action");
        this.messagesContainer = useRef("messagesContainer");

        const initialContent = "Bonjour ! Je suis MIRO AI, votre assistant Code Intelligence, ERP et documentaire sur Odoo 17. Comment puis-je vous aider aujourd'hui ?";

        this.state = useState({
            messages: [
                {
                    id: 1,
                    sender: "bot",
                    content: initialContent,
                    formattedContent: formatMarkdown(initialContent),
                    sources: [],
                    route: null,
                    confidence: 1.0,
                    evidence_status: null,
                    omitted_for_authorization: [],
                    investigation_plan: null,
                }
            ],
            inputQuestion: "",
            loading: false,
            sessionId: "odoo_session_" + Date.now(),
            nextMsgId: 2,
        });

        onPatched(() => {
            if (this.messagesContainer.el) {
                this.messagesContainer.el.scrollTop = this.messagesContainer.el.scrollHeight;
            }
        });
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

    async sendMessage() {
        const question = this.state.inputQuestion.trim();
        if (!question || this.state.loading) {
            return;
        }

        const userMsgId = this.state.nextMsgId++;
        this.state.messages.push({
            id: userMsgId,
            sender: "user",
            content: question,
            formattedContent: formatMarkdown(question),
            sources: [],
            route: null,
            confidence: 1.0,
            evidence_status: null,
            omitted_for_authorization: [],
            investigation_plan: null,
        });
        this.state.inputQuestion = "";
        this.state.loading = true;

        try {
            const response = await this.rpc("/miro_ai/ask", {
                question: question,
                session_id: this.state.sessionId,
            });

            if (response && response.answer) {
                const botMsgId = this.state.nextMsgId++;
                this.state.messages.push({
                    id: botMsgId,
                    sender: "bot",
                    content: response.answer,
                    formattedContent: formatMarkdown(response.answer),
                    sources: response.sources || [],
                    route: response.route || null,
                    confidence: response.confidence !== undefined ? response.confidence : 1.0,
                    evidence_status: response.evidence_status || null,
                    omitted_for_authorization: response.omitted_for_authorization || [],
                    investigation_plan: response.investigation_plan || null,
                });
                if (response.session_id) {
                    this.state.sessionId = response.session_id;
                }
            } else {
                throw new Error("Réponse vide de l'assistant.");
            }
        } catch (error) {
            console.error("Erreur MIRO AI:", error);
            const errorMsgId = this.state.nextMsgId++;
            const errMsg = "Désolé, une erreur est survenue lors de la communication avec l'assistant MIRO AI. Veuillez vérifier la connexion ou consulter le journal d'erreurs.";
            this.state.messages.push({
                id: errorMsgId,
                sender: "bot",
                content: errMsg,
                formattedContent: formatMarkdown(errMsg),
                sources: [],
                route: null,
                confidence: 0.0,
                evidence_status: "ERROR",
                omitted_for_authorization: [],
                investigation_plan: null,
            });
            this.notification.add("Erreur de connexion à l'assistant MIRO AI.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }
}

registry.category("actions").add("miro_ai.action_assistant", MiroAiAssistant);


/**
 * Systray Navbar Menu Item Component.
 * Embedded in the top navbar; toggles a floating quick-chat drawer.
 */
export class MiroAiSystray extends Component {
    static template = "miro_ai.SystrayItem";

    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");
        this.actionService = useService("action");

        this.state = useState({
            isOpen: false,
            loading: false,
            inputQuestion: "",
            sessionId: "systray_session_" + Date.now(),
            messages: [
                {
                    id: 1,
                    sender: "bot",
                    content: "Bonjour ! Posez votre question ou interrogez-moi sur le document actif.",
                    formattedContent: formatMarkdown("Bonjour ! Posez votre question ou interrogez-moi sur le document actif."),
                    sources: [],
                    route: null,
                    confidence: 1.0,
                    evidence_status: null,
                    omitted_for_authorization: [],
                    investigation_plan: null,
                }
            ],
            nextMsgId: 2,
            activeModelContext: null,
        });

        this.drawerMessages = useRef("drawerMessages");

        onPatched(() => {
            if (this.drawerMessages.el) {
                this.drawerMessages.el.scrollTop = this.drawerMessages.el.scrollHeight;
            }
        });
    }

    toggleDrawer() {
        this.state.isOpen = !this.state.isOpen;
        if (this.state.isOpen) {
            this.detectActiveContext();
        }
    }

    closeDrawer() {
        this.state.isOpen = false;
    }

    detectActiveContext() {
        try {
            const controller = this.actionService.currentController;
            if (controller && controller.action && controller.action.res_model) {
                const resModel = controller.action.res_model;
                const resId = controller.action.res_id || null;
                this.state.activeModelContext = {
                    model: resModel,
                    id: resId,
                    displayName: controller.action.display_name || resModel,
                };
            } else {
                this.state.activeModelContext = null;
            }
        } catch (e) {
            this.state.activeModelContext = null;
        }
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

    async sendMessage() {
        let question = this.state.inputQuestion.trim();
        if (!question || this.state.loading) {
            return;
        }

        // Contextual enrichment if user is currently looking at a record
        if (this.state.activeModelContext && this.state.activeModelContext.model) {
            const ctxModel = this.state.activeModelContext.model;
            // Only prepend context if not already mentioned in question
            if (!question.toLowerCase().includes(ctxModel.toLowerCase())) {
                // Keep the prompt human-friendly while grounding technical model
                question = `[Contexte: modèle ${ctxModel}] ` + question;
            }
        }

        const userMsgId = this.state.nextMsgId++;
        this.state.messages.push({
            id: userMsgId,
            sender: "user",
            content: this.state.inputQuestion.trim(),
            formattedContent: formatMarkdown(this.state.inputQuestion.trim()),
            sources: [],
            route: null,
            confidence: 1.0,
            evidence_status: null,
            omitted_for_authorization: [],
            investigation_plan: null,
        });
        this.state.inputQuestion = "";
        this.state.loading = true;

        try {
            const response = await this.rpc("/miro_ai/ask", {
                question: question,
                session_id: this.state.sessionId,
            });

            if (response && response.answer) {
                const botMsgId = this.state.nextMsgId++;
                this.state.messages.push({
                    id: botMsgId,
                    sender: "bot",
                    content: response.answer,
                    formattedContent: formatMarkdown(response.answer),
                    sources: response.sources || [],
                    route: response.route || null,
                    confidence: response.confidence !== undefined ? response.confidence : 1.0,
                    evidence_status: response.evidence_status || null,
                    omitted_for_authorization: response.omitted_for_authorization || [],
                    investigation_plan: response.investigation_plan || null,
                });
                if (response.session_id) {
                    this.state.sessionId = response.session_id;
                }
            } else {
                throw new Error("Réponse vide de l'assistant.");
            }
        } catch (error) {
            console.error("Erreur MIRO AI Systray:", error);
            const errorMsgId = this.state.nextMsgId++;
            const errMsg = "Erreur de communication avec l'assistant MIRO AI.";
            this.state.messages.push({
                id: errorMsgId,
                sender: "bot",
                content: errMsg,
                formattedContent: formatMarkdown(errMsg),
                sources: [],
                route: null,
                confidence: 0.0,
                evidence_status: "ERROR",
                omitted_for_authorization: [],
                investigation_plan: null,
            });
            this.notification.add("Erreur de connexion MIRO AI.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }
}

export const miroAiSystrayItem = {
    Component: MiroAiSystray,
};

registry.category("systray").add("miro_ai.SystrayItem", miroAiSystrayItem, { sequence: 40 });
