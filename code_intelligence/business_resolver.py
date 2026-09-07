"""
code_intelligence/business_resolver.py

Business Term to Technical Symbol Resolver.
Maps natural language functional concepts to technical graph nodes (models, fields, modules).

Resolution Order:
1. Static Business Alias Lookup (BUSINESS_ALIASES dictionary) - 100% deterministic, zero latency.
2. Fuzzy String Matching against indexed Graph Node labels, names, and XML-IDs.
3. Bounded LLM Candidate Selection (only if ambiguous candidates exist).
4. Explicit "unresolved" return status if no candidate matches.
"""

import re
import logging
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from rapidfuzz import fuzz, process

_logger = logging.getLogger(__name__)


BUSINESS_ALIASES: Dict[str, List[str]] = {
    # Comptabilité / avoirs
    "avoir": ["account.move"],
    "avoirs": ["account.move"],
    "credit note": ["account.move"],
    "facture": ["account.move"],
    "factures": ["account.move"],
    "facturation": ["account.move", "sale.order"],
    "demande d'achat": ["purchase.request", "custom.purchase.request"],
    "demande d'achats": ["purchase.request", "custom.purchase.request"],
    "ligne de demande d'achat": ["purchase.request.line"],
    "lignes de demande d'achat": ["purchase.request.line"],
    "commande d'achat": ["purchase.order"],
    "commandes d'achat": ["purchase.order"],
    "ligne de commande d'achat": ["purchase.order.line"],
    "lignes de commande d'achat": ["purchase.order.line"],
    # Prêt matériel
    "mise a disposition": ["custom.asset.loan"],
    "mise à disposition": ["custom.asset.loan"],
    # Section 228 (todo/contexte.txt) : alias manquants, question H4 reelle
    # ("Quelles sont les regles de visibilite pour les prets de materiel ?")
    # ne matchait aucun alias existant -- "mise a disposition" seul ne couvre
    # pas le vocabulaire "pret(s) de materiel".
    "pret de materiel": ["custom.asset.loan"],
    "prêt de matériel": ["custom.asset.loan"],
    "prets de materiel": ["custom.asset.loan"],
    "prêts de matériel": ["custom.asset.loan"],
    # Congés
    "conge": ["hr.leave"],
    "congé": ["hr.leave"],
    "conges": ["hr.leave"],
    "congés": ["hr.leave"],
    "demande de conge": ["hr.leave"],
    "demande de congé": ["hr.leave"],
    "remboursement": ["custom.reimbursement.request", "hr.expense"],
    "remboursement de frais": ["custom.reimbursement.request", "hr.expense"],
    "note de frais": ["custom.reimbursement.request", "hr.expense"],
    # Automatismes Odoo
    "action automatique": ["base.automation"],
    "serveur action": ["ir.actions.server"],
    "server action": ["ir.actions.server"],
    # Deep inheritance security
    "document deep": ["custom.deep.document"],
    "deep document": ["custom.deep.document"],
    # Section 228 (todo/contexte.txt) : forme plurielle manquante -- la
    # frontiere de mot stricte du pattern d'alias ne tolere pas le "s" du
    # pluriel intercale ("documents deep" ne matchait ni "document deep" ni
    # "deep document"), reproduit par une question H4 reelle ("Un employe
    # peut-il voir les documents deep sans autorisation ?").
    "documents deep": ["custom.deep.document"],
    "deep documents": ["custom.deep.document"],
    # Animal
    "animaux": ["animal"],
    "espece": ["animal.species"],
    "especes": ["animal.species"],
    "espèce": ["animal.species"],
    "espèces": ["animal.species"],
    "race": ["animal.breed"],
    "races": ["animal.breed"],
    # Tier validation
    "validation par paliers": ["tier.validation"],
    "approbation par paliers": ["tier.validation"],
    "tier validation": ["tier.validation"],
    "champs non exemptes": ["tier.validation"],
    "champs non exemptés": ["tier.validation"],
    "en cours de validation": ["tier.validation"],
    # Stock inventory
    "inventaire": ["stock.inventory"],
    "inventaires": ["stock.inventory"],
    "ajustement d'inventaire": ["stock.inventory"],
    "ajustements d'inventaire": ["stock.inventory"],
    # Sale order type
    "type de commande": ["sale.order", "sale.order.type"],
    "types de commande": ["sale.order", "sale.order.type"],
    "type d'une commande": ["sale.order", "sale.order.type"],
    "type de commande de vente": ["sale.order", "sale.order.type"],
    "types de commande de vente": ["sale.order", "sale.order.type"],
    "commande confirmee": ["sale.order"],
    "commande confirmée": ["sale.order"],
    "commandes confirmees": ["sale.order"],
    "commandes confirmées": ["sale.order"],
    "commande": ["sale.order"],
    "commandes": ["sale.order"],
    "commande de vente": ["sale.order"],
    "commandes de vente": ["sale.order"],
    "generation de facture": ["sale.order", "account.move"],
    "génération de facture": ["sale.order", "account.move"],
    "section de facture": ["account.move"],
    "sections de facture": ["account.move"],
    "ligne de section": ["sale.order", "account.move.line"],
    "lignes de section": ["sale.order", "account.move.line"],
    # Partenaires / Contacts
    "partenaire": ["res.partner"],
    "partenaires": ["res.partner"],
    "fiche partenaire": ["res.partner"],
    "fiche d'un partenaire": ["res.partner"],
    "contact": ["res.partner"],
    "contacts": ["res.partner"],
    # Sociétés
    "societe": ["res.company"],
    "société": ["res.company"],
    "societes": ["res.company"],
    "sociétés": ["res.company"],
    "entreprise": ["res.company"],
    "entreprises": ["res.company"],
    "compagnie": ["res.company"],
    "compagnies": ["res.company"],
    # Database cleanup
    "database cleanup": ["cleanup.purge.wizard"],
    "nettoyage de base": ["cleanup.purge.wizard"],
    "nettoyage de base de donnees": ["cleanup.purge.wizard"],
    "nettoyage de base de données": ["cleanup.purge.wizard"],
    "purge": ["cleanup.purge.wizard"],
    "purges": ["cleanup.purge.wizard"],
    "proposer a la purge": ["cleanup.purge.wizard.model"],
    "proposer à la purge": ["cleanup.purge.wizard.model"],
    "purge de modeles": ["cleanup.purge.wizard.model"],
    "purge de modèles": ["cleanup.purge.wizard.model"],
    "purge de modeles orphelins": ["cleanup.purge.wizard.model"],
    "purge de modèles orphelins": ["cleanup.purge.wizard.model"],
    "modeles orphelins": ["cleanup.purge.wizard.model"],
    "modèles orphelins": ["cleanup.purge.wizard.model"],
    "purge de colonnes": ["cleanup.purge.wizard.column"],
    "colonnes orphelines": ["cleanup.purge.wizard.column"],
    "colonnes sensibles": ["cleanup.purge.wizard.column"],
    "suppression de colonnes": ["cleanup.purge.wizard.column"],
    "purge de champs": ["cleanup.purge.wizard.field"],
    "champs orphelins": ["cleanup.purge.wizard.field"],
    "purge de tables": ["cleanup.purge.wizard.table"],
    "tables orphelines": ["cleanup.purge.wizard.table"],
    # Stock archive constraint
    "stock archive constraint": ["product.product", "stock.location"],
    "stock_archive_constraint": ["product.product", "stock.location"],
    "archiver un produit": ["product.product"],
    "archiver un emplacement": ["stock.location"],
    "archiver des produits": ["product.product"],
    "archiver des emplacements": ["stock.location"],
    "archivage de produit": ["product.product"],
    "archivage d'emplacement": ["stock.location"],
    "archivage d'un produit": ["product.product"],
    "archivage d'un emplacement": ["stock.location"],
    "archivage produit": ["product.product"],
    "archivage emplacement": ["stock.location"],
    "emplacements de stock": ["stock.location"],
    "emplacement de stock": ["stock.location"],
    # Auditlog
    "auditlog": ["auditlog.rule", "auditlog.log"],
    "regle d'audit": ["auditlog.rule"],
    "règle d'audit": ["auditlog.rule"],
    "regles d'audit": ["auditlog.rule"],
    "règles d'audit": ["auditlog.rule"],
    "regle audit": ["auditlog.rule"],
    "règle audit": ["auditlog.rule"],
    "regles audit": ["auditlog.rule"],
    "règles audit": ["auditlog.rule"],
    "audit rule": ["auditlog.rule"],
    "audit rules": ["auditlog.rule"],
    "modele audite": ["auditlog.rule"],
    "modèle audité": ["auditlog.rule"],
    "modeles audites": ["auditlog.rule"],
    "modèles audités": ["auditlog.rule"],
    "journalisation": ["auditlog.log"],
    "journal d'audit": ["auditlog.log"],
    "journaux d'audit": ["auditlog.log"],
    "logs d'audit": ["auditlog.log"],
    "log d'audit": ["auditlog.log"],
    # KPI
    "kpi": ["kpi"],
    "kpi.kpi": ["kpi"],
    "indicateur": ["kpi"],
    "indicateurs": ["kpi"],
    "kpis": ["kpi"],
    "valeur d'un kpi": ["kpi"],
    "calculer un kpi": ["kpi"],
}


