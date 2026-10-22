from full_setup import DB, get_connection


if __name__ == "__main__":
    print("Connecting to Odoo...")
    uid, pwd, models = get_connection()
    print("Connected.")

    print("Cleaning up ALL transactions (including Demo data)...")
    
    # Stock Picking
    pickings = models.execute_kw(DB, uid, pwd, 'stock.picking', 'search', [[]])
    if pickings:
        models.execute_kw(DB, uid, pwd, 'stock.picking', 'unlink', [pickings])
        print(f"  Deleted {len(pickings)} stock pickings.")

    # Account Move (Invoices)
    invoices = models.execute_kw(DB, uid, pwd, 'account.move', 'search', [[]])
    if invoices:
        # Filter for non-draft invoices
        non_draft_invoices = models.execute_kw(DB, uid, pwd, 'account.move', 'search', [[('state', '!=', 'draft')]])
        if non_draft_invoices:
            # First cancel them (required for some Odoo versions)
            models.execute_kw(DB, uid, pwd, 'account.move', 'button_cancel', [non_draft_invoices])
            # Then reset to draft
            models.execute_kw(DB, uid, pwd, 'account.move', 'button_draft', [non_draft_invoices])
        
        models.execute_kw(DB, uid, pwd, 'account.move', 'unlink', [invoices])
        print(f"  Deleted {len(invoices)} invoices.")

    # Sale Order
    sales = models.execute_kw(DB, uid, pwd, 'sale.order', 'search', [[]])
    if sales:
        non_draft_sales = models.execute_kw(DB, uid, pwd, 'sale.order', 'search', [[('state', '!=', 'draft')]])
        if non_draft_sales:
            models.execute_kw(DB, uid, pwd, 'sale.order', 'action_cancel', [non_draft_sales])
        models.execute_kw(DB, uid, pwd, 'sale.order', 'unlink', [sales])
        print(f"  Deleted {len(sales)} sales orders.")

    # Project Tasks
    tasks = models.execute_kw(DB, uid, pwd, 'project.task', 'search', [[]])
    if tasks:
        models.execute_kw(DB, uid, pwd, 'project.task', 'unlink', [tasks])
        print(f"  Deleted {len(tasks)} tasks.")

    print("Cleanup complete!")
