/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { FormController } from "@web/views/form/form_controller";

export class AccountMoveWidget extends FormController {
    static template = "account.AccountMoveWidget";

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        
        this.state = useState({
            paymentStatus: "not_paid",
            amountDue: 0,
            isLoading: false
        });

        onMounted(() => {
            this.loadPaymentStatus();
        });
    }

    async loadPaymentStatus() {
        if (!this.props.resId) return;
        
        this.state.isLoading = true;
        try {
            const result = await this.orm.read(
                "account.move",
                [this.props.resId],
                ["payment_state", "amount_residual"]
            );
            
            if (result && result.length > 0) {
                this.state.paymentStatus = result[0].payment_state;
                this.state.amountDue = result[0].amount_residual;
            }
        } catch (error) {
            console.error("Failed to load payment status", error);
        } finally {
            this.state.isLoading = false;
        }
    }

    async onRegisterPayment() {
        if (!this.props.resId) return;
        
        try {
            const action = await this.orm.call(
                "account.move",
                "action_register_payment",
                [[this.props.resId]]
            );
            
            if (action) {
                this.actionService.doAction(action, {
                    onClose: () => {
                        this.loadPaymentStatus();
                        this.notification.add(_t("Payment registered successfully"), { type: "success" });
                    }
                });
            }
        } catch (error) {
            this.notification.add(_t("Error registering payment"), { type: "danger" });
        }
    }

    get statusBadgeClass() {
        switch (this.state.paymentStatus) {
            case "paid": return "text-bg-success";
            case "in_payment": return "text-bg-info";
            case "partial": return "text-bg-warning";
            case "not_paid": return "text-bg-danger";
            case "reversed": return "text-bg-secondary";
            default: return "text-bg-light";
        }
    }
    
    get formattedStatus() {
        switch (this.state.paymentStatus) {
            case "paid": return _t("Paid");
            case "in_payment": return _t("In Payment");
            case "partial": return _t("Partially Paid");
            case "not_paid": return _t("Not Paid");
            case "reversed": return _t("Reversed");
            default: return _t("Unknown");
        }
    }
}

registry.category("views").add("account_move_widget", {
    ...FormController.components,
    Controller: AccountMoveWidget,
});
