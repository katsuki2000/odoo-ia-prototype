# Relecture des cas de droits d'acces (brouillon)

192 cas, 48 lignes. A = autorise, D = refuse (verite fournie par `check_access_rights` d'Odoo).

A relire : coherence avec ce que vous savez d'Odoo (ex. un utilisateur portail ne peut ni ecrire ni creer sur un devis), pas avec les reponses du systeme.

| Instance | Utilisateur | Modele | read | write | create | unlink |
| --- | --- | --- | --- | --- | --- | --- |
| accounting_fr | base.demo_user0 | account.move | A | D | D | D |
| accounting_fr | base.user_admin | account.move | A | A | A | A |
| accounting_fr | base.user_demo | account.move | A | A | A | A |
| crm_project_web | base.demo_user0 | account.move | A | D | D | D |
| crm_project_web | base.demo_user0 | crm.lead | D | D | D | D |
| crm_project_web | base.demo_user0 | project.task | A | D | D | D |
| crm_project_web | base.demo_user0 | sale.order | A | D | D | D |
| crm_project_web | base.user_admin | account.move | A | A | A | A |
| crm_project_web | base.user_admin | crm.lead | A | A | A | A |
| crm_project_web | base.user_admin | project.task | A | A | A | A |
| crm_project_web | base.user_admin | sale.order | A | A | A | A |
| crm_project_web | base.user_demo | account.move | A | A | A | A |
| crm_project_web | base.user_demo | crm.lead | A | A | A | D |
| crm_project_web | base.user_demo | project.task | A | A | A | A |
| crm_project_web | base.user_demo | sale.order | A | A | A | D |
| hr_suite | base.demo_user0 | account.move | A | D | D | D |
| hr_suite | base.demo_user0 | hr.employee | D | D | D | D |
| hr_suite | base.demo_user0 | hr.leave | D | D | D | D |
| hr_suite | base.user_admin | account.move | A | A | A | A |
| hr_suite | base.user_admin | hr.employee | A | A | A | A |
| hr_suite | base.user_admin | hr.leave | A | A | A | A |
| hr_suite | base.user_demo | account.move | A | A | A | A |
| hr_suite | base.user_demo | hr.employee | A | A | A | A |
| hr_suite | base.user_demo | hr.leave | A | A | A | A |
| oca_sale_workflow | base.demo_user0 | account.move | A | D | D | D |
| oca_sale_workflow | base.demo_user0 | sale.order | A | D | D | D |
| oca_sale_workflow | base.demo_user0 | stock.picking | A | D | D | D |
| oca_sale_workflow | base.user_admin | account.move | A | A | A | A |
| oca_sale_workflow | base.user_admin | sale.order | A | A | A | A |
| oca_sale_workflow | base.user_admin | stock.picking | A | A | A | A |
| oca_sale_workflow | base.user_demo | account.move | A | A | A | A |
| oca_sale_workflow | base.user_demo | sale.order | A | A | A | D |
| oca_sale_workflow | base.user_demo | stock.picking | A | A | A | A |
| oca_server_tools | base.demo_user0 | project.task | A | D | D | D |
| oca_server_tools | base.user_admin | project.task | A | A | A | A |
| oca_server_tools | base.user_demo | project.task | A | A | A | A |
| sales_purchase_stock | base.demo_user0 | account.move | A | D | D | D |
| sales_purchase_stock | base.demo_user0 | purchase.order | A | D | D | D |
| sales_purchase_stock | base.demo_user0 | sale.order | A | D | D | D |
| sales_purchase_stock | base.demo_user0 | stock.picking | A | D | D | D |
| sales_purchase_stock | base.user_admin | account.move | A | A | A | A |
| sales_purchase_stock | base.user_admin | purchase.order | A | A | A | A |
| sales_purchase_stock | base.user_admin | sale.order | A | A | A | A |
| sales_purchase_stock | base.user_admin | stock.picking | A | A | A | A |
| sales_purchase_stock | base.user_demo | account.move | A | A | A | A |
| sales_purchase_stock | base.user_demo | purchase.order | A | A | A | A |
| sales_purchase_stock | base.user_demo | sale.order | A | A | A | D |
| sales_purchase_stock | base.user_demo | stock.picking | A | A | A | A |
