# -*- coding: utf-8 -*-
{
    'name': 'MIRO AI Assistant (Discuss Chat)',
    'version': '17.0.1.0.0',
    'category': 'Productivity/AI',
    'summary': 'Assistant IA conversationnel dans Odoo Discuss (0 JS)',
    'description': """
MIRO AI Discuss Integration
===========================
Permet d'interagir avec l'Assistant IA directement dans l'application Discuss d'Odoo 17 :
- Chat direct 1-à-1 avec le bot partenaire "Assistant IA"
- Mention @Assistant IA dans n'importe quel canal ou groupe de discussion
- Formatage HTML automatique des réponses (Markdown, tableaux GFM, blocs de code, listes, liens)
- Sécurité : jetons JWT éphémères et clés API par utilisateur (respect strict des droits Odoo)
- Journalisation complète dans l'audit log MIRO AI (miro.ai.log)
- Architecture 100% Python côté backend (0 ligne de JavaScript)
    """,
    'author': 'MIRO Team',
    'website': 'https://github.com/katsuki2000/odoo-ia-prototype',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'miro_ai',
    ],
    'data': [
        'data/bot_partner_data.xml',
        'views/discuss_channel_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
