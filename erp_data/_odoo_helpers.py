"""Shared helpers for ORM tool modules."""

import logging
from datetime import datetime, timezone
from typing import List, Tuple

from erp_data.odoo_connector import OdooConnector
from erp_data.odoo_context import odoo_uid_ctx, odoo_api_key_ctx
from core.evidence import Evidence, EvidenceSourceType, make_evidence
from erp_data.date_utils import parse_period

logger = logging.getLogger(__name__)

connector = OdooConnector()

_cached_uid = None


def get_current_uid() -> int:
    uid = odoo_uid_ctx.get()
    if uid is not None:
        return uid
    global _cached_uid
    if _cached_uid is None:
        logger.warning(
            "get_current_uid(): no requester uid in context -- falling back "
            "to the admin uid. Expected in tests/scripts only."
        )
        _cached_uid = connector.authenticate("admin")
    return _cached_uid


def orm_evidence_scope(uid: int) -> dict:
    return {
        "execution_identity": uid,
        "read_at": datetime.now(timezone.utc).isoformat(),
    }


def normalize_client_name(client: str) -> str:
    if not client:
        return ""
    trans = str.maketrans({
        'é': '_', 'è': '_', 'ê': '_', 'ë': '_',
        'É': '_', 'È': '_', 'Ê': '_', 'Ë': '_',
        'à': '_', 'â': '_', 'À': '_', 'Â': '_',
        'î': '_', 'ï': '_', 'Î': '_', 'Ï': '_',
        'ô': '_', 'ö': '_', 'Ô': '_', 'Ö': '_',
        'ù': '_', 'û': '_', 'ü': '_', 'Ù': '_', 'Û': '_', 'Ü': '_',
        'ç': '_', 'Ç': '_'
    })
    return client.translate(trans)


def is_all_clients(client: str) -> bool:
    return not client or client.lower() in ["tous les clients", "tous", ""]


def client_label(client: str) -> str:
    return f" pour {client}" if not is_all_clients(client) else ""


def build_sale_domain(client: str, periode: str, states: List[str]) -> list:
    domain = [("state", "in", states)]
    if not is_all_clients(client):
        domain.append(("partner_id.name", "ilike", normalize_client_name(client)))
    date_range = parse_period(periode) if periode else None
    if date_range:
        domain.append(("date_order", ">=", date_range[0]))
        end_str = date_range[1] if " " in date_range[1] else date_range[1] + " 23:59:59"
        domain.append(("date_order", "<=", end_str))
    return domain


STATUT_SCOPE_LABELS = {
    "confirmees": "commandes confirmées",
    "brouillon": "devis en brouillon",
    "annulees": "commandes annulées",
    "toutes": "commandes non annulées",
}


def resolve_statut(statut: str) -> Tuple[List[str], str]:
    normalized = (statut or "").lower().strip()
    if normalized in ("confirmees", "confirmée", "confirmées", "confirmee"):
        canonical = "confirmees"
        states = ["sale", "done"]
    elif normalized in ("brouillon", "en cours", "draft"):
        canonical = "brouillon"
        states = ["draft", "sent"]
    elif normalized in ("annulees", "annulée", "annulées", "annulee", "annulé", "cancel"):
        canonical = "annulees"
        states = ["cancel"]
    else:
        canonical = "toutes"
        states = ["draft", "sent", "sale", "done"]
    return states, STATUT_SCOPE_LABELS[canonical]
