/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class StockBarcodeScanner extends Component {
    static template = "stock.BarcodeScanner";
    
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.barcodeService = useService("barcode");
        
        this.state = useState({
            scannedLines: [],
            currentPickingId: this.props.pickingId || null,
            scanMode: "product", // 'product', 'location', 'package'
            isScanning: false,
            lastError: null
        });

        this.onBarcodeScanned = this.handleBarcodeScan.bind(this);

        onMounted(() => {
            // Subscribe to global barcode events
            this.barcodeService.bus.addEventListener("barcode_scanned", this.onBarcodeScanned);
            if (this.state.currentPickingId) {
                this.loadPickingLines();
            }
        });

        onWillUnmount(() => {
            // Clean up event listener
            this.barcodeService.bus.removeEventListener("barcode_scanned", this.onBarcodeScanned);
        });
    }

    async loadPickingLines() {
        try {
            const lines = await this.orm.searchRead(
                "stock.move.line",
                [["picking_id", "=", this.state.currentPickingId]],
                ["product_id", "qty_done", "product_uom_qty", "location_id", "location_dest_id", "lot_id"]
            );
            this.state.scannedLines = lines;
        } catch (error) {
            console.error("Could not load picking lines", error);
            this.state.lastError = _t("Failed to load picking lines.");
        }
    }

    async handleBarcodeScan(event) {
        const barcode = event.detail.barcode;
        this.state.isScanning = true;
        this.state.lastError = null;
        
        try {
            // Play a scanning sound
            this.playSound("scan");
            
            // Call server to process barcode
            const result = await this.orm.call(
                "stock.picking",
                "process_barcode",
                [[this.state.currentPickingId]],
                { barcode: barcode, mode: this.state.scanMode }
            );
            
            if (result.success) {
                this.notification.add(_t("Product scanned: %s", result.product_name), { type: "success" });
                await this.loadPickingLines(); // Refresh lines
            } else {
                this.playSound("error");
                this.state.lastError = result.error_message || _t("Invalid barcode.");
                this.notification.add(this.state.lastError, { type: "danger" });
            }
        } catch (error) {
            this.playSound("error");
            this.state.lastError = _t("Server error during scan.");
            console.error(error);
        } finally {
            this.state.isScanning = false;
        }
    }

    playSound(type) {
        // In a real module, these would point to actual audio files in static/src/audio/
        const src = type === "scan" ? "/web/static/src/audio/barcode_scan.mp3" : "/web/static/src/audio/error.mp3";
        const audio = new Audio(src);
        audio.play().catch(e => console.log("Audio play prevented", e));
    }

    changeScanMode(mode) {
        this.state.scanMode = mode;
        this.notification.add(_t("Scan mode changed to: %s", mode), { type: "info" });
    }

    async validatePicking() {
        try {
            const result = await this.orm.call(
                "stock.picking",
                "button_validate",
                [[this.state.currentPickingId]]
            );
            
            if (result === true || (result && result.type)) {
                this.notification.add(_t("Picking validated!"), { type: "success" });
                // If it returns an action (like a backorder wizard), we might need to handle it
                // using actionService.doAction(result)
            }
        } catch (error) {
            this.notification.add(_t("Error validating picking"), { type: "danger" });
        }
    }
}

registry.category("actions").add("stock_barcode_client_action", StockBarcodeScanner);
