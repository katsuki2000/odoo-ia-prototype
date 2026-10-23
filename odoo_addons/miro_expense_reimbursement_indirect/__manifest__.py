{
    'name': 'Custom Expense Reimbursement Indirect (Adversarial Test 9)',
    'version': '17.0.1.0.0',
    'category': 'Human Resources',
    'summary': "Module adversarial — gate de validation non-nommable, "
               "sans mécanisme Odoo standard (ni groupe, ni ir.rule, "
               "ni sudo(), ni donnée ir.actions.server)",
    'author': 'Jeu de test adversarial',
    'depends': ['base'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'application': False,
}
