/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";

// Translatable strings of the MIRO AI assistant.
//
// They live in their own module on purpose: Odoo extracts JavaScript terms with Babel, whose
// tokenizer gives up at the regular-expression literals of the Markdown formatter in
// miro_ai.js, so any _t() call placed after that point would silently miss the .pot file.

export const systrayInitialContent = () => _t("Hello! Ask me your question, or ask about the active document.");

export const cancelledContent = () => _t("Question cancelled.");

export const loadHistoryErrorLabel = () => _t("Unable to load the conversation history.");

export const loadSessionErrorLabel = () => _t("Unable to load this conversation.");

export const deleteSessionLabel = () => _t("Delete");

export const deleteSessionTitle = () => _t("Delete conversation");

export const deleteSessionBody = () => _t("This conversation will be removed from your history.");

export const deleteSessionErrorLabel = () => _t("Unable to delete this conversation.");

export const communicationErrorLabel = () => _t("Error communicating with the MIRO AI assistant.");

export const connectionErrorLabel = () => _t("MIRO AI connection error.");

export const senderLabel = (sender) => (sender === "user" ? _t("You") : "MIRO AI");

export const exchangeCountLabel = (count) => _t("%s exchange(s)", count);

export const verifyLinkLabel = (label) => _t("Check in Odoo: %s", label);

