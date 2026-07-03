# -*- coding: utf-8 -*-
"""
ai_document.py
==============
Tracks every document (PDF, Knowledge article, Helpdesk ticket, code file)
that has been ingested into the ChromaDB vector store.
"""
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class AiDocument(models.Model):
    _name = 'ai.document'
    _description = 'AI ERP — Document indexé'
    _rec_name = 'name'
    _order = 'ingestion_date desc, id'

    # ── Identity ────────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Titre / Nom du fichier',
        required=True,
        index=True,
    )
    doc_type = fields.Selection(
        [
            ('pdf', 'PDF'),
            ('wiki', 'Article Knowledge (Wiki)'),
            ('ticket', 'Ticket Helpdesk'),
            ('code_python', 'Code Python'),
            ('code_xml', 'Code XML'),
            ('other', 'Autre'),
        ],
        string='Type de document',
        required=True,
        default='pdf',
        index=True,
    )

    # ── Source references ───────────────────────────────────────────────────────
    source_path = fields.Char(
        string='Chemin / URL source',
        help=(
            'Pour les PDFs : chemin absolu sur le serveur.\n'
            'Pour les articles Knowledge : ID interne.\n'
            'Pour le code : chemin relatif au module.'
        ),
    )
    source_ref = fields.Char(
        string='Référence externe',
        help='Ticket ID, article ID, ou identifiant externe.',
    )

    # ── Ingestion metadata ──────────────────────────────────────────────────────
    ingestion_date = fields.Datetime(
        string='Date d\'ingestion',
        default=fields.Datetime.now,
        readonly=True,
        index=True,
    )
    last_update = fields.Datetime(
        string='Dernière mise à jour',
        readonly=True,
    )
    ingestion_status = fields.Selection(
        [
            ('pending', 'En attente'),
            ('processing', 'En cours'),
            ('done', 'Indexé'),
            ('error', 'Erreur'),
            ('outdated', 'Obsolète'),
        ],
        string='Statut',
        default='pending',
        required=True,
        index=True,
    )
    ingestion_error = fields.Text(
        string='Erreur d\'ingestion',
        readonly=True,
    )

    # ── Vector store references ─────────────────────────────────────────────────
    collection_name = fields.Char(
        string='Collection ChromaDB',
        readonly=True,
    )
    chunk_count = fields.Integer(
        string='Nombre de chunks indexés',
        readonly=True,
        default=0,
    )
    chroma_ids = fields.Text(
        string='IDs ChromaDB (JSON)',
        readonly=True,
        help='Liste JSON des IDs des vecteurs stockés dans ChromaDB.',
    )

    # ── Content metadata ────────────────────────────────────────────────────────
    language = fields.Selection(
        [('fr', 'Français'), ('en', 'Anglais'), ('auto', 'Détection auto')],
        string='Langue',
        default='auto',
    )
    description = fields.Text(string='Description / Notes')
    odoo_version = fields.Char(
        string='Version Odoo',
        default='17.0',
        help='Pour extensibilité future multi-version.',
    )

    # ── Attachment (PDF upload) ─────────────────────────────────────────────────
    attachment_id = fields.Many2one(
        'ir.attachment',
        string='Pièce jointe',
        help='Pièce jointe PDF à indexer.',
        ondelete='set null',
    )

    # ── Actions ─────────────────────────────────────────────────────────────────
    def action_ingest(self):
        """Trigger ingestion of this document into ChromaDB."""
        for rec in self:
            if rec.ingestion_status == 'processing':
                raise UserError(
                    f'Le document « {rec.name} » est déjà en cours d\'indexation.'
                )
            rec.write({'ingestion_status': 'processing', 'ingestion_error': False})
            try:
                from ..services.ingestion import IngestionService
                svc = IngestionService(rec.env)
                result = svc.ingest_document(rec)
                rec.write({
                    'ingestion_status': 'done',
                    'last_update': fields.Datetime.now(),
                    'chunk_count': result.get('chunk_count', 0),
                    'chroma_ids': result.get('chroma_ids_json', '[]'),
                    'collection_name': result.get('collection_name', ''),
                })
            except Exception as exc:
                _logger.exception('Erreur lors de l\'ingestion de %s', rec.name)
                rec.write({
                    'ingestion_status': 'error',
                    'ingestion_error': str(exc),
                })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Ingestion terminée',
                'message': f'{len(self)} document(s) traité(s).',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_delete_from_vectorstore(self):
        """Remove this document's vectors from ChromaDB."""
        self.ensure_one()
        if self.ingestion_status != 'done':
            raise UserError('Ce document n\'a pas encore été indexé.')
        try:
            from ..services.vector_store import VectorStoreService
            config = self.env['ai.config'].get_active_config()
            svc = VectorStoreService(config)
            import json
            ids = json.loads(self.chroma_ids or '[]')
            if ids:
                svc.delete_by_ids(self.collection_name, ids)
            self.write({
                'ingestion_status': 'pending',
                'chunk_count': 0,
                'chroma_ids': '[]',
            })
        except Exception as exc:
            _logger.exception('Erreur lors de la suppression des vecteurs')
            raise UserError(f'Erreur : {exc}') from exc

    @api.model
    def action_bulk_ingest_pending(self):
        """Ingest all documents with status = pending."""
        pending = self.search([('ingestion_status', '=', 'pending')])
        if not pending:
            return
        pending.action_ingest()
