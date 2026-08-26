{
    'name': "Pieges - Combinaison des ir.rule (global vs groupe)",
    'version': '17.0.1.0.0',
    'category': 'Accounting',
    'depends': ['custom_credit_note_approval'],
    'data': [
        'security/security_groups.xml',
        'security/ir_rule_layered.xml',
    ],
    'installable': True,
}
