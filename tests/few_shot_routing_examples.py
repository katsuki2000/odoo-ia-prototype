# -*- coding: utf-8 -*-
"""
J18-J19: Few-shot routing examples covering ambiguous cases at the boundary
of the 4 branches (DOCUMENTAIRE, DONNEES_ERP, HYBRIDE, CODE_INTELLIGENCE).

Each example has:
  - question: the user's natural-language query
  - expected_route: the correct branch
  - rationale: why this route is correct (for documentation and review)
  - conflict_notes: which branches compete and how to resolve

The conflict resolution policy is:
  CODE_INTELLIGENCE > DONNEES_ERP > HYBRIDE > DOCUMENTAIRE

Rationale: Code is the source of truth for governance questions.
If a question touches both code-level security (ir.rule, sudo, locks)
AND wiki documentation, the code branch must prime because the wiki
may be stale or incomplete. ERP data primes over pure documentation
when live numbers are requested. HYBRIDE is for genuine doc+data needs.
"""

FEW_SHOT_ROUTING_EXAMPLES = [
    # =========================================================================
    # 1. Pure CODE_INTELLIGENCE — unambiguous governance/security questions
    # =========================================================================
    {
        "question": "Qui a le permission d'approuver un avoir de 25 000€ pour un client normal ?",
        "expected_route": "code_intelligence",
        "rationale": "Approval rights are determined by Python locks + ir.rule, not wiki.",
        "conflict_notes": "Could match 'qui a le permission' (doc_keywords) but code_intel_keywords takes priority.",
    },
    {
        "question": "Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?",
        "expected_route": "code_intelligence",
        "rationale": "Approval rules = ir.actions.server + sudo bypass. Code is source of truth.",
        "conflict_notes": "'mêmes règles' matches _AUTOMATION_PATTERN; 'règles d'approbation' is code_intel.",
    },
    {
        "question": "Un utilisateur membre du groupe régional peut-il voir un avoir de 80 000€ ?",
        "expected_route": "code_intelligence",
        "rationale": "ir.rule visibility question. Deterministic can_view_amount() answers this.",
        "conflict_notes": "Contains a monetary amount but it's a visibility question, not an ERP data lookup.",
    },

    # =========================================================================
    # 2. Pure DONNEES_ERP — unambiguous data lookups
    # =========================================================================
    {
        "question": "Combien de factures impayées avons-nous ce mois-ci ?",
        "expected_route": "donnees_erp",
        "rationale": "Quantitative data lookup from live ERP. No governance/code analysis needed.",
        "conflict_notes": "No conflict — purely transactional.",
    },
    {
        "question": "Quel est le montant total des ventes de janvier 2026 ?",
        "expected_route": "donnees_erp",
        "rationale": "Aggregate financial query. ORM agent must query the database.",
        "conflict_notes": "No conflict.",
    },

    # =========================================================================
    # 3. Pure DOCUMENTAIRE — unambiguous documentation/procedure questions
    # =========================================================================
    {
        "question": "Quelle est la procédure de validation des notes de frais selon le wiki ?",
        "expected_route": "documentaire",
        "rationale": "Explicitly references the wiki. Procedure documentation, not code.",
        "conflict_notes": "'procédure de validation' could match code_intel, but 'selon le wiki' anchors it to doc.",
    },
    {
        "question": "Comment configurer le module de comptabilité dans Odoo 17 ?",
        "expected_route": "documentaire",
        "rationale": "Configuration guide = documentation, not code analysis or data lookup.",
        "conflict_notes": "No conflict.",
    },

    # =========================================================================
    # 4. AMBIGUOUS: Code Intelligence vs Documentaire
    #    Policy: CODE_INTELLIGENCE wins (code is source of truth for governance)
    # =========================================================================
    {
        "question": "Qui peut approuver un avoir de plus de 500 000 Ar ?",
        "expected_route": "code_intelligence",
        "rationale": "Approval authority is enforced in Python code (UserError locks), not just documented. "
                     "Even if a wiki page describes the policy, the code is the enforced truth.",
        "conflict_notes": "CONFLICT: 'qui peut' matches doc_keywords, 'approuver' + 'avoir' matches code_intel. "
                         "Resolution: code_intel wins per policy (code > wiki for governance).",
    },
    {
        "question": "Quelles sont les conditions pour valider une demande de congé urgente ?",
        "expected_route": "code_intelligence",
        "rationale": "Validation conditions are Python-enforced (UserError in hr_leave.py). "
                     "Wiki may describe the policy but code is the actual enforcement.",
        "conflict_notes": "CONFLICT: 'quelles sont les conditions' sounds documentary, but 'valider' + "
                         "'demande de congé' is a code-level governance question. Resolution: code_intel.",
    },
    {
        "question": "Quel est le rôle du responsable comptable dans le processus d'approbation des avoirs ?",
        "expected_route": "code_intelligence",
        "rationale": "The role in the approval process is defined by Python code locks and group membership, "
                     "not by a wiki role description.",
        "conflict_notes": "CONFLICT: 'quel est le rôle' matches doc_keywords. But 'responsable comptable' + "
                         "'processus d'approbation des avoirs' is governance/code. Resolution: code_intel.",
    },

    # =========================================================================
    # 5. AMBIGUOUS: Code Intelligence vs Données ERP
    #    Policy: CODE_INTELLIGENCE wins (governance question, not data lookup)
    # =========================================================================
    {
        "question": "Le montant total des avoirs de ce trimestre dépasse-t-il le seuil d'approbation du N+2 ?",
        "expected_route": "code_intelligence",
        "rationale": "The core question is about the approval threshold (code-level), not the aggregate amount. "
                     "The amount is context, not the answer.",
        "conflict_notes": "CONFLICT: 'montant total' matches erp_keywords, 'seuil d'approbation' is code_intel. "
                         "Resolution: code_intel wins — the question asks about the threshold, not the total.",
    },
    {
        "question": "Combien d'avoirs ont été approuvés sans passer par le responsable comptable ?",
        "expected_route": "donnees_erp",
        "rationale": "This is a data audit query — counting records that bypassed a control. "
                     "Requires ORM search with domain filters, not code analysis.",
        "conflict_notes": "CONFLICT: 'responsable comptable' + 'approuvés' sounds code_intel, but 'combien' "
                         "makes this a quantitative data lookup. Resolution: donnees_erp wins — the answer is a number.",
    },

    # =========================================================================
    # 6. AMBIGUOUS: Documentaire vs Données ERP (HYBRIDE)
    # =========================================================================
    {
        "question": "Quelle est la procédure de gestion des tickets et combien en avons-nous en cours ?",
        "expected_route": "hybride",
        "rationale": "Two distinct sub-questions: procedure (doc) + count (ERP data). Genuine hybrid.",
        "conflict_notes": "HYBRIDE is correct — both branches contribute non-overlapping information.",
    },

    # =========================================================================
    # 7. TRICKY: Governance vocabulary but pure documentation intent
    # =========================================================================
    {
        "question": "Où est documentée la politique d'approbation des avoirs dans le wiki interne ?",
        "expected_route": "documentaire",
        "rationale": "The user is asking WHERE the policy is documented, not WHAT the policy enforces. "
                     "The answer is a wiki page reference, not code analysis.",
        "conflict_notes": "TRICKY: 'approbation des avoirs' matches code_intel strongly, but "
                         "'où est documentée' + 'wiki interne' anchors this to documentation. "
                         "Resolution: documentaire wins — intent is document-retrieval, not governance.",
    },
    {
        "question": "Selon la politique interne, qui devrait approuver les avoirs VIP ?",
        "expected_route": "documentaire",
        "rationale": "'Selon la politique interne' explicitly defers to documented policy, not code enforcement. "
                     "The user wants the written rule, not the technical implementation.",
        "conflict_notes": "TRICKY: 'approuver les avoirs VIP' is pure code_intel territory, but "
                         "'selon la politique interne' anchors to doc. Resolution: documentaire.",
    },

    # =========================================================================
    # 8. EDGE CASE: question mentioning code but actually needing ERP data
    # =========================================================================
    {
        "question": "Combien de demandes d'achat de plus de 15 000€ ont été traitées par daf@societe.com ?",
        "expected_route": "donnees_erp",
        "rationale": "Despite mentioning a specific email (which is a hardcoded bypass), this is a "
                     "quantitative audit query. The answer is a count from the database.",
        "conflict_notes": "EDGE CASE: 'daf@societe.com' is a code-level hardcoded validator, but "
                         "'combien de demandes' makes this a data lookup. Resolution: donnees_erp.",
    },

    # =========================================================================
    # 9. REGRESSION: doc ANCHOR (not a DOC_KEYWORD) + quantitative -> HYBRIDE
    #    Found in review: is_hybrid only checked DOC_KEYWORDS, so anchors
    #    like "où est documenté" / "dans le wiki" / "wiki interne" that are NOT
    #    also in DOC_KEYWORDS silently fell through to DOCUMENTAIRE instead of
    #    HYBRIDE. Only "selon le wiki" worked by coincidence (present in both
    #    lists). Fixed by widening is_hybrid to (DOC_KEYWORDS or DOC_ANCHORS).
    # =========================================================================
    {
        "question": "Où est documenté combien de tickets sont encore en cours ?",
        "expected_route": "hybride",
        "rationale": "Two needs at once: pointer to the documented procedure (doc anchor 'où est "
                     "documenté') AND a live count of open tickets (quantitative). Genuine hybrid, "
                     "not pure documentaire.",
        "conflict_notes": "REGRESSION: 'où est documenté' is a DOC_ANCHOR but not a DOC_KEYWORD; "
                         "before the fix this silently routed to documentaire because is_hybrid only "
                         "looked at DOC_KEYWORDS. Resolution: hybride.",
    },
]


