import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code_intelligence.agent.resolver import resolve_business_term
from code_intelligence.graph.loader import get_code_intelligence_graph

print("Loading graph...")
G = get_code_intelligence_graph()
print(f"Graph: {G.number_of_nodes()} nodes\n")

queries = [
    'Qui peut approuver un avoir de 25000€ ?',
    'Comment fonctionne la facturation électronique ?',
    'demande de congé urgent',
    'purchase order approval',
    'mise à disposition de matériel',
]

extra_cases = [
    "avoirs",                    # bug n°1 : doit résoudre en alias, pas fuzzy res.partner
    "avoir",
    "congé",
    "congés",
    "démande de congé",          # variante avec accent parasite, doit rester robuste
    "mise à disposition",        # multi-mots, ordre préservé
    "disposition à mise",        # ordre inversé -> ne doit PAS matcher static_alias (sinon alerte faux-positif)
    "document Deep",             # bug (b) STATUT PARTIELLEMENT REFERME  -- formulation informelle, doit résoudre vers custom.deep.document
    "le document Deep",          # même bug, variante avec article -- confirme si le problème tient à la formulation exacte
]

print("=== Standard Queries ===")
for q in queries:
    r = resolve_business_term(q, G)
    print(f"Q: {q!r}")
    print(f"   -> models={r.resolved_models[:3]}  conf={r.confidence}  step={r.source_step}")
    print(f"      reason={r.reason[:120]}")

print("\n=== Non-Regression Extra Cases ===")
for q in extra_cases:
    r = resolve_business_term(q, G)
    print(f"Q: {q!r:25s} -> source={r.source_step:18s}, modèles={r.resolved_models}, résolu={r.is_resolved}")

# mesure prealable AVANT toute ecriture de NATIVE_MODEL_SYNONYMS -- diagnostic du mismatch linguistique de l'index fuzzy (_build_fuzzy_index indexe Model.description/Field.label/Menu.name, probablement en anglais pour les modeles Odoo natifs) sur les modeles candidats de la Phase 1 proposee par l'utilisateur (Vente/Achat/Stock). Lecture seule : aucun code de production touche, ce script ne fait qu'appeler resolve_business_term() en lecture sur le graphe deja charge.
native_model_candidates = [
    "qui peut valider une commande de vente",
    "qui peut approuver une commande d'achat",
    "quel est le stock disponible",
    "commande de vente",
    "devis",
    "vente",
    "commande d'achat",
    "achat",
    "livraison",
    "reception",
    "mouvement de stock",
    "produit",
    "stock",
]

print("\n=== Section 307 : Phase 1 candidats NATIVE_MODEL_SYNONYMS (mesure prealable) ===")
for q in native_model_candidates:
    r = resolve_business_term(q, G)
    print(f"Q: {q!r:45s} -> source={r.source_step:18s}, modèles={r.resolved_models}, conf={r.confidence}, résolu={r.is_resolved}")
    # Section 309 (todo/contexte.txt) : un 'unresolved' affiche peut cacher
    # deux situations tres differentes -- aucun candidat du tout (Step 4,
    # 'No business alias or graph model match found'), ou une ambiguite
    # massive deja presente (Step 2/3, 'Ambiguous fuzzy candidates (...)',
    # arbitrage LLM indisponible hors-ligne) -- cas reel decouvert sur 'stock'
    # seul. Le champ `reason` distingue les deux ; necessaire avant de decider
    # quels candidats restants sont sans risque de collision pour
    # NATIVE_MODEL_SYNONYMS.
    print(f"   reason: {r.reason}")

# Section 308 (todo/contexte.txt) : diagnostic cible des deux faux positifs
# decouverts en section 308 ('achat' -> custom.asset.loan conf 1.0 ;
# 'mouvement de stock' -> product.product conf 0.75) -- dump des entrees
# brutes (label, model) de _build_fuzzy_index() contenant les sous-chaines
# en cause, pour identifier la source exacte AVANT d'ecrire
# NATIVE_MODEL_SYNONYMS (risque de collision de score sinon). Lecture seule :
# appelle une fonction privee du module en lecture, ne modifie rien.
from code_intelligence.agent.matching import _build_fuzzy_index

print("\n=== entrees d'index contenant 'achat' ===")
idx = _build_fuzzy_index(G)
for label, model in idx:
    if "achat" in label:
        print(f"  model={model!r:35s} <- label={label!r}")

print("\n=== entrees d'index contenant 'stock' ===")
for label, model in idx:
    if "stock" in label:
        print(f"  model={model!r:35s} <- label={label!r}")
