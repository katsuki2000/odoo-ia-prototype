/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, useRef, onPatched } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class MiroAiAssistant extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");
        this.messagesContainer = useRef("messagesContainer");
        this.state = useState({
            messages: [
                {
                    id: 1,
                    sender: "bot",
                    content: "Bonjour ! Je suis MIRO AI, votre assistant ERP et documentaire sur Odoo 17. Comment puis-je vous aider aujourd'hui ?",
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
            this.state.messages.push({
                id: errorMsgId,
                sender: "bot",
                content: "Désolé, une erreur est survenue lors de la communication avec l'assistant MIRO AI. Veuillez vérifier la connexion ou consulter le journal d'erreurs.",
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
