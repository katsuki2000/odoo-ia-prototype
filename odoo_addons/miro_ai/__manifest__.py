# -*- coding: utf-8 -*-
{
    'name': 'MIRO AI Assistant',
    'version': '17.0.1.0.2',
    'category': 'Productivity/AI',
    'summary': 'Intelligent AI Assistant for Odoo (RAG + ORM)',
    'description': """
MIRO AI Assistant - RAG and LangChain integration for Odoo 17
==============================================================

Features:
- API connection settings towards FastAPI / ChromaDB
- Activation of the skill scope (Sales, Stock, Accounting, Tickets)
- Chat interface and request audit log
    """,
    'author': 'MIRO Team',
    'website': 'https://github.com/katsuki2000/odoo-ia-prototype',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'data': [
        'security/miro_ai_security.xml',
        'security/ir.model.access.csv',
        'views/miro_ai_settings_views.xml',
        'views/miro_ai_log_views.xml',
        'views/miro_ai_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'miro_ai/static/src/css/miro_ai.css',
            'miro_ai/static/src/js/miro_ai_labels.js',
            'miro_ai/static/src/js/miro_ai.js',
            'miro_ai/static/src/xml/miro_ai_assistant.xml',
        ],
    },
    'application': True,
    'installable': True,
    'auto_install': False,
}
