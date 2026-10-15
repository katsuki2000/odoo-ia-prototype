# -*- coding: utf-8 -*-
"""models/miro_ai_bot.py
======================
Service Bot MIRO AI pour l'intégration Odoo Discuss (0 JS).

Gère :
- L'interception des messages privés ou mentions @Assistant IA
- Le nettoyage du texte utilisateur (extraction HTML -> texte brut, suppression des mentions)
- L'authentification sécurisée (clé API éphémère par utilisateur + JWT HS256)
- L'interrogation du backend FastAPI / RAG (/api/v1/ask)
- L'enregistrement dans le journal d'audit (miro.ai.log)
- La conversion Markdown -> HTML riche (tableaux GFM, blocs de code, listes, titres)
- La publication de la réponse en temps réel via le bus Odoo Discuss
"""
import base64
import hashlib
import hmac
import html
import json
import logging
import re
import time
from urllib.parse import urlparse

from markupsafe import Markup

try:
    from odoo import api, models, _
    from odoo.exceptions import UserError
    from odoo.tools import html2plaintext
except ImportError:
    # Permet l'exécution des tests unitaires purs hors serveur Odoo
    class UserError(Exception):
        pass

    class _MockModels:
        AbstractModel = object
        Model = object

    models = _MockModels()

    class _MockApi:
        @staticmethod
        def model(f):
            return f

    api = _MockApi()
    _ = lambda s: s

    def html2plaintext(html_str):
        return re.sub(r'<[^>]+>', '', html_str or '')

try:
    from odoo.addons.miro_ai.controllers.backend_client import (
        post_with_failover,
        BackendError,
        BackendTimeout,
        BackendUnreachable,
    )
except ImportError:
    import requests

    class BackendError(Exception):
        pass

    class BackendUnreachable(BackendError):
        pass

    class BackendTimeout(BackendError):
        pass

    def post_with_failover(candidate_urls, path, headers, payload, timeout):
        last_error = None
        for url in candidate_urls:
            try:
                return requests.post(f"{url}{path}", headers=headers, json=payload, timeout=timeout), url
            except requests.exceptions.ConnectionError as err:
                last_error = err
            except requests.exceptions.Timeout as err:
                raise BackendTimeout(f"{url} n'a pas répondu en {timeout} s") from err
        raise BackendUnreachable("Serveur RAG inaccessible") from last_error


_logger = logging.getLogger(__name__)

_BULLET_PREFIX_RE = re.compile(r'^[-*]\s+')
_NUMBERED_PREFIX_RE = re.compile(r'^\d+\.\s+')


def generate_jwt_token(payload_dict, secret_key):
    """Génère un jeton JWT HS256 valide en pur Python standard."""
    header = {"alg": "HS256", "typ": "JWT"}

    def b64url_encode(data_bytes):
        return base64.urlsafe_b64encode(data_bytes).rstrip(b'=').decode('ascii')

    encoded_header = b64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8'))
    encoded_payload = b64url_encode(json.dumps(payload_dict, separators=(',', ':')).encode('utf-8'))

    signing_input = f"{encoded_header}.{encoded_payload}".encode('ascii')
    signature = hmac.new(secret_key.encode('utf-8'), signing_input, hashlib.sha256).digest()
    encoded_signature = b64url_encode(signature)

    return f"{encoded_header}.{encoded_payload}.{encoded_signature}"


def markdown_to_html(text: str) -> str:
    """Échappe le texte brut pour Discuss et conserve les retours à la ligne."""
    if not text:
        return ""
    return html.escape(text).replace("\\n", "<br/>")



