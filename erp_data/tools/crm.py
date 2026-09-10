"""ORM tools for partner search and project ticket queries."""

from typing import List, Optional, Tuple

from langchain_core.tools import tool

from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence
from core.evidence.evidence_collector import record_evidence
from erp_data._odoo_helpers import (
    connector, get_current_uid, orm_evidence_scope,
    normalize_client_name, is_all_clients,
)


def search_partner_raw(nom: str = "", limite: int = 0) -> Tuple[str, List[Evidence]]:
    uid = get_current_uid()
    scope = orm_evidence_scope(uid)

    companies = connector.search_read(
        uid=uid, model="res.company", domain=[],
        fields=["partner_id"], context={"active_test": False},
    )
    company_partner_ids = [c["partner_id"][0] for c in companies if c.get("partner_id")]

    domain = [
        ("name", "ilike", normalize_client_name(nom)),
        ("user_ids", "=", False),
    ]
    if company_partner_ids:
        domain.append(("id", "not in", company_partner_ids))

    records = connector.search_read(
        uid=uid, model="res.partner", domain=domain,
        fields=["name", "email", "phone", "city"],
    )

    if not records:
        text = f"Aucun client trouvé avec le nom '{nom}'."
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No res.partner matches name={nom}",
            source="res.partner:search_read(name,email,phone,city)",
            value=None, scope=scope,
        )
        return text, [evidence]

    total_count = len(records)
    display_limit = limite if limite > 0 else total_count
    displayed = records[:display_limit]
    result_lines = [f"{total_count} client(s) trouvé(s) :"]
    evidences = []
    for r in displayed:
        name = r.get("name")
        email = r.get("email") or "N/A"
        phone = r.get("phone") or "N/A"
        city = r.get("city") or "N/A"
        result_lines.append(f"- {name} (Email: {email}, Tél: {phone}, Ville: {city})")
        evidences.append(make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"Contact details for partner={name}",
            source="res.partner:search_read(name,email,phone,city)",
            value={"email": email, "phone": phone, "city": city},
            scope=scope,
        ))

    if total_count > display_limit:
        result_lines.append("... (résultats tronqués, précisez la recherche ou demandez la liste complète)")
    result_lines.append("[Source: Odoo ERP - Contacts (res.partner)]")
    return "\n".join(result_lines), evidences


@tool
def search_partner(nom: str = "", limite: int = 0) -> str:
    """Search for a commercial client by name to get contact details.
    Excludes internal Odoo user/admin accounts.

    Args:
        nom: Client name or partial name. Leave empty for all commercial clients.
        limite: Max clients to display (0 for all). Default: 0.
    """
    try:
        text, evidence = search_partner_raw(nom, limite)
        record_evidence(evidence)
        return text
    except Exception as e:
        return f"Erreur lors de la recherche du client : {str(e)}"


def get_recent_tickets_raw(
    client: str = "", limite: int = 0, statut: Optional[str] = None,
) -> Tuple[str, List[Evidence]]:
    uid = get_current_uid()
    scope = orm_evidence_scope(uid)
    domain = []

    is_global = is_all_clients(client)
    if not is_global:
        domain.append(("partner_id.name", "ilike", normalize_client_name(client)))

    if statut:
        s = statut.lower()
        if "résolu" in s or "fini" in s or "done" in s:
            domain.append(("state", "=", "1_done"))
        elif "en cours" in s or "progress" in s:
            domain.append(("state", "=", "01_in_progress"))
        elif "nouveau" in s or "ouvert" in s:
            domain.append(("state", "=", "01_in_progress"))

    records = connector.search_read(
        uid=uid, model="project.task", domain=domain,
        fields=["name", "state", "create_date", "date_deadline", "partner_id"],
        order="date_deadline desc, id desc",
    )

    if not records:
        text = (
            f"Aucun ticket trouvé pour {client or 'tous les clients'} "
            f"avec le statut '{statut or 'tous'}'.\n"
            f"[Source: Odoo ERP - Module Projet (project.task)]"
        )
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No project.task matches client={client or 'all'}, statut={statut or 'all'}",
            source="project.task:search_read(state,create_date,partner_id)",
            value=None, scope=scope,
        )
        return text, [evidence]

    if not is_global:
        unique_partners = {r["partner_id"][1] for r in records if r.get("partner_id")}
        if len(unique_partners) > 1:
            text = f"AMBIGUÏTÉ : Plusieurs clients correspondent à '{client}'. Veuillez préciser lequel parmi : {', '.join(unique_partners)}."
            return text, []

    records.sort(
        key=lambda x: (x.get("date_deadline") or x.get("create_date") or "", x.get("id", 0)),
        reverse=True,
    )
    total_count = len(records)
    display_limit = limite if limite > 0 else total_count

    result_lines = [
        f"Total de tickets trouvés : {total_count}",
        f"Liste des tickets pour {client or 'tous les clients'} :",
    ]
    evidences = []
    for r in records[:display_limit]:
        state = r.get("state") or "N/A"
        date_str = (r.get("create_date") or "N/A")[:10]
        partner_name = r["partner_id"][1] if r.get("partner_id") else "N/A"
        ticket_name = r.get("name")
        result_lines.append(f"- [{state}] Client: {partner_name} | {ticket_name} (Créé le: {date_str})")
        evidences.append(make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"Ticket details for name={ticket_name}",
            source="project.task:search_read(state,create_date,partner_id)",
            value={"state": state, "partner": partner_name, "create_date": date_str},
            scope=scope,
        ))

    result_lines.append("[Source: Odoo ERP - Module Projet (project.task)]")
    return "\n".join(result_lines), evidences


@tool
def get_recent_tickets(
    client: str = "", limite: int = 0, statut: Optional[str] = None,
) -> str:
    """Get support tickets or project tasks from Odoo ERP.

    Args:
        client: Optional client name. Leave empty for all clients.
        limite: Max tickets to return (0 for all).
        statut: Optional status filter (e.g. 'résolu', 'en cours'). Leave None unless explicitly requested.
    """
    try:
        text, evidence = get_recent_tickets_raw(client, limite, statut)
        record_evidence(evidence)
        return text
    except Exception as e:
        return f"Erreur lors de la récupération des tickets : {str(e)}"
