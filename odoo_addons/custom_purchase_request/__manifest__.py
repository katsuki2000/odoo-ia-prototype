{
    'name': "Demande d'Achat Interne",
    'version': '17.0.1.0.0',
    'category': 'Purchases',
    'depends': ['purchase'],
    'data': [
        'security/ir.model.access.csv',
        'views/purchase_request_views.xml',
    ],
    'installable': True,
}