class MiroAiBot(models.AbstractModel):
    _name = 'miro.ai.bot'
    _description = 'Service Bot MIRO AI pour Odoo Discuss'

    def _get_bot_partner_id(self):
        """Retourne l'ID du res.partner associé au bot Assistant IA."""
        return self.env['ir.model.data']._xmlid_to_res_id('miro_ai_discuss.partner_miro_ai_bot')

    def _clean_incoming_text(self, body_html: str) -> str:
        """Extrait le texte brut d'un message Odoo en nettoyant les balises de mention."""
        if not body_html:
            return ""
        # 1. Supprime les balises d'ancrage créées par Odoo lors d'une mention de partenaire
        clean_html = re.sub(r'<a[^>]*data-oe-model=["\']res\.partner["\'][^>]*>.*?</a>', '', body_html)
        # 2. Conversion HTML vers texte brut standard Odoo
        text = html2plaintext(clean_html).strip()
        # 3. Supprime les éventuelles mentions textuelles résiduelles (@Assistant IA, @MIRO AI, etc.)
        text = re.sub(r'@(Assistant IA|MIRO AI|Miro AI|Assistant)\b', '', text, flags=re.IGNORECASE).strip()
        return text

    def _call_rag_backend(self, question: str, user, channel_id: int) -> dict:
        """Interroge le serveur FastAPI RAG avec jeton JWT et clé API éphémère."""
        settings = self.env['miro.ai.settings'].sudo().get_active_settings()
        api_url = settings.api_url.rstrip('/') if settings and settings.api_url else "http://127.0.0.1:8000"
        try:
            secret_key = settings.get_signing_secret()
        except UserError as err:
            return {'answer': f"⚠️ {err.args[0]}", 'sources': []}
        timeout = settings.request_timeout or 120

        uid = user.id
        company_id = self.env.company.id
        groups = [g.id for g in user.groups_id]
        effective_session = f"discuss_channel_{channel_id}"

        # Clé API éphémère self-service pour l'utilisateur
        apikeys_model = self.env['res.users.apikeys']
        key_name = f"MIRO AI Discuss - {effective_session}_{int(time.time())}"
        rpc_api_key = None
        apikey_record = None
        try:
            rpc_api_key = apikeys_model.with_user(user)._generate(None, key_name)
            apikey_record = apikeys_model.sudo().search([
                ('user_id', '=', uid),
                ('name', '=', key_name),
            ], order='create_date desc', limit=1)
            self.env.cr.commit()
        except Exception as key_err:
            rpc_api_key = None
            apikey_record = None
            _logger.warning("MIRO AI Discuss: échec de génération de la clé API pour uid=%s: %s", uid, key_err)

        # Génération du JWT HS256
        jwt_payload = {
            "sub": str(uid),
            "uid": uid,
            "login": user.login,
            "company_id": company_id,
            "groups": groups,
            "api_key": rpc_api_key,
            "is_admin": user.has_group('base.group_system'),
            "exp": int(time.time()) + 300
        }
        jwt_token = generate_jwt_token(jwt_payload, secret_key)

        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "question": question,
            "session_id": effective_session,
            "user_uid": uid,
            "company_id": company_id,
            "groups": groups,
        }

        candidate_urls = [api_url]
        if api_url in ("http://miro_rag:8000", "http://miro_rag:8000/"):
            candidate_urls.append("http://127.0.0.1:8000")
        elif api_url in ("http://127.0.0.1:8000", "http://127.0.0.1:8000/"):
            candidate_urls.append("http://localhost:8000")

        start_time = time.time()
        resp = None
        backend_error = None
        try:
            resp, _ = post_with_failover(candidate_urls, "/api/v1/ask", headers, payload, timeout)
        except BackendError as err:
            backend_error = err

        try:
            if resp is not None and resp.status_code == 200:
                elapsed_ms = int((time.time() - start_time) * 1000)
                data = resp.json()
                answer_str = data.get('answer', 'Aucune réponse renvoyée par le serveur RAG.')
                sources_list = data.get('sources', [])
                metadata_dict = {
                    'route': data.get('route'),
                    'confidence': data.get('confidence', 1.0),
                    'evidence_status': data.get('evidence_status'),
                    'resolved_concept': data.get('resolved_concept'),
                    'omitted_for_authorization': data.get('omitted_for_authorization', []),
                    'investigation_plan': data.get('investigation_plan'),
                    'channel_id': channel_id,
                }
                try:
                    self.env['miro.ai.log'].sudo().log_query(
                        question=question,
                        answer=answer_str,
                        session_id=effective_session,
                        response_time_ms=elapsed_ms,
                        sources=sources_list,
                        state='success',
                        metadata=metadata_dict
                    )
                except Exception as log_err:
                    _logger.warning("MIRO AI Discuss: échec du journal log_query: %s", log_err)

                return {'answer': answer_str, 'sources': sources_list}
            elif resp is not None:
                elapsed_ms = int((time.time() - start_time) * 1000)
                err_msg = (
                    f"⚠️ Erreur du serveur RAG (HTTP {resp.status_code}). "
                    "Veuillez vérifier que le service FastAPI est actif."
                )
                try:
                    self.env['miro.ai.log'].sudo().log_query(
                        question=question,
                        answer=err_msg,
                        session_id=effective_session,
                        response_time_ms=elapsed_ms,
                        sources=[],
                        state='error'
                    )
                except Exception as log_err:
                    _logger.warning("MIRO AI Discuss: échec log_query: %s", log_err)
                return {'answer': err_msg, 'sources': []}
            else:
                raise backend_error or Exception("Erreur inconnue de connexion au backend RAG")
        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            _logger.exception("MIRO AI Discuss: échec de l'appel backend: %s", e)
            if isinstance(e, BackendTimeout):
                err_msg = (
                    f"⏱️ Le serveur d'intelligence artificielle ({api_url}) n'a pas répondu "
                    f"dans le délai imparti ({timeout} s). Veuillez réessayer ou ajuster le délai."
                )
            else:
                err_msg = (
                    f"⚠️ Impossible de contacter le serveur d'intelligence artificielle ({api_url}). "
                    "Vérifiez que le backend FastAPI est bien démarré."
                )
            try:
                self.env['miro.ai.log'].sudo().log_query(
                    question=question,
                    answer=err_msg,
                    session_id=effective_session,
                    response_time_ms=elapsed_ms,
                    sources=[],
                    state='error'
                )
            except Exception as log_err:
                _logger.warning("MIRO AI Discuss: échec log_query: %s", log_err)
            return {'answer': err_msg, 'sources': []}
        finally:
            if apikey_record:
                try:
                    apikey_record.sudo()._remove()
                    self.env.cr.commit()
                except Exception as revoke_err:
                    _logger.warning("MIRO AI Discuss: échec de révocation de la clé API pour uid=%s: %s", uid, revoke_err)
                    try:
                        self.env.cr.rollback()
                    except Exception as rollback_err:
                        _logger.warning("MIRO AI Discuss: échec du rollback après la révocation pour uid=%s: %s", uid, rollback_err)

    def _handle_channel_message(self, channel, message, msg_vals):
        """Intercepte un message posté dans un canal Discuss et répond si le bot est sollicité."""
        if len(channel) != 1:
            return

        bot_partner_id = self._get_bot_partner_id()
        if not bot_partner_id:
            return

        # Ignorer les messages générés par le bot lui-même pour éviter toute boucle infinie
        if message.author_id.id == bot_partner_id or msg_vals.get('author_id') == bot_partner_id:
            return

        # Traiter uniquement les commentaires
        if message.message_type != 'comment' and msg_vals.get('message_type') != 'comment':
            return

        # Déterminer si le bot est destinataire : chat privé 1-à-1 OU mention directe
        is_private_chat = (
            channel.channel_type == 'chat'
            and bot_partner_id in channel.with_context(active_test=False).channel_partner_ids.ids
        )
        pinged_partner_ids = msg_vals.get('partner_ids') or message.partner_ids.ids or []
        is_pinged = bot_partner_id in pinged_partner_ids

        if not is_private_chat and not is_pinged:
            return

        # Déterminer l'utilisateur demandeur
        user = message.create_uid or self.env.user
        if not user or user._is_public():
            return

        # Extraction et nettoyage du texte de la question
        question = self._clean_incoming_text(message.body)
        if not question:
            # Message vide ou mention seule : message d'accueil
            welcome_text = _(
                "Bonjour ! Je suis votre Assistant IA. Posez-moi une question sur vos ventes, "
                "vos stocks, votre comptabilité ou le paramétrage d'Odoo !"
            )
            answer_html = f"<p>{welcome_text}</p>"
        else:
            # Appel du backend RAG
            result = self._call_rag_backend(question=question, user=user, channel_id=channel.id)
            raw_answer = result.get('answer', '')
            answer_html = markdown_to_html(raw_answer)

        # Construction du message de réponse
        reply_vals = {
            'body': Markup(answer_html),
            'author_id': bot_partner_id,
            'message_type': 'comment',
            'subtype_xmlid': 'mail.mt_comment',
        }

        # Dans un canal public ou de groupe, notifier l'auteur en réponse
        if channel.channel_type != 'chat':
            reply_vals['partner_ids'] = [user.partner_id.id]
            reply_vals['parent_id'] = message.id

        # Publication de la réponse
        channel.with_context(mail_create_nosubscribe=True).sudo().message_post(**reply_vals)
