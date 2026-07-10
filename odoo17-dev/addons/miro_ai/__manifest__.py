# -*- coding: utf-8 -*-
{
    'name': 'MIRO AI Assistant',
    'version': '17.0.1.0.0',
    'category': 'Productivity/AI',
    'summary': 'Assistant IA Intelligent pour Odoo (RAG + ORM)',
    'description': """
MIRO AI Assistant - Intégration RAG et LangChain pour Odoo 17
=============================================================

Fonctionnalités :
- Paramétrage de la connexion API vers FastAPI / ChromaDB
- Activation du périmètre d'action (Ventes, Stocks, Comptabilité, Tickets)
- Interface de chat et journal d'audit des requêtes
    """,
    'author': 'MIRO Team',
    'website': 'https://github.com/katsuki2000/odoo-ia-prototype',
    'license': 'LGPL-3',
    'depends': ['base'],
    'data': [
        'security/miro_ai_security.xml',
        'security/ir.model.access.csv',
        'views/miro_ai_settings_views.xml',
        'views/miro_ai_menus.xml',
    ],
    'application': True,
    'installable': True,
    'auto_install': False,
}
