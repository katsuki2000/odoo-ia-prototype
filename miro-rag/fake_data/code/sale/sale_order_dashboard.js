/** @odoo-module **/

import { Component, useState, onMounted, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class SaleOrderDashboard extends Component {
    static template = "sale.SaleOrderDashboard";
    
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.rpc = useService("rpc");
        
        this.state = useState({
            totalRevenue: 0,
            conversionRate: 0,
            avgOrderValue: 0,
            ordersCount: 0,
            isLoading: true,
            dateRange: "month" // 'week', 'month', 'year'
        });
        
        this.chartRef = useRef("chartCanvas");

        onMounted(() => {
            this.fetchDashboardData();
        });
    }

    async fetchDashboardData() {
        this.state.isLoading = true;
        try {
            // Using RPC for complex dashboard aggregations
            const data = await this.rpc("/web/dataset/call_kw/sale.order/get_dashboard_data", {
                model: "sale.order",
                method: "get_dashboard_data",
                args: [[]],
                kwargs: { date_range: this.state.dateRange }
            });
            
            if (data) {
                this.state.totalRevenue = data.total_revenue || 0;
                this.state.conversionRate = data.conversion_rate || 0;
                this.state.avgOrderValue = data.avg_order_value || 0;
                this.state.ordersCount = data.orders_count || 0;
                
                if (data.chart_data) {
                    this.renderChart(data.chart_data);
                }
            }
        } catch (error) {
            console.error("Failed to fetch sale dashboard data", error);
        } finally {
            this.state.isLoading = false;
        }
    }

    async setDateRange(range) {
        this.state.dateRange = range;
        await this.fetchDashboardData();
    }

    renderChart(chartData) {
        if (!this.chartRef.el) return;
        
        // Pseudo chart rendering logic, normally would use Chart.js
        // that Odoo bundles
        console.log("Rendering chart with data:", chartData);
        const ctx = this.chartRef.el.getContext("2d");
        ctx.clearRect(0, 0, this.chartRef.el.width, this.chartRef.el.height);
        ctx.fillStyle = "#71639e"; // Odoo primary color
        
        // Simple bar chart visualization
        const barWidth = 40;
        const spacing = 10;
        const maxVal = Math.max(...chartData.map(d => d.value));
        
        chartData.forEach((point, index) => {
            const barHeight = (point.value / maxVal) * 150;
            const x = index * (barWidth + spacing) + 20;
            const y = 180 - barHeight;
            ctx.fillRect(x, y, barWidth, barHeight);
        });
    }

    openOrdersList() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: _t("Sales Orders"),
            res_model: "sale.order",
            views: [[false, "list"], [false, "form"]],
            domain: [["state", "in", ["sale", "done"]]],
        });
    }

    formatCurrency(value) {
        // Simplified formatting
        return new Intl.NumberFormat(undefined, { 
            style: 'currency', 
            currency: 'EUR' 
        }).format(value);
    }
}

registry.category("actions").add("sale_dashboard_action", SaleOrderDashboard);
