"""
code_intelligence/ci_agent_node/constants.py

Static text/display constants for the CI agent node, extracted from the
former ci_agent_node.py monolith (refactor, see todo/contexte.txt).
"""

_EXECUTION_FAILURE_NOTICE = (
    "\n\n[ATTENTION] Une ou plusieurs analyses Code Intelligence n'ont pas pu "
    "s'ex\u00e9cuter correctement pour cette question (panne technique d'un ou "
    "plusieurs outils). La r\u00e9ponse ci-dessus peut donc \u00eatre incompl\u00e8te ; "
    "n'y voyez pas une absence confirm\u00e9e d'information."
)

# ── Human-readable labels for sources built from tool observations ─────────
# (section: réponses trop techniques, todo/contexte.txt) -- used only for
# SourceReference.title in the dépliant; falls back to the raw tool name
# for anything not listed here (e.g. new tools added later).
_CI_TOOL_DISPLAY_NAMES = {
    "analyze_security_locks": "Verrous de sécurité (code Python)",
    "analyze_server_actions": "Actions serveur / automatisations",
    "analyze_method_override_chain": "Chaîne de surcharge de méthode",
    "who_has_access_to": "Matrice d'accès (ACL)",
    "evaluate_record_rules": "Règles d'enregistrement (ir.rule)",
    "can_view_amount_v2": "Vérification déterministe du montant",
    "analyze_data_constraints": "Contraintes de données (Semgrep)",
    "field_change_impact": "Impact de modification de champ",
    "button_execution_path": "Chemin d'exécution du bouton",
    "trace_full_inheritance": "Héritage complet du modèle",
    "describe_workflow": "Workflow (états)",
    "resolve_technical_name": "Résolution de rôle technique",
    "list_involved_modules": "Modules impliqués",
    "explain_decision_path": "Explication du chemin de décision",
    "read_source_code": "Lecture de code source",
}
