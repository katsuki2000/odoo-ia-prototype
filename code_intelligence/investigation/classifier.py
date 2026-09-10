"""
code_intelligence/investigation_plan_classifier.py

Deterministic Question Intent classification using regex cascades and graph ontology tags.
Replaces the ad-hoc GOVERNANCE_SIGNAL_TERMS list with a principled
intent + ontology-grounded classifier.
"""

from typing import Any, Optional
import logging
import re

from code_intelligence.business_resolver import ResolvedConcept
from code_intelligence.investigation.schemas import (
    QuestionIntent,
    _fold_accents,
)
from code_intelligence.ontology.tags import BehavioralTag

logger = logging.getLogger(__name__)


# ── Question Intent Classification (Replaces GOVERNANCE_SIGNAL_TERMS) ────────

_GOVERNANCE_PATTERNS = [
    r"\bqui\s+peut\b",
    r"\bqui\s+a\s+(le\s+)?(droit|acces|accès|permission|pouvoir)\b",
    r"\bqui\s+est\s+autoris[eé]\b",
    r"\b(peut|peuvent)[-\s](?:t[-\s])?(il|elle|on|ils|elles)\s+(?:\w+\s+)?(?:voir|acceder|accéder|modifier|supprimer|creer|créer|declencher|déclencher|lancer|executer|exécuter|faire|purger|utiliser)\b",
    # Section 214: non-inverted French construction ("un utilisateur peut voir",
    # subject before the verb) -- the pattern above only covers the inverted
    # interrogative form ("peut-il voir"). Both ask the same access/permission
    # question; only the word order differs.
    r"\b(peut|peuvent)\s+(?:\w+\s+)?(?:voir|acceder|accéder|modifier|supprimer|creer|créer|declencher|déclencher|lancer|executer|exécuter|faire|purger|valider|approuver|utiliser)\b",
    r"\b(a|ont)[-\s]t[-\s](il|elle|ils|elles)\s+le\s+droit\b",
    r"\b(verrou|verrouill[eé]|bloqu[eé]|interdit|restreint|non[\s-]modifiable|lecture[\s-]seule|readonly)\b",
    r"\b(regle|règle|ir\.rule|ir_rule|securite|sécurité|acl|permission)\b",
    r"\b(?:base\.group_\w+|group_[a-z0-9_]+)\b",
    r"\b(approbation|approuver|valider|validation|signer|signature)\b",
    r"\b(plafond|seuil|limite\s+montant|depasse|dépasse)\b",
    r"\b(masqu[eé]|cach[eé]|invisible|visibilit[eé])\b",
    r"\b(?:n['’]|ne\s+)(?:apparait|appara[iî]t|s['’]affiche)\b",
    r"\b(?:apparait|appara[iî]t|s['’]affiche)[-\s]t?[-\s]*(?:il|elle|ils|elles)?\s+pas\b",
    r"\b(?:n['’]est\s+pas|pas|non)\s+visible\b",
    r"\b(?:empecher|empêcher|bloquer|interdire|restreindre)\s+l['’]acces\b",
    # Section 208-bis: troubleshooting questions ("je n'arrive pas à démarrer/valider")
    # express an access/governance problem even without explicit governance keywords.
    r"(?:n.arrive|ne\s+(?:peut|peux|parvien[st])\s+pas|impossible|empeche|empêche)\s.*?(?:demarrer|démarrer|valider|approuver|confirmer|creer|créer|modifier|supprimer|lancer)",
    r"(?:empeche|empêche|bloque|interdit|propose)\s.*?(?:supprimer|suppression|modifier|modification|creer|créer|creation|création)",
    # Section 208-bis: explicit condition inspection ("conditions vérifiées par action_X")
    r"\bconditions?\s+(?:verifiees?|vérifiées?|requises?|necessaires?|nécessaires?)\b",
    # Section 208-bis: direct method name reference (action_demarrer, action_valider, etc.)
    r"\baction_[a-z_]+\b",
    r"\b(que\s+se\s+passe[-\s]t[-\s]il|qu['’]arrive[-\s]t[-\s]il)\s+(?:si|lorsqu|quand)\b",
    r"\bvaleur\s+non\s+reconnue\b",
]

