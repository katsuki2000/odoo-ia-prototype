-- Rename the business modules in an EXISTING Odoo database (psql -d odoo-dev -f this file).
-- Take a backup first: pg_dump -Fc odoo-dev > odoo-dev.before_rename.dump
-- Run with Odoo stopped, then start it with: -u miro_hr_leave_workflow (and -i <new modules>).
-- Only the modules that are installed matter; rows of never-installed modules are simply dropped.
BEGIN;

CREATE TEMP TABLE rename_map (old_name text PRIMARY KEY, new_name text NOT NULL) ON COMMIT DROP;
INSERT INTO rename_map VALUES
    ('custom_credit_note_approval_regional', 'miro_credit_note_approval_regional'),
    ('custom_credit_note_approval_vip', 'miro_credit_note_approval_vip'),
    ('custom_credit_note_approval', 'miro_credit_note_approval'),
    ('custom_credit_note_visibility_rules', 'miro_credit_note_visibility_rules'),
    ('custom_hr_leave_workflow', 'miro_hr_leave_workflow'),
    ('custom_automation_traps', 'miro_automation_traps'),
    ('custom_expense_reimbursement_indirect', 'miro_expense_reimbursement_indirect'),
    ('custom_expense_risk_base', 'acme_expense_risk_base'),
    ('custom_expense_risk_alert', 'acme_expense_risk_alert'),
    ('custom_expense_risk_score', 'acme_expense_risk_score'),
    ('custom_purchase_request', 'ext_purchase_request'),
    ('custom_asset_loan', 'asset_loan'),
    ('custom_deep_inheritance_security', 'deep_inheritance_security');

UPDATE ir_module_module m
   SET name = r.new_name
  FROM rename_map r
 WHERE m.name = r.old_name
   AND NOT EXISTS (SELECT 1 FROM ir_module_module x WHERE x.name = r.new_name);

UPDATE ir_module_module_dependency d
   SET name = r.new_name
  FROM rename_map r
 WHERE d.name = r.old_name;

UPDATE ir_model_data d
   SET module = r.new_name
  FROM rename_map r
 WHERE d.module = r.old_name;

-- Stale rows left under an old name (never installed): remove them.
DELETE FROM ir_module_module
 WHERE name IN (SELECT old_name FROM rename_map)
   AND state IN ('uninstalled', 'uninstallable');

-- Must return no row: an old name still installed means the rename conflicted.
SELECT name, state FROM ir_module_module WHERE name IN (SELECT old_name FROM rename_map);

COMMIT;