# Section 307-310 (todo/contexte.txt) : lexique de synonymes FR pour les
# modeles Odoo natifs, delibrement SEPARE de BUSINESS_ALIASES (mecanisme
# different -- celui-ci alimente l'index fuzzy du Step 2, il n'est jamais
# teste en priorite/deterministe comme BUSINESS_ALIASES au Step 1). Portee
# Phase 1 restreinte aux 4 entrees ci-dessous, chacune validee empiriquement
# via scripts/test_resolver.py (sections 307-310) : la requete correspondante
# etait un `unresolved` PROPRE (reason="No business alias or graph model
# match found."), sans aucun candidat concurrent existant a ce jour. Des
# candidats plus courts/ambigus ("achat" seul, "stock" seul, "reception"
# seul, "produit" seul) ont ete explicitement exclus de cette Phase 1 --
# ils sont deja noyes dans plusieurs modeles a score quasi identique dans
# l'index existant (5+ candidats a 100 pour "stock"/"reception", 5 candidats
# a 86 pour "produit"), et l'ajout d'un synonyme supplementaire n'y cree pas
# de gagnant net -- au contraire, "achat" seul creerait une egalite exacte a
# 100 avec un label de champ existant sur custom.asset.loan (root cause
# tracee section 309). Ne pas y ajouter d'entree sans repeter la meme mesure
# prealable (dump reason via _fuzzy_match_graph/resolve_business_term).
NATIVE_MODEL_SYNONYMS: Dict[str, List[str]] = {
    "sale.order": ["commande de vente", "devis", "vente"],
    "purchase.order": ["commande d'achat"],
    "stock.picking": ["livraison"],
    "stock.move": ["mouvement de stock"],
}


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


