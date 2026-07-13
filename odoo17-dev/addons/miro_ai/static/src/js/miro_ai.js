/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, useRef, onPatched, markup } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class MiroAiAssistant extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");
        this.messagesContainer = useRef("messagesContainer");
        const initialContent = "Bonjour ! Je suis MIRO AI, votre assistant ERP et documentaire sur Odoo 17. Comment puis-je vous aider aujourd'hui ?";
        this.state = useState({
            messages: [
                {
                    id: 1,
                    sender: "bot",
                    content: initialContent,
                    formattedContent: this.formatMarkdown(initialContent),
                    sources: []
                }
            ],
            inputQuestion: "",
            loading: false,
            sessionId: "odoo_session_" + Date.now(),
            nextMsgId: 2
        });

        onPatched(() => {
            if (this.messagesContainer.el) {
                this.messagesContainer.el.scrollTop = this.messagesContainer.el.scrollHeight;
            }
        });
    }

    formatMarkdown(text) {
        if (!text) return "";
        // 1. Sécurisation anti-XSS par échappement HTML basique
        let html = text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");

        // 2. Blocs de code (fenced code blocks)
        html = html.replace(/```(?:[a-zA-Z0-9_-]+)?\n?([\s\S]*?)```/g, (match, code) => {
            return `<pre class="miro-code-block"><code>${code.trim()}</code></pre>`;
        });

        // 3. Code inline (`code`)
        html = html.replace(/`([^`\n]+)`/g, `<code class="miro-inline-code">$1</code>`);

        // 4. Titres (### Titre, ## Titre)
        html = html.replace(/^###\s+(.*)$/gm, `<h6 class="miro-heading mt-2 mb-1 font-weight-bold">$1</h6>`);
        html = html.replace(/^##\s+(.*)$/gm, `<h5 class="miro-heading mt-2 mb-1 font-weight-bold">$1</h5>`);

        // 5. Gras et italique (**gras**, *italique*)
        html = html.replace(/\*\*([^*\n]+)\*\*/g, `<strong>$1</strong>`);
        html = html.replace(/\*([^*\n]+)\*/g, `<em>$1</em>`);

        // 6. Liens Markdown [texte](url)
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, `<a href="$2" target="_blank" rel="noopener noreferrer" class="miro-link font-weight-bold">$1</a>`);

        // 7. Listes à puces (- élément ou * élément en début de ligne)
        html = html.replace(/(?:^|\n)([-*]\s+.+(?:\n[-*]\s+.+)*)/g, (match, listBlock) => {
            const items = listBlock.trim().split(/\n/).map(line => {
                const itemText = line.replace(/^[-*]\s+/, '');
                return `<li>${itemText}</li>`;
            }).join('');
            return `<ul class="miro-list pl-3 mb-2">${items}</ul>`;
        });

        // 8. Sauts de ligne simples en dehors des balises pre et ul
        // Remplacement des sauts de ligne restants par des <br/>
        const parts = html.split(/(<pre[\s\S]*?<\/pre>|<ul[\s\S]*?<\/ul>)/g);
        for (let i = 0; i < parts.length; i++) {
            if (!parts[i].startsWith('<pre') && !parts[i].startsWith('<ul')) {
                parts[i] = parts[i].replace(/\n/g, '<br/>');
            }
        }
        return markup(parts.join(''));
    }

    onKeyDown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
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
            formattedContent: this.formatMarkdown(question),
            sources: []
        });
        this.state.inputQuestion = "";
        this.state.loading = true;

        try {
            const response = await this.rpc("/miro_ai/ask", {
                question: question,
                session_id: this.state.sessionId
            });

            if (response && response.answer) {
                const botMsgId = this.state.nextMsgId++;
                this.state.messages.push({
                    id: botMsgId,
                    sender: "bot",
                    content: response.answer,
                    formattedContent: this.formatMarkdown(response.answer),
                    sources: response.sources || []
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
                formattedContent: this.formatMarkdown(errMsg),
                sources: []
            });
            this.notification.add("Erreur de connexion à l'assistant MIRO AI.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }
}

MiroAiAssistant.template = "miro_ai.AssistantClientAction";
registry.category("actions").add("miro_ai.action_assistant", MiroAiAssistant);
