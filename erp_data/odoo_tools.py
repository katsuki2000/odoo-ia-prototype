"""
LangChain @tool definitions for Odoo XML-RPC operations.
These tools are exposed to the AI for function calling.
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
import logging
from langchain_core.tools import tool
from erp_data.odoo_connector import OdooConnector
from tools.date_utils import parse_period
from core.evidence import Evidence, EvidenceSourceType, make_evidence
import contextvars

logger = logging.getLogger(__name__)

# Instantiate the connector.
connector = OdooConnector()

odoo_uid_ctx = contextvars.ContextVar('odoo_uid', default=None)
odoo_api_key_ctx = contextvars.ContextVar('odoo_api_key', default=None)

_cached_uid = None

def _get_current_uid() -> int:
    """
    Return the requester's real Odoo uid, propagated via odoo_uid_ctx from
    query_graph()'s `uid` param (itself taken from the trusted JWT on every
    real API request -- see api/main.py::ask_question_v1). That contextvar
    is always set on the real request path, so this admin fallback should
    only ever be hit from tests, scripts, or other out-of-request usage --
    never silently, hence the loud warning: a silent admin fallback is
    exactly the kind of mock that made every ERP query run with admin
    rights regardless of who actually asked.
    """
    uid = odoo_uid_ctx.get()
    if uid is not None:
        return uid

    global _cached_uid
    if _cached_uid is None:
        logger.warning(
            "_get_current_uid(): no requester uid in context -- falling back "
            "to the admin uid. This is expected in tests/scripts, but must "
            "never happen on a real API request (it would mean the JWT uid "
            "was not propagated)."
        )
        _cached_uid = connector.authenticate("admin")
    return _cached_uid

def _orm_evidence_scope(uid: int) -> dict:
    """
    B0 pilot (todo/contexte.txt sections 426-428): canonical scope shared by
    every ORM tool's Evidence. execution_identity is the real requester uid
    (see _get_current_uid's docstring) -- the identity Odoo's own ir.rule/
    ACL enforcement actually used for this read, not a decorative label.
    company_id is deliberately omitted here: OdooConnector does not
    currently pass or receive an explicit company scope (Odoo resolves the
    active company server-side from the uid's session) -- adding a
    fabricated company_id would misrepresent what this tool actually knows.
    """
    return {
        "execution_identity": uid,
        "read_at": datetime.now(timezone.utc).isoformat(),
    }


def _normalize_client_name(client: str) -> str:
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

def get_total_sales_raw(client: str = "", periode: str = "", statut: str = "toutes") -> Tuple[str, Evidence]:
    """
    Execute get_total_sales and return both the display string and the
    structured Evidence (B0 pilot, todo/contexte.txt sections 426-428).
    Exposed separately from the @tool wrapper so a future Evidence Builder
    (B2/B3) can call it directly and reuse the result object, the same
    pattern already used on the CI side by ci_agent_tools.evaluate_rules_raw.
    """
    statut_normalized = statut.lower().strip()

    if statut_normalized in ("confirmees", "confirmée", "confirmées", "confirmee"):
        states = ["sale", "done"]
    elif statut_normalized in ("brouillon", "en cours", "draft"):
        states = ["draft", "sent"]
    else:
        states = ["draft", "sent", "sale", "done"]

    domain = [("state", "in", states)]

    if client and client.lower() not in ["tous les clients", "tous", ""]:
        domain.append(("partner_id.name", "ilike", _normalize_client_name(client)))

    date_range = parse_period(periode) if periode else None
    if date_range:
        domain.append(("date_order", ">=", date_range[0]))
        end_str = date_range[1] if " " in date_range[1] else date_range[1] + " 23:59:59"
        domain.append(("date_order", "<=", end_str))

    uid = _get_current_uid()
    scope = _orm_evidence_scope(uid)
    client_label = f" pour {client}" if client and client.lower() not in ["tous les clients", "tous", ""] else ""

    results = connector.read_group(
        uid=uid,
        model="sale.order",
        domain=domain,
        fields=["amount_total:sum"],
        groupby=[],
    )

    if not results or not results[0].get("amount_total"):
        text = f"Aucune vente trouvée{client_label} (statut: {statut})."
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No sale.order matches client={client or 'all'}, period={periode or 'all'}, statut={statut}",
            source="sale.order:read_group(amount_total:sum)",
            value=None,
            scope=scope,
        )
        return text, evidence

    total = results[0]["amount_total"]
    text = f"Le total des ventes{client_label} (statut: {statut}) est de {total:.2f} Ar.\n[Source: Odoo ERP - Module Ventes (sale.order)]"
    evidence = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Total sales amount for client={client or 'all'}, period={periode or 'all'}, statut={statut}",
        source="sale.order:read_group(amount_total:sum)",
        value=total,
        scope=scope,
    )
    return text, evidence


@tool
def get_total_sales(client: str = "", periode: str = "", statut: str = "toutes") -> str:
    """
    Get the total sales amount filtered by client, period, and status.

    Args:
        client: Client name. Leave empty ("") or "tous" for all clients.
        periode: Optional time period filter (e.g. 'ce mois', '2025'). Leave empty string ("") for all time unless a specific period is explicitly mentioned in the user query.
        statut: Order status filter ('confirmees', 'brouillon', 'toutes'). Default: 'toutes'.
    """
    text, _evidence = get_total_sales_raw(client, periode, statut)
    return text

def get_product_stock_raw(produit: str) -> Tuple[str, List[Evidence]]:
    """
    Execute get_product_stock and return both the display string and the
    structured Evidence list (B1 replication -- ORM 2/9, todo/contexte.txt
    section 468+). Returns a List[Evidence] rather than a single Evidence
    (unlike get_total_sales_raw/get_average_sales_raw) because read_group
    here returns two independent raw aggregates (quantity, reserved_
    quantity) in the same call -- each is its own verifiable fact. The
    displayed `available` figure is a derived subtraction of those two
    facts, not a separate Evidence -- it is not something Odoo returned,
    it's arithmetic applied to facts already covered. Deliberately never
    catches connector exceptions itself -- the @tool wrapper below owns
    the try/except, so no Evidence is ever fabricated from a technical
    failure (same discipline as get_average_sales_raw, section 466).
    When `results` has more than one entry (a partial `produit` match on
    several product names), only results[0] is used -- exactly like the
    pre-existing @tool behavior -- so the Evidence only ever covers the
    product actually reflected in `text`, never the ignored matches.
    """
    uid = _get_current_uid()
    scope = _orm_evidence_scope(uid)
    domain = [("product_id.name", "ilike", produit)]

    results = connector.read_group(
        uid=uid,
        model="stock.quant",
        domain=domain,
        fields=["quantity:sum", "reserved_quantity:sum"],
        groupby=["product_id"]
    )

    if not results:
        text = f"Le produit '{produit}' n'a pas été trouvé en stock."
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No stock.quant matches product={produit}",
            source="stock.quant:read_group(quantity:sum,reserved_quantity:sum)",
            value=None,
            scope=scope,
        )
        return text, [evidence]

    qty = results[0].get("quantity", 0.0)
    reserved = results[0].get("reserved_quantity", 0.0)
    available = qty - reserved

    text = f"Il y a {available} unités de '{produit}' disponibles en stock (Total: {qty}, Réservé: {reserved}).\n[Source: Odoo ERP - Module Stock (stock.quant)]"

    evidence_qty = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Total quantity in stock for product={produit}",
        source="stock.quant:read_group(quantity:sum,reserved_quantity:sum)",
        value=qty,
        scope=scope,
    )
    evidence_reserved = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Reserved quantity in stock for product={produit}",
        source="stock.quant:read_group(quantity:sum,reserved_quantity:sum)",
        value=reserved,
        scope=scope,
    )
    return text, [evidence_qty, evidence_reserved]


@tool
def get_product_stock(produit: str) -> str:
    """
    Check the available stock quantity for a specific product.
    
    Args:
        produit: The name of the product to check.
    """
    try:
        text, _evidence = get_product_stock_raw(produit)
        return text
    except Exception as e:
        return f"Erreur lors de la vérification du stock : {str(e)}"

def get_order_status_raw(reference: str) -> Tuple[str, List[Evidence]]:
    """
    Execute get_order_status and return both the display string and the
    structured Evidence list (B1 replication -- ORM 3/9, todo/contexte.txt
    section 470+). Introduces a new form relative to the read_group-based
    pilots: a single-record search_read lookup rather than an aggregation,
    producing a qualitative fact (order state) rather than a numeric sum.
    Returns a List[Evidence] (2 entries on a match): the raw order state
    (Odoo's own value, e.g. "sale" -- not the French display label
    state_fr, which is a display-only translation of the same fact, not an
    independent one) and the partner name -- both are actually asserted in
    `text`. `amount_total` is fetched by the underlying query but never
    displayed in `text` (pre-existing, unrelated to this chantier) -- no
    Evidence is fabricated for a fact the text never actually asserts.
    Deliberately never catches connector exceptions itself -- the @tool
    wrapper below owns the try/except, so no Evidence is ever fabricated
    from a technical failure (same discipline as get_product_stock_raw).
    Domain is an exact match on `name`, so `records` should hold at most
    one entry in practice -- but the same results[0]-only discipline as
    get_product_stock_raw is kept defensively: only records[0] is ever
    reflected in text or Evidence.
    """
    uid = _get_current_uid()
    scope = _orm_evidence_scope(uid)
    domain = [("name", "=", reference)]

    records = connector.search_read(
        uid=uid,
        model="sale.order",
        domain=domain,
        fields=["state", "amount_total", "partner_id"]
    )

    if not records:
        text = f"La commande {reference} n'existe pas."
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No sale.order matches name={reference}",
            source="sale.order:search_read(state,partner_id)",
            value=None,
            scope=scope,
        )
        return text, [evidence]

    order = records[0]
    state_mapping = {
        "draft": "Devis",
        "sent": "Devis envoyé",
        "sale": "Bon de commande (Confirmé)",
        "done": "Verrouillé",
        "cancel": "Annulé"
    }
    state_raw = order.get("state")
    state_fr = state_mapping.get(state_raw, state_raw)
    partner = order.get("partner_id", [0, "Inconnu"])[1]

    text = f"La commande {reference} pour {partner} est au statut '{state_fr}'."

    evidence_state = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Order state for name={reference}",
        source="sale.order:search_read(state,partner_id)",
        value=state_raw,
        scope=scope,
    )
    evidence_partner = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Partner assigned to order name={reference}",
        source="sale.order:search_read(state,partner_id)",
        value=partner,
        scope=scope,
    )
    return text, [evidence_state, evidence_partner]


@tool
def get_order_status(reference: str) -> str:
    """
    Get the status of a specific sales order (e.g. S00042).
    
    Args:
        reference: Sales order reference code.
    """
    try:
        text, _evidence = get_order_status_raw(reference)
        return text
    except Exception as e:
        return f"Erreur lors de la récupération de la commande : {str(e)}"

def get_total_invoices_raw(client: str = "", statut: str = "toutes") -> Tuple[str, List[Evidence]]:
    """
    Execute get_total_invoices and return both the display string and the
    structured Evidence list (B1 replication -- ORM 8/9, todo/contexte.txt
    section 478+). Design confirmed with Trunk (ORM 8/9 decision table):
      1. Python-side sum() over N read_group rows (global branch) is the
         calculation method for the single "total" fact the text actually
         asserts -> 1 Evidence, not N -- the per-partner rows are an
         intermediate aggregation step, not N separate facts to surface.
      2. Client-specific branch (single result row): 1 positive Evidence
         on the total actually asserted, source=account.move.
      3. AMBIGUITE branch: no total is presented to the user -> [] -- an
         Evidence here would assert a fact the text never actually states.
      4. sale.order fallback branch (account.move empty, fallback finds a
         total): Evidence.source follows the real provenance of the value
         -- source=sale.order, never account.move -- even though the text
         prose does not currently render a "[Source: ...]" suffix on this
         branch (the source must follow the real provenance, not what the
         text happens to display).
      5. Fully-empty branch (both account.move AND the sale.order fallback
         return nothing): 1 negative Evidence, value=None, confidence never
         set (deterministic ORM read, core/evidence.py). Its `source` is a
         COMPOSITE of both attempted reads ("account.move:... ; sale.order:
         ..."), not account.move alone -- the claim honestly covers what
         was actually checked. No separate negative Evidence is added for
         sale.order on its own: the final text never surfaces that attempt
         as a distinct fact from the account.move one.

    Known pre-existing limitation, NOT fixed here (out of scope for this
    Evidence-ification pass, would need its own mandate): the sale.order
    fallback query does not re-apply the `client`/`statut` filters used on
    the account.move query -- it is a global "confirmed sales to date"
    read. The Evidence claim below reflects this honestly (it does not
    claim a client-scoped fallback value that was never actually computed).
    """
    uid = _get_current_uid()
    scope = _orm_evidence_scope(uid)

    payment_state = None
    state = None

    statut_lower = statut.lower()
    if "pay" in statut_lower and "impay" not in statut_lower:
        payment_state = "paid"
        state = "posted"
    elif "impay" in statut_lower:
        payment_state = "not_paid"
        state = "posted"
    elif "brouillon" in statut_lower:
        state = "draft"
        payment_state = "not_paid"

    domain = [
        ("move_type", "=", "out_invoice")
    ]
    if state:
        domain.append(("state", "=", state))

    if client and client.lower() not in ["tous les clients", "tous", ""]:
        domain.append(("partner_id.name", "ilike", _normalize_client_name(client)))

    if state == "posted" and payment_state:
        domain.append(("payment_state", "in", ["paid", "in_payment"] if payment_state == "paid" else ["not_paid", "partial"]))

    account_move_source = "account.move:read_group(amount_total:sum, groupby=partner_id)"
    client_label = client or "tous les clients"

    results = connector.read_group(
        uid=uid,
        model="account.move",
        domain=domain,
        fields=["amount_total:sum"],
        groupby=["partner_id"]
    )

    if not results:
        sale_order_source = "sale.order:read_group(amount_total:sum)"
        fallback_res = connector.read_group(
            uid=uid,
            model="sale.order",
            domain=[("state", "in", ["sale", "done"])],
            fields=["amount_total:sum"],
            groupby=[]
        )
        if fallback_res and fallback_res[0].get("amount_total"):
            tot = fallback_res[0]["amount_total"]
            text = f"Le montant total des ventes confirmées/facturées à ce jour est de {tot:.2f} Ar."
            evidence = make_evidence(
                source_type=EvidenceSourceType.ORM,
                claim="Total confirmed/invoiced sale.order amount to date (fallback: account.move had no matching rows)",
                source=sale_order_source,
                value=tot,
                scope=scope,
            )
            return text, [evidence]

        text = f"Aucune facture ({statut}) trouvée pour {client_label}."
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No matching invoice/sale amount found for client={client_label}, statut={statut}",
            source=f"{account_move_source} [empty] ; {sale_order_source} [empty]",
            value=None,
            scope=scope,
        )
        return text, [evidence]

    is_global = not client or client.lower() in ["tous les clients", "tous", ""]
    if not is_global and len(results) > 1:
        names = [r.get("partner_id")[1] for r in results if r.get("partner_id")]
        text = f"AMBIGUÏTÉ : Plusieurs clients correspondent à '{client}'. Veuillez préciser lequel parmi : {', '.join(names)}."
        return text, []

    if is_global:
        total = sum(r.get("amount_total", 0.0) for r in results)
        text = f"Le total des factures ({statut}) est de {total:.2f} Ar.\n[Source: Odoo ERP - Module Comptabilité (account.move)]"
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"Total invoices amount (statut={statut}) across all clients",
            source=account_move_source,
            value=total,
            scope=scope,
        )
        return text, [evidence]

    total = results[0].get("amount_total", 0.0)
    client_name = results[0].get("partner_id")[1] if results[0].get("partner_id") else client
    text = f"Le total des factures ({statut}) pour {client_name} s'élève à {total:.2f} Ar.\n[Source: Odoo ERP - Module Comptabilité (account.move)]"
    evidence = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Total invoices amount for client={client_name}, statut={statut}",
        source=account_move_source,
        value=total,
        scope=scope,
    )
    return text, [evidence]


@tool
def get_total_invoices(client: str = "", statut: str = "toutes") -> str:
    """
    Get the total amount of invoices (paid, unpaid, draft).
    
    Args:
        client: Client name (Optional).
        statut: Invoice status ('payé', 'impayé', 'brouillon', 'toutes'). Default: 'toutes'.
    """
    try:
        text, _evidence = get_total_invoices_raw(client, statut)
        return text
    except Exception as e:
        return f"Erreur lors de la récupération des factures : {str(e)}"

def search_partner_raw(nom: str) -> Tuple[str, List[Evidence]]:
    """
    Execute search_partner and return both the display string and the
    structured Evidence list (B1 replication -- ORM 4/9, todo/contexte.txt
    section 471+). Unlike the single-record lookups (get_order_status,
    get_product_stock), this tool is a multi-result search by construction
    (`ilike` on a partial name) -- up to 5 partners can be displayed in
    `text` at once (pre-existing truncation, unchanged here). Granularity
    confirmed by San Goku: one Evidence per partner actually displayed
    (never per ignored/truncated match beyond the first 5), each Evidence
    carrying the 3 contact facts (email, phone, city) together as a single
    structured `value` dict rather than 3 separate Evidence per partner --
    avoids exploding the Evidence count on a search that can legitimately
    surface several clients at once. Deliberately never catches connector
    exceptions itself -- the @tool wrapper below owns the try/except, so no
    Evidence is ever fabricated from a technical failure (same discipline
    as every other ORM Evidence tool so far).
    """
    uid = _get_current_uid()
    scope = _orm_evidence_scope(uid)
    domain = [("name", "ilike", _normalize_client_name(nom))]

    records = connector.search_read(
        uid=uid,
        model="res.partner",
        domain=domain,
        fields=["name", "email", "phone", "city"]
    )

    if not records:
        text = f"Aucun client trouvé avec le nom '{nom}'."
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No res.partner matches name={nom}",
            source="res.partner:search_read(name,email,phone,city)",
            value=None,
            scope=scope,
        )
        return text, [evidence]

    displayed = records[:5]
    result_lines = [f"{len(records)} client(s) trouvé(s) :"]
    evidences = []
    for r in displayed:
        partner_name = r.get("name")
        email = r.get("email") or "N/A"
        phone = r.get("phone") or "N/A"
        city = r.get("city") or "N/A"
        result_lines.append(f"- {partner_name} (Email: {email}, Tél: {phone}, Ville: {city})")
        evidences.append(make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"Contact details for partner={partner_name}",
            source="res.partner:search_read(name,email,phone,city)",
            value={"email": email, "phone": phone, "city": city},
            scope=scope,
        ))

    if len(records) > 5:
        result_lines.append("... (résultats tronqués, précisez la recherche)")

    result_lines.append("[Source: Odoo ERP - Contacts (res.partner)]")
    text = "\n".join(result_lines)
    return text, evidences


@tool
def search_partner(nom: str) -> str:
    """
    Search for a client or partner by name to get contact details.
    
    Args:
        nom: Client name or partial name to search.
    """
    try:
        text, _evidence = search_partner_raw(nom)
        return text
    except Exception as e:
        return f"Erreur lors de la recherche du client : {str(e)}"

def get_recent_tickets_raw(client: str = "", limite: int = 0, statut: Optional[str] = None) -> Tuple[str, List[Evidence]]:
    """
    Execute get_recent_tickets and return both the display string and the
    structured Evidence list (B1 replication -- ORM 6/9, todo/contexte.txt
    section 476+). Granularity confirmed by San Goku: one Evidence per
    ticket actually displayed (bounded by display_limit, mirroring the
    pre-existing display truncation) -- never for a ticket beyond that
    limit, since `text` never asserts anything about it. Each Evidence
    bundles the 3 facts actually asserted in `text` together as a single
    structured `value` dict (state, partner, create_date) -- same pattern
    as search_partner_raw's contact dict. `date_deadline` is fetched and
    used for sorting only -- never displayed in `text` -- so, like
    `amount_total` in get_order_status_raw, it is deliberately excluded
    from Evidence: no Evidence is ever fabricated for a fact the text
    never actually asserts. The AMBIGUÏTÉ branch asserts no fact about any
    specific ticket (it interrupts display to ask the caller to
    disambiguate a client) -- it returns text with an empty Evidence list,
    same principle as a technical exception producing no Evidence.
    Deliberately never catches connector exceptions itself -- the @tool
    wrapper below owns the try/except, so no Evidence is ever fabricated
    from a technical failure (same discipline as every other ORM Evidence
    tool so far).
    """
    uid = _get_current_uid()
    scope = _orm_evidence_scope(uid)
    domain = []

    is_global = not client or client.lower() in ["tous les clients", "tous", ""]
    if not is_global:
        domain.append(("partner_id.name", "ilike", _normalize_client_name(client)))

    if statut:
        statut_lower = statut.lower()
        if "résolu" in statut_lower or "fini" in statut_lower or "done" in statut_lower:
            domain.append(("state", "=", "1_done"))
        elif "en cours" in statut_lower or "progress" in statut_lower:
            domain.append(("state", "=", "01_in_progress"))
        elif "nouveau" in statut_lower or "ouvert" in statut_lower:
            domain.append(("state", "=", "01_in_progress"))

    records = connector.search_read(
        uid=uid,
        model="project.task",
        domain=domain,
        fields=["name", "state", "create_date", "date_deadline", "partner_id"],
        order="date_deadline desc, id desc"
    )
    if not records:
        text = f"Aucun ticket trouvé pour {client or 'tous les clients'} avec le statut '{statut or 'tous'}'.\n[Source: Odoo ERP - Module Projet (project.task)]"
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No project.task matches client={client or 'all'}, statut={statut or 'all'}",
            source="project.task:search_read(state,create_date,partner_id)",
            value=None,
            scope=scope,
        )
        return text, [evidence]

    if not is_global:
        unique_partners = set()
        for r in records:
            if r.get("partner_id"):
                unique_partners.add(r.get("partner_id")[1])

        if len(unique_partners) > 1:
            text = f"AMBIGUÏTÉ : Plusieurs clients correspondent à '{client}'. Veuillez préciser lequel parmi : {', '.join(unique_partners)}."
            return text, []

    records.sort(key=lambda x: (x.get("date_deadline") or x.get("create_date") or "", x.get("id", 0)), reverse=True)

    total_count = len(records)
    display_limit = limite if limite > 0 else total_count

    result_lines = [
        f"Total de tickets trouvés : {total_count}",
        f"Liste des tickets pour {client or 'tous les clients'} :"
    ]
    evidences = []
    for r in records[:display_limit]:
        state = r.get("state") or "N/A"
        date_str = r.get("create_date") or "N/A"
        if date_str != "N/A":
            date_str = date_str[:10]
        partner_name = r.get("partner_id")[1] if r.get("partner_id") else "N/A"
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
    text = "\n".join(result_lines)
    return text, evidences


@tool
def get_recent_tickets(client: str = "", limite: int = 0, statut: Optional[str] = None) -> str:
    """
    Get support tickets or project tasks from Odoo ERP.
    
    Args:
        client: Optional client name. Leave empty ("") for all clients.
        limite: Max number of tickets to return (0 for all matching tickets).
        statut: Optional status filter (e.g. 'résolu', 'en cours'). Leave None unless the user explicitly requests a specific ticket status.
    """
    try:
        text, _evidence = get_recent_tickets_raw(client, limite, statut)
        return text
    except Exception as e:
        return f"Erreur lors de la récupération des tickets : {str(e)}"

def list_out_of_stock_products_raw() -> Tuple[str, List[Evidence]]:
    """
    Execute list_out_of_stock_products and return both the display string
    and the structured Evidence list (B1 replication -- ORM 5/9, todo/
    contexte.txt section 473+). Structurally new relative to the previous
    4 ORM tools: read_group here is unfiltered (domain=[]) and returns
    every product -- the quantity<=0 criterion is applied in Python, not
    in the query. So an empty `rupture_products` list is not "no data
    matched the query" (like the other tools' negative-evidence case) --
    it is a real, positive fact: the query succeeded and zero products
    satisfy the criterion. Confirmed by San Goku: that case gets a
    POSITIVE Evidence (value=0), not the usual None/negative pattern used
    for a genuinely empty query result elsewhere in this file.
    Granularity confirmed by San Goku: one Evidence per product actually
    displayed (max 10, mirroring the pre-existing display truncation) --
    never for a rupture product beyond that truncation, since `text` never
    asserts anything about it. Deliberately never catches connector
    exceptions itself -- the @tool wrapper below owns the try/except, so
    no Evidence is ever fabricated from a technical failure (same
    discipline as every other ORM Evidence tool so far).
    """
    uid = _get_current_uid()
    scope = _orm_evidence_scope(uid)
    domain = []

    results = connector.read_group(
        uid=uid,
        model="stock.quant",
        domain=domain,
        fields=["quantity:sum"],
        groupby=["product_id"]
    )

    rupture_products = []
    for r in results:
        if r.get("quantity", 0.0) <= 0.0:
            prod = r.get("product_id")
            if prod:
                rupture_products.append((prod[1], r.get("quantity", 0.0)))

    if not rupture_products:
        text = "Aucun produit n'est actuellement en rupture de stock."
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim="No stock.quant product has quantity<=0",
            source="stock.quant:read_group(quantity:sum)",
            value=0,
            scope=scope,
        )
        return text, [evidence]

    displayed = rupture_products[:10]
    text = f"{len(rupture_products)} produit(s) en rupture de stock :\n- " + "\n- ".join(name for name, _qty in displayed) + ("\n..." if len(rupture_products) > 10 else "")

    evidences = [
        make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"Product {name} is out of stock (quantity<=0)",
            source="stock.quant:read_group(quantity:sum)",
            value=qty,
            scope=scope,
        )
        for name, qty in displayed
    ]
    return text, evidences


@tool
def list_out_of_stock_products() -> str:
    """
    List products with zero or negative available stock.
    """
    try:
        text, _evidence = list_out_of_stock_products_raw()
        return text
    except Exception as e:
        return f"Erreur lors de la récupération des stocks : {str(e)}"

def get_period_revenue_raw(periode: str) -> Tuple[str, List[Evidence]]:
    """
    Execute get_period_revenue and return both the display string and the
    structured Evidence list (B1 replication -- ORM 9/9, last ORM tool of
    Bloc B1, todo/contexte.txt section 478+). Same branch shape as
    get_total_invoices_raw (ORM 8/9, ditto file) since both aggregate
    account.move with an identical account.move-empty -> sale.order
    fallback pattern, but with two differences specific to this tool:
      1. No client filter exists on get_period_revenue -> no AMBIGUITE
         branch is possible here (unlike get_total_invoices_raw).
      2. Unlike get_total_invoices_raw's fallback (documented as a known
         pre-existing limitation: it does NOT reapply the account.move
         query's filters), this tool's sale.order fallback DOES reapply
         the date window (`fb_domain` mirrors `date_range` onto
         `date_order`) -- so the fallback Evidence's claim can honestly
         describe it as scoped to the same period, not a global read.
    Branches:
      1. Full branch (results non-empty): Python sum() over N read_group
         rows (grouped by company_id) is the calculation method for the
         single "total" fact the text asserts -> 1 Evidence, not N --
         same principle as get_total_invoices_raw's global branch.
      2. sale.order fallback branch (account.move empty, fallback finds a
         total): Evidence.source follows the real provenance -- source=
         sale.order, never account.move -- even though the text prose does
         not currently render a "[Source: ...]" suffix distinguishing it
         (it reuses the same account.move-labelled suffix as the full
         branch, a pre-existing text quirk not touched here).
      3. Fully-empty branch (both account.move AND the sale.order fallback
         return nothing): 1 negative Evidence, value=None, confidence never
         set. Its `source` is a COMPOSITE of both attempted reads, not
         account.move alone -- same discipline as get_total_invoices_raw.
    Deliberately never catches connector exceptions itself -- the @tool
    wrapper below owns the try/except, so no Evidence is ever fabricated
    from a technical failure (same discipline as every other ORM Evidence
    tool so far).
    """
    uid = _get_current_uid()
    scope = _orm_evidence_scope(uid)
    domain = [
        ("move_type", "=", "out_invoice"),
        ("state", "=", "posted"),
        ("payment_state", "in", ["paid", "in_payment"])
    ]

    date_range = parse_period(periode)
    if date_range:
        domain.append(("invoice_date", ">=", date_range[0]))
        domain.append(("invoice_date", "<=", date_range[1]))

    account_move_source = "account.move:read_group(amount_total:sum, groupby=company_id)"

    results = connector.read_group(
        uid=uid,
        model="account.move",
        domain=domain,
        fields=["amount_total:sum"],
        groupby=["company_id"]
    )

    if not results:
        fb_domain = [("state", "in", ["sale", "done"])]
        if date_range:
            fb_domain.append(("date_order", ">=", date_range[0]))
            end_str = date_range[1] if " " in date_range[1] else date_range[1] + " 23:59:59"
            fb_domain.append(("date_order", "<=", end_str))

        sale_order_source = "sale.order:read_group(amount_total:sum)"
        fallback_res = connector.read_group(
            uid=uid,
            model="sale.order",
            domain=fb_domain,
            fields=["amount_total:sum"],
            groupby=[]
        )
        if fallback_res and fallback_res[0].get("amount_total"):
            tot = fallback_res[0]["amount_total"]
            text = f"Le montant total des ventes confirmées/facturées pour la période '{periode}' est de {tot:.2f} Ar.\n[Source: Odoo ERP - Module Comptabilité (account.move)]"
            evidence = make_evidence(
                source_type=EvidenceSourceType.ORM,
                claim=f"Total confirmed/invoiced sale.order amount for period={periode} (fallback: account.move had no matching rows)",
                source=sale_order_source,
                value=tot,
                scope=scope,
            )
            return text, [evidence]

        text = f"Aucun chiffre d'affaires trouvé pour la période '{periode}'."
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No matching invoice/sale revenue found for period={periode}",
            source=f"{account_move_source} [empty] ; {sale_order_source} [empty]",
            value=None,
            scope=scope,
        )
        return text, [evidence]

    total = sum(r.get("amount_total", 0.0) for r in results)
    text = f"Le chiffre d'affaires total pour la période '{periode}' est de {total:.2f} Ar.\n[Source: Odoo ERP - Module Comptabilité (account.move)]"
    evidence = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Total revenue (paid invoices) for period={periode}",
        source=account_move_source,
        value=total,
        scope=scope,
    )
    return text, [evidence]


@tool
def get_period_revenue(periode: str) -> str:
    """
    Get global revenue (paid invoices) over a period.
    
    Args:
        periode: Time period (e.g. 'ce mois', '2025', 'toutes').
    """
    try:
        text, _evidence = get_period_revenue_raw(periode)
        return text
    except Exception as e:
        return f"Erreur lors du calcul du CA : {str(e)}"

def get_average_sales_raw(client: str = "", periode: str = "toutes") -> Tuple[str, Evidence]:
    """
    Execute get_average_sales and return both the display string and the
    structured Evidence (B1 replication of the B0 pilot -- ORM 1/9, todo/
    contexte.txt sections 429/436+). Exposed separately from the @tool
    wrapper so a future Evidence Builder can call it directly, same pattern
    already used for get_total_sales_raw. Deliberately never catches
    connector exceptions itself -- the @tool wrapper below owns the
    try/except, so this function's return type stays a strict
    Tuple[str, Evidence] (never Optional[Evidence]), and no Evidence is
    ever fabricated from a technical failure.
    """
    uid = _get_current_uid()
    scope = _orm_evidence_scope(uid)
    domain = [("state", "in", ["sale", "done"])]
    if client and client.lower() not in ["tous les clients", "tous", ""]:
        domain.append(("partner_id.name", "ilike", _normalize_client_name(client)))

    date_range = parse_period(periode)
    if date_range:
        domain.append(("date_order", ">=", date_range[0]))
        domain.append(("date_order", "<=", date_range[1]))

    results = connector.read_group(
        uid=uid,
        model="sale.order",
        domain=domain,
        fields=["amount_total:avg"],
        groupby=["partner_id"] if client and client.lower() not in ["tous", ""] else []
    )

    if not results:
        text = f"Aucune vente trouvée pour calculer la moyenne."
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No sale.order matches to compute average for client={client or 'all'}, period={periode or 'all'}",
            source="sale.order:read_group(amount_total:avg)",
            value=None,
            scope=scope,
        )
        return text, evidence

    if not client or client.lower() in ["tous", ""]:
        moyenne = results[0].get("amount_total", 0.0)
        text = f"Le montant moyen d'une vente est de {moyenne:.2f} Ar.\n[Source: Odoo ERP - Module Ventes (sale.order)]"
    else:
        moyenne = results[0].get("amount_total", 0.0)
        client_name = results[0].get("partner_id")[1] if results[0].get("partner_id") else client
        text = f"Le montant moyen d'une vente pour {client_name} est de {moyenne:.2f} Ar.\n[Source: Odoo ERP - Module Ventes (sale.order)]"

    evidence = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Average sale amount for client={client or 'all'}, period={periode or 'all'}",
        source="sale.order:read_group(amount_total:avg)",
        value=moyenne,
        scope=scope,
    )
    return text, evidence


@tool
def get_average_sales(client: str = "", periode: str = "toutes") -> str:
    """
    Get average sale amount for a client or overall.
    
    Args:
        client: Client name (Optional).
        periode: Time period (Optional).
    """
    try:
        text, _evidence = get_average_sales_raw(client, periode)
        return text
    except Exception as e:
        return f"Erreur lors du calcul de la moyenne : {str(e)}"

def get_sale_details_raw(client: str = "", statut: str = "toutes", limite: int = 0) -> Tuple[str, List[Evidence]]:
    """
    Execute get_sale_details and return both the display string and the
    structured Evidence list (B1 replication -- dernier outil ORM du volet
    B1, todo/contexte.txt section 481+). Design confirme avec Ray :
      1. total_sum (Python sum() sur les records affiches) est une
         agregation derivee de faits deja couverts par les Evidence
         par-commande -> aucune Evidence dediee, meme principe que
         `available` dans get_product_stock_raw.
      2. Deux lectures ORM distinctes par commande affichee -- la lecture
         sale.order elle-meme (name/state/partner/amount) et une seconde
         lecture separee sale.order.line (resolution order_line -> noms
         produits) -- donc 2 Evidence par commande, jamais un dict fusionne
         unique, chacune avec sa vraie source. `value` de l'Evidence
         commande porte le `state` brut (valeur Odoo elle-meme, pas le
         libelle francais state_fr -- meme discipline que
         get_order_status_raw : une traduction d'un fait deja couvert
         n'est pas un second fait).
      3. "Aucune ligne du tout" (order_line vide, aucune seconde requete
         meme tentee) et "lignes recuperees mais aucun product_id resolu"
         produisent la meme forme d'Evidence (value=[], positive -- le
         texte affirme "Aucun produit" dans les deux cas, aucune raison de
         distinguer deux formes de claim/value que le texte lui-meme ne
         distingue pas). Le `source` continue neanmoins de suivre la
         lecture reellement responsable du fait : quand order_line etait
         vide, le fait est connu directement depuis la lecture sale.order
         elle-meme (aucune requete sale.order.line n'a jamais eu lieu) --
         citer une source sale.order.line pour une requete jamais executee
         travestirait la provenance, donc ce cas cite
         sale.order:search_read(order_line) a la place.
      4. Fallback intra-modele (pas intra-source comme pour
         get_total_invoices/get_period_revenue) : quand statut != "toutes"
         et que le domaine filtre par statut ne retourne rien, une seconde
         search_read sur LE MEME modele avec un domaine plus large
         (state != cancel) est tentee. Evidence.source doit refleter le
         domaine reellement responsable des records utilises -- primaire
         (filtre par statut) ou fallback (elargi) -- jamais l'autre, meme
         si les deux partagent le meme modele/champs. Quand les deux
         tentatives sont reellement vides (pas un echec technique -- voir
         discipline try/except ci-dessous), 1 Evidence negative avec une
         source composite nommant les deux domaines tentes, meme principe
         que get_total_invoices_raw. Quand statut == "toutes", aucun
         fallback n'est tente (le domaine "toutes" est deja le plus large)
         -- source a un seul domaine sur le cas negatif.
      5. `date_order` est fetche (necessaire nulle part dans `text`) et
         exclu de toute Evidence et de tout `source` -- meme discipline
         que `date_deadline` dans get_recent_tickets_raw / `amount_total`
         dans get_order_status_raw : fetche != affirme.
    Ne catch jamais lui-meme les exceptions connecteur (y compris la
    lecture imbriquee sale.order.line) -- le wrapper @tool ci-dessous
    possede seul le try/except, donc aucune Evidence (positive ou
    negative) n'est jamais fabriquee a partir d'un echec technique. Ce
    point compte plus ici que dans les tools precedents : un `records`
    vide apres une lecture reelle, reussie, vide recoit une Evidence
    negative ; un `records` vide parce que la lecture a leve une exception
    n'en recoit aucune -- les deux ne doivent jamais etre confondus.
    """
    uid = _get_current_uid()
    scope = _orm_evidence_scope(uid)
    # Always fetch all sales orders for the client to provide complete totals and itemized products
    effective_limit = 0 if limite <= 1 else limite

    fields = ["name", "partner_id", "date_order", "amount_total", "state", "order_line"]
    order_source = "sale.order:search_read(name,state,partner_id,amount_total)"

    if statut.lower() in ["brouillon", "en cours"]:
        domain = [("state", "in", ["draft", "sent"])]
    elif statut.lower() in ["confirmé", "confirmees", "confirmées"]:
        domain = [("state", "in", ["sale", "done"])]
    elif statut.lower() in ["annulé", "annule", "cancel"]:
        domain = [("state", "=", "cancel")]
    else:
        domain = [("state", "!=", "cancel")]

    if client and client.lower() not in ["tous les clients", "tous", ""]:
        domain.append(("partner_id.name", "ilike", _normalize_client_name(client)))

    primary_source = f"{order_source}[domaine=statut]"
    records = connector.search_read(
        uid=uid,
        model="sale.order",
        domain=domain,
        fields=fields,
        limit=effective_limit
    )
    used_source = primary_source

    fallback_attempted = False
    fallback_source = None
    if not records and statut.lower() not in ["toutes"]:
        fallback_attempted = True
        fallback_domain = [("state", "!=", "cancel")]
        if client and client.lower() not in ["tous les clients", "tous", ""]:
            fallback_domain.append(("partner_id.name", "ilike", _normalize_client_name(client)))
        fallback_source = f"{order_source}[domaine=state!=cancel (repli)]"
        records = connector.search_read(
            uid=uid,
            model="sale.order",
            domain=fallback_domain,
            fields=fields,
            limit=effective_limit
        )
        used_source = fallback_source

    if not records:
        text = f"Aucune vente trouvée pour {client or 'tous les clients'}."
        if fallback_attempted:
            neg_source = f"{primary_source} [empty] ; {fallback_source} [empty]"
        else:
            neg_source = f"{primary_source} [empty]"
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No sale.order matches client={client or 'all'}, statut={statut}",
            source=neg_source,
            value=None,
            scope=scope,
        )
        return text, [evidence]

    total_sum = sum(r.get("amount_total", 0.0) for r in records)
    state_labels = {
        "draft": "Devis en cours",
        "sent": "Devis envoyé",
        "sale": "Vente confirmée",
        "done": "Vente confirmée",
        "cancel": "Commande annulée"
    }
    total_fmt = f"{total_sum:,.2f}".replace(",", " ")
    result_lines = [
        f"Détails des commandes / devis pour {client or 'tous les clients'} (Total: {total_fmt} Ar, {len(records)} commande(s)) :"
    ]
    evidences = []
    for r in records:
        client_name = r.get("partner_id")[1] if r.get("partner_id") else "Inconnu"
        amount = r.get("amount_total", 0.0)
        amount_fmt = f"{amount:,.2f}".replace(",", " ")
        state_raw = r.get("state", "inconnu")
        state_fr = state_labels.get(state_raw, state_raw)
        name = r.get("name", "inconnu")

        evidences.append(make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"Order details for name={name}",
            source=used_source,
            value={"state": state_raw, "partner": client_name, "amount": amount},
            scope=scope,
        ))

        line_ids = r.get("order_line", [])
        produits = []
        if line_ids:
            lines = connector.search_read(
                uid=uid,
                model="sale.order.line",
                domain=[("id", "in", line_ids)],
                fields=["product_id"]
            )
            for line in lines:
                if line.get("product_id"):
                    produits.append(line.get("product_id")[1])
            products_source = "sale.order.line:search_read(product_id)"
        else:
            products_source = "sale.order:search_read(order_line)"

        evidences.append(make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"Products for order name={name}",
            source=products_source,
            value=produits,
            scope=scope,
        ))

        prod_str = ", ".join(produits) if produits else "Aucun produit"
        result_lines.append(f"- Commande {name} ({state_fr}) pour {client_name} : {amount_fmt} Ar. Produits : {prod_str}")

    result_lines.append("[Source: Odoo ERP - Module Ventes (sale.order)]")
    text = "\n".join(result_lines)
    return text, evidences


@tool
def get_sale_details(client: str = "", statut: str = "toutes", limite: int = 0) -> str:
    """
    Get sale order line details (products sold, amounts, dates) for a client.
    
    Args:
        client: Client name.
        statut: Optional order status filter ('confirmé', 'brouillon', 'toutes'). Default: 'toutes'. Leave 'toutes' unless a specific status is explicitly requested.
        limite: Max sales orders to return (0 for all matching sales orders). Default: 0. Leave 0 unless a specific limit is explicitly requested.
    """
    try:
        text, _evidence = get_sale_details_raw(client, statut, limite)
        return text
    except Exception as e:
        return f"Erreur lors de la récupération des détails : {str(e)}"