_WORKFLOW_PATTERNS = [
    r"\b(etape|étape|workflow|cycle\s+de\s+vie|statut|etat|état)\b",
    r"\b(transition|passer\s+de|bouton|action_valider|action_)\b",
    r"\b(brouillon|draft|confirm[eé]e?s?|annul[eé]e?s?|valid[eé]e?s?)\b",
    r"\b(dans\s+quel\s+cas|dans\s+quelles\s+conditions)\b",
    r"\b(?:g[eé]n[eé]ration|cr[eé]ation)\s+(?:de\s+|d['’]\s*)?(?:facture|commande|livraison|section)\b",
    r"\b(determine|détermine)[-\s]t[-\s]il\b",
    r"\b(proposer?|recherche)\s+a\s+la\s+purge\b",
]

_CALCULATION_CODE_PATTERNS = [
    r"\b(calcul[eé]|formule|compute|d[eé]pend|impact|recalcul)\b",
]

# Section 399 (todo/contexte.txt): split off from the group above. Bare
# financial vocabulary ("montant total", "somme", "taxe"...) is ambiguous
# between a code-level computation question and a live-data aggregation
# question -- "montant total des ventes" is answered by an ORM query, not a
# compute-field trace.
_CALCULATION_AMOUNT_PATTERNS = [
    r"\b(montant\s+total|somme|prix|taxe|tva|pourcentage)\b",
]

_INHERITANCE_PATTERNS = [
    r"\b(heritage|héritage|inherit|override|surcharg[eé]e?s?|surcharger|cascade|mro|classe\s+m[eè]re|classe\s+parente)\b",
    r"\b(r[eé]utilise[-\s]t[-\s]il|[eé]tend[-\s]t[-\s]il|modifie[-\s]t[-\s]il)\b",
    r"\bmod[eè]le\s+(?:concret|abstrait|standard|natif|existant)\b",
    r"\b(?:propres?|nouveaux?)\s+mod[eè]les?\b",
    r"\b(?:mod[eè]les?|champs?|m[eé]thodes?)\s+(?:sont\s+)?(?:modifi[eé]e?s?|[eé]tendue?s?)\b",
    r"\b(super\(|arbre\s+d'heritage|arbre\s+d'héritage)\b",
]

_AUTOMATION_PATTERNS = [
    r"\b(action\s+automatique|automatisation|cron|declencheur|déclencheur|base\.automation|ir\.actions\.server)\b",
    r"\b(automatiquement|en\s+arriere[- ]plan|tache\s+planifiee|tâche\s+planifiée)\b",
]

_ERP_DATA_PATTERNS = [
    r"\b(combien\s+d(?:e\b|['\u2019])|liste\s+des|donne[- ]moi\s+les|quels\s+sont\s+les\s+(derniers|clients|factures|devis|avoirs))\b",
    r"\b(montant\s+total\s+des\s+ventes|chiffre\s+d'affaires|ca\s+de|dans\s+la\s+base)\b",
]

# Bloc 17 (todo/contexte.txt section 645) : vocabulaire de localisation UI
# ("ou se trouve/accede-t-on/dans quel onglet/ou puis-je trouver/comment
# naviguer"), distinct du vocabulaire "comment faire pour X" (action metier,
# reste DOCUMENTARY_POLICY -- voir TestBenchmarkRegressionPin, DOC-01/02/03/
# 04/10). Verifie deliberement APRES governance/workflow dans la cascade :
# "bouton"/transitions doivent rester WORKFLOW_STATE, un "menu" incident dans
# une question de gouvernance doit rester GOVERNANCE_SECURITY.
_NAVIGATION_PATTERNS = [
    r"\b(?:ou|où)\s+se\s+trouve\b",
    r"\b(?:ou|où)\s+puis[-\s]je\s+trouver\b",
    r"\bcomment\s+(?:acceder|accéder)\s+(?:a|à)\b",
    r"\bdans\s+quel\s+onglet\b",
    r"\bcomment\s+naviguer\b",
]


_DOC_ANCHOR_PATTERNS = [
    r"\b(selon\s+le\s+wiki|dans\s+le\s+wiki|wiki\s+interne|guide\s+utilisateur|documentation|procedure|procédure)\b",
    r"\b(ou\s+est\s+documente|où\s+est\s+documenté|politique\s+interne)\b",
]


def has_documentary_anchor(folded_question: str) -> bool:
    """Single source of truth for 'does this question carry an explicit
    documentary anchor' (wiki/documentation/guide utilisateur/procédure/
    politique interne). Takes an already accent-folded, lowercased question.
    """
    return any(re.search(p, folded_question) for p in _DOC_ANCHOR_PATTERNS)


_WEAK_PROCESS_SIGNALS = [
    r"\b(process|processus|procedure|procédure|demarche|démarche|deroulement|déroulement|fonctionne|fonctionnement|se\s+passe|ca\s+marche|ça\s+marche)\b",
]


