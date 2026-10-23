{
    'name': "Mise a Disposition de Materiel",
    'version': '17.0.1.0.0',
    'category': 'Human Resources',
    'depends': ['ext_purchase_request'],
    'data': [
        'security/ir.model.access.csv',
        'views/asset_loan_views.xml',
    ],
    'installable': True,
}