# =============================================================================
# Conflict resolution policy 
# =============================================================================
CONFLICT_RESOLUTION_POLICY = """
## Politique de résolution de conflit inter-branches

### Règle 1 : Code > Wiki pour les questions de gouvernance
Si une question porte sur QUI peut faire QUOI (approbation, validation, accès,
visibilité), le code Python et les ir.rule sont la source de vérité, pas le wiki.
Le wiki peut être obsolète ; le code est ce qui s'exécute réellement.

→ Route : CODE_INTELLIGENCE

### Règle 2 : Données ERP > Code pour les questions quantitatives
Si la question demande un NOMBRE, un MONTANT AGRÉGÉ, un STATUT d'enregistrement
spécifique, ou une LISTE d'enregistrements, c'est une requête de données même si
elle mentionne des concepts de gouvernance comme contexte.

→ Route : DONNEES_ERP

### Règle 3 : Ancrage explicite au wiki
Si la question contient un ancrage explicite vers la documentation
("selon le wiki", "où est documenté", "politique interne", "procédure"),
elle est traitée comme documentaire SAUF si elle demande aussi des données
quantitatives (auquel cas → HYBRIDE).

→ Route : DOCUMENTAIRE ou HYBRIDE

### Règle 4 : HYBRIDE uniquement si deux sous-questions distinctes
HYBRIDE n'est utilisé que lorsque la question contient explicitement deux
sous-questions adressant deux branches différentes. Une simple mention
d'un concept ERP dans une question de gouvernance n'est PAS hybride.

→ Route : HYBRIDE (rare)

### Ordre de priorité global
CODE_INTELLIGENCE > DONNEES_ERP > HYBRIDE > DOCUMENTAIRE
"""
