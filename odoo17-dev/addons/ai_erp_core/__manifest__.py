# -*- coding: utf-8 -*-
{
    'name': 'AI ERP Core — Private AI Assistant',
    'version': '17.0.1.0.0',
    'category': 'Tools/AI',
    'summary': (
        'Private RAG-based AI assistant for Odoo 17 — powered by Ollama. '
        'Answers questions over documents, source code, and live ERP data '
        'with mandatory source citations.'
    ),
    'description': """
AI ERP Core
===========

A fully private, on-premise AI assistant embedded in Odoo 17.

Architecture
------------
- **Document RAG** : ingest PDFs, Odoo Knowledge articles, Helpdesk tickets
- **Code RAG**     : ingest custom Python/XML modules with file + line citations
- **ORM Tools**    : predefined safe queries on live Odoo data (no free SQL)
- **Router**       : agentic LLM decides which pipeline to invoke
- **Vector store** : ChromaDB (local)
- **LLM backend**  : Ollama (Hermes 3 / Mistral 7B / Phi-3.5 Mini)

Every answer includes mandatory source citations (file, page, or ORM field).
    """,
    'author': 'MIRO KE',
    'website': '',
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/ai_config_views.xml',
        'views/ai_document_views.xml',
        'views/ai_conversation_views.xml',
        'views/menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ai_erp_core/static/src/js/chat_widget.js',
            'ai_erp_core/static/src/css/chat_widget.css',
            'ai_erp_core/static/src/xml/chat_widget.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