BUSINESS_ALIASES_NFC: Dict[str, List[str]] = {_nfc(k): v for k, v in BUSINESS_ALIASES.items()}

_ALIAS_PATTERNS: Dict[str, re.Pattern] = {
    alias: re.compile(r"(?<!\w)" + re.escape(alias) + r"(?!\w)")
    for alias in BUSINESS_ALIASES_NFC
}

AMBIGUITY_GAP_THRESHOLD = 10.0

# Section 228 (todo/contexte.txt), option (b): candidate shortlist used ONLY
# when the strict fuzzy pass (threshold above, in _fuzzy_match_graph's default
# argument) finds nothing at all -- see the "else" branch in
# resolve_business_term below for the full rationale (length_penalty makes the
# strict threshold unreachable for long questions matched against short
# indexed labels). Never auto-accepted: only ever used to build a bounded
# closed list for _llm_arbitrate.
WIDENED_CANDIDATE_THRESHOLD = 30
WIDENED_CANDIDATE_LIMIT = 8

_ARBITRATION_SYSTEM_PROMPT = (
    "Tu es un composant de résolution de symboles techniques Odoo. "
    "Tu dois choisir, parmi une liste fermée de modèles techniques candidats, "
    "celui qui correspond le mieux à la question métier posée — ou indiquer "
    "qu'aucun ne convient. Tu ne dois JAMAIS proposer un nom de modèle en "
    "dehors de la liste fournie, même s'il te semble plus pertinent."
)


def _build_arbitration_prompt(query_text: str, candidates: List[str]) -> str:
    candidates_block = "\n".join(f"- {c}" for c in candidates)
    return (
        f'Question métier utilisateur : "{query_text}"\n\n'
        f"Modèles techniques Odoo candidats (extraits par correspondance approximative, "
        f"scores proches, ambigus) :\n{candidates_block}\n\n"
        "Réponds UNIQUEMENT avec le nom technique exact d'UN SEUL de ces modèles "
        "s'il correspond clairement à la question, ou UNIQUEMENT le mot NONE si "
        "aucun ne correspond clairement. Pas d'explication, pas de ponctuation, "
        "pas de modèle hors de cette liste."
    )