def classify_question_intent(
    question: str,
    resolved_concept: Optional[ResolvedConcept] = None,
    G: Optional[Any] = None,
) -> QuestionIntent:
    """
    Classifies the user query into a structured QuestionIntent.
    Combines text patterns, resolved concept properties, and graph ontology tags.
    """
    folded = _fold_accents(question)

    # 1. Check explicit documentary anchors (e.g. DOC-08)
    if has_documentary_anchor(folded):
        # Unless it specifically asks a quantitative query alongside
        if not any(re.search(p, folded) for p in _ERP_DATA_PATTERNS):
            return QuestionIntent.DOCUMENTARY_POLICY

    # 2-3. Governance vs. workflow disambiguation
    governance_hits = sum(1 for p in _GOVERNANCE_PATTERNS if re.search(p, folded))
    workflow_hits = sum(1 for p in _WORKFLOW_PATTERNS if re.search(p, folded))

    if workflow_hits >= 1 and governance_hits == 0:
        return QuestionIntent.WORKFLOW_STATE

    if workflow_hits >= 1 and governance_hits >= 1:
        return QuestionIntent.WORKFLOW_STATE

    if governance_hits >= 1:
        return QuestionIntent.GOVERNANCE_SECURITY

    # 4. Check unambiguous calculation/compute code patterns
    if any(re.search(p, folded) for p in _CALCULATION_CODE_PATTERNS):
        return QuestionIntent.CALCULATION_LOGIC

    # 5. Check inheritance / override patterns
    if any(re.search(p, folded) for p in _INHERITANCE_PATTERNS):
        return QuestionIntent.INHERITANCE_STRUCTURE

    # 6. Check automation / server action patterns
    if any(re.search(p, folded) for p in _AUTOMATION_PATTERNS):
        return QuestionIntent.AUTOMATION_ACTION

    # 7. Check quantitative / ERP live data patterns
    if any(re.search(p, folded) for p in _ERP_DATA_PATTERNS):
        return QuestionIntent.ERP_DATA_QUERY

    # 7bis. Check ambiguous calculation/financial-amount vocabulary
    if any(re.search(p, folded) for p in _CALCULATION_AMOUNT_PATTERNS):
        return QuestionIntent.CALCULATION_LOGIC

    # 8. Concept + Graph Tag affinity fallback
    if resolved_concept and resolved_concept.is_resolved and G is not None:
        has_weak_process_signal = any(re.search(p, folded) for p in _WEAK_PROCESS_SIGNALS)
        if has_weak_process_signal:
            for model_name in resolved_concept.resolved_models:
                model_node = f"model:{model_name}"
                if model_node in G:
                    b_tags = G.nodes[model_node].get("behavioral_tags", [])
                    if BehavioralTag.WORKFLOW_RULE.value in b_tags:
                        return QuestionIntent.WORKFLOW_STATE

    # 8bis. Bloc 17 (todo/contexte.txt section 645) : localisation UI
    # ("ou se trouve", "comment accede-t-on", ...) -- verifie juste avant le
    # fallback documentaire, jamais avant governance/workflow/calcul/
    # heritage/automation/erp_data qui ont deja tous eu leur chance ci-dessus.
    if any(re.search(p, folded) for p in _NAVIGATION_PATTERNS):
        return QuestionIntent.NAVIGATION_HOWTO

    # 9. No explicit code intelligence signal found
    return QuestionIntent.DOCUMENTARY_POLICY


def concept_suggests_code_intelligence_v2(
    question: str,
    resolved_concept: Optional[ResolvedConcept],
    G: Optional[Any] = None,
) -> bool:
    """
    Principled replacement for _concept_suggests_code_intelligence() / GOVERNANCE_SIGNAL_TERMS.

    Evaluates whether a query with a resolved concept should route to CODE_INTELLIGENCE:
      - Returns False if concept is unresolved.
      - Returns False if query is explicitly anchored to documentation (e.g. DOC-08).
      - Returns True if classified intent is a Code Intelligence domain.
    """
    if resolved_concept is None or not getattr(resolved_concept, "is_resolved", False):
        return False

    import sys
    ip_mod = sys.modules.get("code_intelligence.investigation")
    classifier_fn = getattr(ip_mod, "classify_question_intent", classify_question_intent) if ip_mod else classify_question_intent
    intent = classifier_fn(question, resolved_concept, G)

    if intent in (QuestionIntent.DOCUMENTARY_POLICY, QuestionIntent.ERP_DATA_QUERY):
        return False

    return True