def _llm_arbitrate(query_text: str, candidates: List[str], llm) -> Optional[str]:
    """
    Bounded LLM candidate selection over a closed list.

    Args:
        query_text: original user question.
        candidates: closed list of candidate technical model names (fuzzy top-N).
        llm: a LangChain-compatible chat model already instantiated by the
             caller (e.g. graph.py's ChatGroq client). Injected rather than
             built here so callers/tests control the client and its config.

    Returns:
        The chosen candidate (exact string from `candidates`), or None if
        the LLM said NONE, returned something outside the closed list, or
        the call failed. None is never treated as a guess — callers must
        fall back to "unresolved", never silently pick a default candidate.
    """
    if llm is None:
        _logger.warning("LLM arbitration requested but no llm client was provided; skipping.")
        return None

    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        # Section 263 (todo/contexte.txt): route through the same
        # multi-key Groq rotation / rate-limit retry wrapper already used
        # by the Code Intelligence branch (core/llm_client.py), instead of
        # calling llm.invoke() directly. rebuild_llm rebuilds a plain
        # (non-tool-bound) client via get_chat_llm() -- reasonable default
        # for a short, single-shot arbitration call -- so a 429 on the
        # injected `llm` rotates to the next configured GROQ_API_KEYS entry
        # instead of failing this arbitration outright.
        from core.llm_client import get_chat_llm, invoke_with_rate_limit

        prompt = _build_arbitration_prompt(query_text, candidates)
        messages = [
            SystemMessage(content=_ARBITRATION_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        def _rebuild_arbitration_llm():
            return get_chat_llm(temperature=0.0, max_retries=0)

        response, _wait = invoke_with_rate_limit(
            llm, messages, rebuild_llm=_rebuild_arbitration_llm,
        )
        raw = (response.content or "").strip()
    except Exception:
        _logger.exception("LLM arbitration call failed for query=%r candidates=%r", query_text, candidates)
        return None

    if raw == "NONE":
        return None
    if raw in candidates:
        return raw

    _logger.warning("LLM arbitration returned an out-of-list value: %r (candidates=%r)", raw, candidates)
    return None


@dataclass
class ResolvedConcept:
    user_term: str
    resolved_models: List[str] = field(default_factory=list)
    resolved_modules: List[str] = field(default_factory=list)
    confidence: float = 1.0
    source_step: str = "static_alias"
    is_resolved: bool = True
    reason: str = ""


_FUZZY_INDEX_CACHE: Dict[int, List[Tuple[str, str]]] = {}


def _build_fuzzy_index(G) -> List[Tuple[str, str]]:
    """
    Build (label, technical_model_name) pairs from graph nodes as targets
    for fuzzy matching.  Sources:
      - Model.description  (e.g. "Credit Note Approval")  -> model name
      - Field.label        (e.g. "Montant total")          -> parent model
      - Menu.name          (e.g. "Facturation / Avoirs")   -> model via OPENS_MODEL
    Labels shorter than 3 characters are skipped (too noisy).
    """
    cache_key = id(G)
    if cache_key in _FUZZY_INDEX_CACHE:
        return _FUZZY_INDEX_CACHE[cache_key]

    index: List[Tuple[str, str]] = []

    for node_id, data in G.nodes(data=True):
        node_type = data.get("node_type")

        if node_type == "Model":
            model_name = data.get("name", node_id.replace("model:", ""))
            desc = data.get("description", "")
            if desc and len(desc) >= 3:
                index.append((desc.lower(), model_name))

        elif node_type == "Field":
            label = data.get("label", "")
            model_name = data.get("model", "")
            if label and model_name and len(label) >= 3:
                index.append((label.lower(), model_name))

        elif node_type == "Menu":
            menu_name = data.get("name", "")
            if menu_name and len(menu_name) >= 3:
                for successor in G.successors(node_id):
                    edge_data = G.edges[node_id, successor]
                    if edge_data.get("edge_type") == "OPENS_MODEL":
                        model_name = successor.replace("model:", "")
                        index.append((menu_name.lower(), model_name))
                        break

        if node_type == "Model":
            technical_name = data.get("name", node_id.replace("model:", ""))
            if technical_name:
                index.append((technical_name.lower(), technical_name))
                spaced = technical_name.replace(".", " ").replace("_", " ")
                if spaced != technical_name:
                    index.append((spaced.lower(), technical_name))

    # injection des synonymes FR pour les modeles Odoo natifs (Phase 1), au meme titre que les entrees Model.description/Field.label/Menu.name ci-dessus -- meme forme de tuple (label.lower(), model_name), meme scorer, aucun traitement prioritaire. Garde G.has_node() pour ne pas injecter silencieusement un synonyme sur un modele absent du graphe charge (ex. module non installe sur cette instance) -- un synonyme fantome pointant vers un modele inexistant serait pire qu'une absence de synonyme.
    for model_name, synonyms in NATIVE_MODEL_SYNONYMS.items():
        if not G.has_node(f"model:{model_name}"):
            continue
        for synonym in synonyms:
            index.append((synonym.lower(), model_name))

    _FUZZY_INDEX_CACHE[cache_key] = index
    _logger.info("Built fuzzy index: %d entries from graph (%d nodes)", len(index), G.number_of_nodes())
    return index


_GENERIC_FIELD_NAMES = {
    "name", "state", "active", "sequence", "create_uid", "create_date",
    "write_uid", "write_date", "company_id", "currency_id", "description",
    "note", "user_id", "partner_id", "date", "type", "id", "display_name",
    "color", "product_id", "product_uom_id", "categ_id", "parent_id",
    "message_ids", "activity_ids", "message_follower_ids",
}


def _find_exact_technical_model_mentions(query_lower: str, G) -> List[str]:
    if G is None:
        return []
    found = []
    for node_id, data in G.nodes(data=True):
        if data.get("node_type") != "Model":
            continue
        technical_name = data.get("name", node_id.replace("model:", ""))
        if not technical_name or len(technical_name) < 3:
            continue
        pattern = r"(?<!\w)" + re.escape(technical_name.lower()) + r"(?!\w)"
        if re.search(pattern, query_lower):
            found.append(technical_name)
    if not found:
        field_models: Dict[str, Set[str]] = {}
        for node_id, data in G.nodes(data=True):
            nt = data.get("node_type")
            if nt in {"Method", "Button", "Menu"}:
                candidates = []
                m_name = (data.get("name") or "").strip().lower()
                if len(m_name) >= 6 and (m_name.startswith(("action_", "button_", "_compute_", "_check_")) or "_" in m_name):
                    candidates.append(m_name)
                m_label = (data.get("label") or "").strip().lower()
                if len(m_label) >= 4 and " " in m_label:
                    candidates.append(m_label)
                for cand in candidates:
                    pattern = r"(?<!\w)" + re.escape(cand) + r"(?!\w)"
                    if re.search(pattern, query_lower):
                        parent_model = data.get("model")
                        if parent_model and parent_model not in found:
                            found.append(parent_model)
            elif nt == "Field":
                f_name = (data.get("name") or "").strip().lower()
                if f_name and f_name not in _GENERIC_FIELD_NAMES and len(f_name) >= 5 and ("_" in f_name or f_name.startswith("x_")):
                    parent_model = data.get("model")
                    if parent_model:
                        field_models.setdefault(f_name, set()).add(parent_model)
        if not found and field_models:
            for f_name, models in field_models.items():
                if len(models) <= 3:
                    pattern = r"(?<!\w)" + re.escape(f_name) + r"(?!\w)"
                    if re.search(pattern, query_lower):
                        for m in models:
                            if m not in found:
                                found.append(m)
    return found


def _find_exact_technical_module_mentions(query_lower: str, G) -> List[str]:
    if G is None:
        return []
    found = []
    generic_module_words = {"base", "mail", "web", "auth", "sale", "account", "stock", "purchase", "point_of_sale"}
    for node_id, data in G.nodes(data=True):
        if data.get("node_type") != "Module" and not node_id.startswith("module:"):
            continue
        mod_name = data.get("name", node_id.replace("module:", ""))
        if not mod_name or len(mod_name) < 3:
            continue
        mod_lower = mod_name.lower()
        mod_escaped = re.escape(mod_lower).replace('_', r'[\s_]+')
        if mod_lower in generic_module_words:
            pattern = r"(?<!\w)(?:module|addon)\s+" + mod_escaped + r"(?!\w)"
        else:
            pattern = r"(?<!\w)" + mod_escaped + r"(?!\w)"
        if re.search(pattern, query_lower):
            if mod_name not in found:
                found.append(mod_name)

    if not found:
        from pathlib import Path
        for node_id, data in G.nodes(data=True):
            nt = data.get("node_type")
            if nt in {"Field", "Method"}:
                item_name = (data.get("name") or "").strip().lower()
                if item_name and len(item_name) >= 5 and ("_" in item_name or item_name.startswith("x_")):
                    if item_name not in _GENERIC_FIELD_NAMES:
                        pattern = r"(?<!\w)" + re.escape(item_name) + r"(?!\w)"
                        if re.search(pattern, query_lower):
                            fp = data.get("filepath", "")
                            if fp:
                                for parent in Path(fp).parents:
                                    if (parent / "__manifest__.py").exists() and G.has_node(f"module:{parent.name}"):
                                        if parent.name not in generic_module_words and parent.name not in found:
                                            found.append(parent.name)
                                        break
    return found


def _specificity_score(technical_name: str, query_lower: str) -> Tuple[int, int, int, int, int, int, int]:
    """Deterministic specificity score for an exact technical model mention,
    higher is more specific/relevant. Compared as a tuple:
      (is_explicit, has_context_mention, is_domain_model, segments, length, is_custom, occurrences)
    -- see rank_by_specificity's docstring for the rationale (todo/contexte.txt
    section 2xx and section 557)."""
    is_explicit = 1 if re.search(r"\b(?:mod[èe]le|model)\s+['\"]?" + re.escape(technical_name.lower()) + r"['\"]?\b", query_lower) else 0

    has_context_mention = 0
    for part in technical_name.split("."):
        if len(part) >= 4 and re.search(r"(?<!\w)" + re.escape(part.lower()) + r"(?!\w)", query_lower):
            has_context_mention = 1
            break
    if not has_context_mention:
        for alias, targets in BUSINESS_ALIASES_NFC.items():
            if technical_name in targets:
                pat = _ALIAS_PATTERNS.get(alias)
                if pat and pat.search(query_lower):
                    has_context_mention = 1
                    break

    is_domain_model = 0 if (
        technical_name.startswith("ir.")
        or technical_name == "base"
        or technical_name.endswith(".settings")
        or "config.settings" in technical_name
    ) else 1
    segments = technical_name.count(".") + 1
    length = len(technical_name)
    is_custom = 1 if technical_name.startswith(("custom.", "x_")) else 0
    pattern = r"(?<!\w)" + re.escape(technical_name.lower()) + r"(?!\w)"
    occurrences = len(re.findall(pattern, query_lower))
    return (is_explicit, has_context_mention, is_domain_model, segments, length, is_custom, occurrences)


def rank_by_specificity(matches: List[str], query_lower: str) -> List[str]:
    """
    Arbitrate between several exact technical model mentions found verbatim
    in the same question, instead of treating every exact match as equally
    valid (todo/contexte.txt section 2xx and section 557).

    Deterministic criteria, most to least significant:
      1. explicit model qualification (preceded by 'modele' / 'modèle' / 'model')
      2. domain model over framework metadata model (not ir.* or base)
      3. number of dot-segments (custom.deep.document > base)
      4. technical name length
      5. presence of a business/custom prefix (custom., x_)
      6. number of verbatim occurrences in the question

    Only the strictly best-scoring match(es) are kept; ties (identical score
    tuple) are all kept rather than picking one arbitrarily. With a single
    match, this is a no-op.
    """
    if len(matches) <= 1:
        return matches
    scored = [(m, _specificity_score(m, query_lower)) for m in matches]
    top_score = max(score for _m, score in scored)
    return [m for m, score in scored if score == top_score]


def _fuzzy_match_graph(query: str, G, threshold: int = 75, limit: int = 5) -> List[Tuple[str, float]]:
    index = _build_fuzzy_index(G)
    if not index:
        return []

    labels = [entry[0] for entry in index]
    query_lower = query.lower()
    query_token_count = max(len(query_lower.split()), 1)

    model_scores: Dict[str, float] = {}

    for scorer in (fuzz.token_set_ratio, fuzz.token_sort_ratio):
        hits = process.extract(
            query_lower, labels,
            scorer=scorer,
            score_cutoff=threshold * 0.6,
            limit=limit * 5,
        )
        for _text, score, idx in (hits or []):
            label = index[idx][0]
            label_token_count = max(len(label.split()), 1)
            length_penalty = min(label_token_count / query_token_count, 1.0) ** 0.5
            adjusted = score * length_penalty
            if adjusted >= threshold:
                model = index[idx][1]
                model_scores[model] = max(model_scores.get(model, 0.0), adjusted)

    sorted_results = sorted(model_scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_results[:limit]


def resolve_business_term(query_text: str, G=None, llm=None, active_model: Optional[str] = None) -> ResolvedConcept:
    if not query_text:
        return ResolvedConcept(
            user_term="",
            is_resolved=False,
            reason="Empty query text provided."
        )

    clean_query = _nfc(query_text.lower().strip())

    # Step 0 (todo/contexte.txt section 548, mandat San Goku 2026-09-04) :
    # une mention technique exacte d'un Model reellement present dans le
    # graphe charge est desormais PRIORITAIRE sur les alias business
    # statiques du Step 1 ci-dessous -- inversion permanente de l'ordre
    # precedent (l'alias gagnait toujours avant meme d'examiner une
    # mention technique). Root cause du changement : une question comme
    # "une demande d'achat (purchase.request)" doit resoudre vers le
    # modele OCA `purchase.request` litteralement nomme, pas silencieusement
    # vers la cible habituelle de l'alias `custom.purchase.request`, quand
    # `purchase.request` est un noeud reel de G. Portee : ne change RIEN
    # pour toute question sans mention technique verbatim d'un Model
    # existant dans G -- `_find_exact_technical_model_mentions` y retourne
    # `[]` comme avant, donc le Step 1 (alias) s'applique exactement comme
    # avant pour ces cas. Voir test_exact_technical_model_mention_takes_
    # priority_over_static_alias (test_business_resolver.py) pour le
    # contrat mis a jour.
    exact_mentions = _find_exact_technical_model_mentions(clean_query, G)
    exact_modules = _find_exact_technical_module_mentions(clean_query, G)
    if len(exact_mentions) > 1:
        # Section 2xx (todo/contexte.txt), option 2: several exact technical mentions can coexist in one query (e.g. a generic name like 'base' alongside a specific one like 'custom.deep.document') -- arbitrate by specificity instead of returning every exact match as equally valid. See rank_by_specificity's docstring for the rationale.
        exact_mentions = rank_by_specificity(exact_mentions, clean_query)
    if exact_mentions or exact_modules:
        if exact_modules:
            matched_aliases = [
                alias for alias in BUSINESS_ALIASES_NFC
                if _ALIAS_PATTERNS[alias].search(clean_query)
            ]
            alias_models = []
            for alias in matched_aliases:
                for t in BUSINESS_ALIASES_NFC[alias]:
                    if t not in alias_models and t not in exact_mentions:
                        if G is not None:
                            is_in_mod = any(
                                G.has_edge(f"model:{t}", f"module:{mod}") or f"model:{t}" in G.predecessors(f"module:{mod}")
                                for mod in exact_modules if G.has_node(f"module:{mod}")
                            )
                            if is_in_mod:
                                alias_models.append(t)
                        else:
                            alias_models.append(t)
            if alias_models:
                if not exact_mentions:
                    exact_mentions = alias_models
                else:
                    exact_mentions.extend(alias_models)
            elif not exact_mentions and G is not None:
                mod_models = []
                for mod in exact_modules:
                    mod_node = f"module:{mod}"
                    if G.has_node(mod_node):
                        for u in G.predecessors(mod_node):
                            if u.startswith("model:"):
                                m_name = u.replace("model:", "")
                                if m_name not in mod_models:
                                    mod_models.append(m_name)
                if mod_models:
                    exact_mentions = mod_models

        user_term_parts = list(exact_mentions) + list(exact_modules)
        reasons = []
        if exact_mentions:
            reasons.append(f"Exact technical model name(s) mentioned verbatim: {', '.join(exact_mentions)}")
        if exact_modules:
            reasons.append(f"Exact technical module name(s) mentioned verbatim: {', '.join(exact_modules)}")
        return ResolvedConcept(
            user_term=query_text if not user_term_parts else ", ".join(user_term_parts),
            resolved_models=exact_mentions,
            resolved_modules=exact_modules,
            confidence=1.0,
            source_step="exact_technical_mention",
            is_resolved=True,
            reason="; ".join(reasons),
        )

    # Step 1: Static Business Alias Lookup (100% deterministic, zero latency)
    matched_models = []
    matched_modules = []
    matched_terms = []

    matched_aliases = [
        alias for alias in BUSINESS_ALIASES_NFC
        if _ALIAS_PATTERNS[alias].search(clean_query)
    ]
    if len(matched_aliases) > 1:
        matched_aliases = [
            a for a in matched_aliases
            if not any(a != b and a in b for b in matched_aliases)
        ]
        matched_aliases.sort(key=lambda a: (len(a.split()), len(a)), reverse=True)

    for alias in matched_aliases:
        targets = BUSINESS_ALIASES_NFC[alias]
        matched_terms.append(alias)
        if G is not None and G.number_of_nodes() > 0:
            existing_in_g = [
                t for t in targets
                if G.has_node(f"model:{t}") or G.has_node(f"module:{t}")
            ]
            is_alternatives = (
                len(targets) == 2
                and any(t.startswith("custom.") for t in targets)
                and not all(t.startswith("custom.") for t in targets)
            )
            if is_alternatives and existing_in_g:
                targets_to_add = [existing_in_g[0]]
            else:
                targets_to_add = existing_in_g if existing_in_g else targets
        else:
            targets_to_add = targets

        for t in targets_to_add:
            if G is not None and G.has_node(f"module:{t}") and not G.has_node(f"model:{t}"):
                if t not in matched_modules:
                    matched_modules.append(t)
            else:
                if t not in matched_models:
                    matched_models.append(t)

    if matched_models or matched_modules:
        return ResolvedConcept(
            user_term=", ".join(matched_terms),
            resolved_models=matched_models,
            resolved_modules=matched_modules,
            confidence=1.0,
            source_step="static_alias",
            is_resolved=True,
            reason=f"Matched static aliases: {', '.join(matched_terms)}",
        )

    # Step 1.5 (H2, todo/contexte.txt section 569-571): ambient UI context
    # (active_model, propagated end-to-end from the Odoo systray's currently
    # open record) is used ONLY once the question's own text has already
    # failed to resolve anything on its own (Step 0 exact mention, Step 1
    # alias) -- an explicit business term typed by the user always wins over
    # ambient context, never the reverse. Also requires the model to be a
    # real node in the loaded graph, so a stale/foreign active_model (e.g. a
    # model from a module not indexed on this instance) is silently ignored
    # rather than fabricating a false resolution. Confidence is deliberately
    # below the two textual-match steps above (1.0): this is inferred from
    # UI navigation, not asserted by the question itself.
    if active_model and G is not None and G.has_node(f"model:{active_model}"):
        return ResolvedConcept(
            user_term=query_text,
            resolved_models=[active_model],
            confidence=0.9,
            source_step="active_context",
            is_resolved=True,
            reason=f"No textual match in the question itself; resolved from active UI context (model={active_model})",
        )

    # Step 2: Fuzzy matching against Graph Node labels (rapidfuzz)
    if G is not None:
        fuzzy_results = _fuzzy_match_graph(clean_query, G)
        if fuzzy_results:
            top_models = [model for model, _score in fuzzy_results]
            top_score = fuzzy_results[0][1]

            # Ambiguity check: is the top candidate clearly detached from
            # the runner-up, or are several candidates within the gap
            # threshold of each other?
            is_ambiguous = (
                len(fuzzy_results) >= 2
                and (fuzzy_results[0][1] - fuzzy_results[1][1]) < AMBIGUITY_GAP_THRESHOLD
            )

            if not is_ambiguous:
                return ResolvedConcept(
                    user_term=query_text,
                    resolved_models=top_models,
                    confidence=round(top_score / 100, 2),
                    source_step="fuzzy_graph_match",
                    is_resolved=True,
                    reason=f"Fuzzy matched graph labels: {', '.join(f'{m} ({s:.0f})' for m, s in fuzzy_results)}",
                )

            # Step 3: Bounded LLM Candidate Selection (only reached on genuine ambiguity — never for a clear top-1 fuzzy match).
            chosen = _llm_arbitrate(query_text, top_models, llm)
            if chosen is not None:
                return ResolvedConcept(
                    user_term=query_text,
                    resolved_models=[chosen],
                    confidence=0.6,  # bounded/low confidence — LLM interpretation, not a structural fact
                    source_step="llm_arbitration",
                    is_resolved=True,
                    reason=(
                        f"LLM arbitration among ambiguous fuzzy candidates "
                        f"({', '.join(f'{m} ({s:.0f})' for m, s in fuzzy_results)}) -> chose '{chosen}'. "
                        f"Low-confidence LLM interpretation, not a certain structural fact."
                    ),
                )

            return ResolvedConcept(
                user_term=query_text,
                is_resolved=False,
                confidence=0.0,
                source_step="unresolved",
                reason=(
                    f"Ambiguous fuzzy candidates "
                    f"({', '.join(f'{m} ({s:.0f})' for m, s in fuzzy_results)}) "
                    f"and LLM arbitration did not select one."
                ),
            )
        else:
            # the strict threshold above, combined with _fuzzy_match_graph's length_penalty, is mathematically unreachable for long natural-language questions matched against short indexed labels (verified by hand for 2 real H4 failures -- required raw score > 100, impossible). Rather than lowering the strict threshold globally (would start auto-accepting weak matches WITHOUT LLM confirmation -- a correctness regression), a second, deliberately loose fuzzy pass builds a bounded candidate shortlist ONLY for LLM arbitration -- the LLM still never picks outside this closed list (same _llm_arbitrate contract as the ambiguous-strict-match case above), and a chosen candidate is explicitly lower confidence than that case.
            widened_results = _fuzzy_match_graph(
                clean_query, G,
                threshold=WIDENED_CANDIDATE_THRESHOLD,
                limit=WIDENED_CANDIDATE_LIMIT,
            )
            if widened_results:
                widened_models = [model for model, _score in widened_results]
                chosen = _llm_arbitrate(query_text, widened_models, llm)
                if chosen is not None:
                    return ResolvedConcept(
                        user_term=query_text,
                        resolved_models=[chosen],
                        confidence=0.5,  # lower than "llm_arbitration": candidate list itself is weak evidence, not just ambiguous among strong matches
                        source_step="llm_arbitration_widened",
                        is_resolved=True,
                        reason=(
                            f"No candidate reached the strict fuzzy threshold; widened "
                            f"low-threshold candidates "
                            f"({', '.join(f'{m} ({s:.0f})' for m, s in widened_results)}) "
                            f"-> LLM chose '{chosen}'. Low-confidence LLM interpretation "
                            f"over a weak candidate shortlist, not a certain structural fact."
                        ),
                    )

    # Step 4: Unresolved concept fallback
    return ResolvedConcept(
        user_term=query_text,
        is_resolved=False,
        confidence=0.0,
        source_step="unresolved",
        reason="No business alias or graph model match found."
    )
