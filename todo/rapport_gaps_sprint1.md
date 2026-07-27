# Rapport de Gaps & Analyse de Couverture — Sprint 1 (E1)

**Date :** 27 juillet 2026  
**Auteur :** Assistant IA Odoo (MiroKE)  
**Corpus d'évaluation :** Jeu de 9 modules adversariaux v2  
**Artefacts associés :** [verbatim_responses_sprint1.md](file:///home/user/odoo-ia-prototype/todo/verbatim_responses_sprint1.md), [verbatim_responses_sprint1.json](file:///home/user/odoo-ia-prototype/todo/verbatim_responses_sprint1.json)

---

## 1. Synthèse Exécutive

L'exécution du benchmark de Sprint 1 sur les 9 questions adversariales fournit un diagnostic empirique sans ambiguïté : **le RAG vectoriel et la recherche naïve par nom de modèle échouent sur 100% des cas complexes**, confirmant l'hypothèse de départ du projet.

| Métrique | Score Obtenu | Cible Sprint 2 |
|---|---|---|
| **Taux de succès global (Vérité Terrain)** | **0 / 9 (0%)** | 9 / 9 (100%) |
| **Taux de Sourcing Vérifiable** | **0 / 9 (0%)** | 9 / 9 (100%) |
| **Score de Couverture Moyen par Module** | **22%** | >85% |
| **Taux de Faux Positifs (Hallucination Générale)** | **77% (7/9)** | 0% |

---

## 2. Analyse des Causes Racines par Catégorie

### Gap 1 : Résolution des Noms Fonctionnels → Noms Techniques Odoo
* **Symptôme** : L'agent cherche `account.invoice`, `client.vip`, `hr.holidays.request`, `stock.request` au lieu de mapper vers les vrais modèles (`account.move`, `hr.leave`, `custom.asset.loan`).
* **Cause Racine** : Absence d'un dictionnaire/outil de désambiguïsation fonctionnelle en amont de la requête d'outil composite (`resoudre_nom_technique_vers_role`).

### Gap 2 : Détection des Verrous Codés en Dur dans les Méthodes Python (Semgrep)
* **Symptôme** : Sur la demande d'achat de 15 000€ (Q3.1), l'agent réponds par des banalités sur les directeurs financiers sans voir la liste `_VALIDATEURS_EXCEPTIONNELS`.
* **Cause Racine** : L'extracteur Python actuel extrait les définitions de méthodes et champs, mais n'utilise pas encore de règles Semgrep dédiées pour extraire les constantes de listes d'e-mails/logins en dur.

### Gap 3 : Logique stockée en Données (`ir.actions.server` / `sudo()`)
* **Symptôme** : Sur les avoirs fournisseurs (Q5.1), l'agent ne détecte pas le bypass automatique pour les fournisseurs 42, 108, 231.
* **Cause Racine** : Logique métier absente des fichiers Python, stockée en XML/données dans `ir.actions.server`. Couverture planifiée en Sprint 2 (Stories S2.3 & S2.4).

### Gap 4 : Algorithme de combinaison des `ir.rule` (ET global / OU groupe)
* **Symptôme** : Sur les questions Q6.1 et Q6.2, l'agent conclut que l'utilisateur ne peut pas voir l'avoir de 80k€ car les groupes n'ont pas de permissions de lecture explicites.
* **Cause Racine** : Absence du résolveur runtime `with_user(utilisateur_test).search()` (Stories S2.1 & S2.2). L'agent a tenté d'analyser les règles sans exécuter l'algorithme Odoo.

### Gap 5 : Détection d'Ignorance & Dispatch Dynamique (`getattr`)
* **Symptôme** : Sur Q9.1, l'agent répond qu'il ne trouve pas le module au lieu d'isoler la ligne `getattr` et d'exprimer son incertitude.
* **Cause Racine** : Pas de règle de détection des appels réflexifs (`getattr`, `eval`, `exec`) comme verrous non classifiés.

### Gap 6 : Non-respect de la Discipline de Fidélité (Meublage du LLM)
* **Symptôme** : Lorsque l'outil composite renvoie un résultat vide ou non trouvé, le LLM meuble la réponse avec sa culture générale Odoo/entreprise plutôt que de répondre *"Information non disponible dans le graphe"*.
* **Cause Racine** : Manque de sévérité dans le prompt de synthèse et absence du vérificateur de fidélité automatisé (Fidelity Checker).

---

## 3. Score de Couverture par Module (S1.6)

Score de couverture = (Constructions Sécurité/Workflow extraites et résolues) / (Total Constructions Métier du Module).

| Module Adversarial | Constructions Métier | Couverture Actuelle | Gap Principal |
|---|---|---|---|
| `custom_credit_note_approval` | 3 (Seuil 5k, dépendance hr, ACL) | 33% | Seuil Python non extrait dans le graphe |
| `custom_credit_note_approval_regional` | 2 (Seuil 20k, N+2) | 0% | Navigation hiérarchique `parent_id.parent_id` non résolue |
| `custom_credit_note_approval_vip` | 2 (Bypass VIP, call super) | 0% | Logique de bypass Python non traduite en arête |
| `custom_hr_leave_workflow` | 2 (Vérification solde, msg erreur exact) | 0% | Message d'erreur de `ValidationError` non capturé |
| `custom_purchase_request` | 2 (Liste e-mails dur, seuil 10k) | 50% | Liste e-mails `_VALIDATEURS_EXCEPTIONNELS` manquée |
| `custom_asset_loan` | 2 (Ref croisée purchase, séparation rôles) | 50% | Seuil 2000€ inter-module non lié |
| `custom_automation_traps` | 2 (`ir.actions.server`, `sudo()` fournisseurs) | 0% | `ir.actions.server` non indexé |
| `custom_credit_note_visibility_rules` | 3 (Règle globale, 50k régio, illimité natio) | 66% | Règles XML extraites mais algorithme ET/OU non résolu |
| `custom_expense_reimbursement_indirect` | 1 (Gate `getattr` dynamique) | 0% | Pattern non reconnu et non signalé comme incertain |
| **MOYENNE GLOBALE** | — | **22%** | — |

---

## 4. Bilan du Sourcing (S1.6)

* **Exigence (§3)** : Tout résultat produit doit être accompagné d'une source citable (fichier + ligne, ou identifiant XML).
* **Constat** : 100% des réponses verbatim ont ajouté le tag générique `[Source: Graphe de Connaissances Code Intelligence]` sans aucune précision de fichier, de ligne ou d'enregistrement XML.
* **Action pour Sprint 2** : Modifier le contrat de sortie des outils composites pour qu'ils retournent un dictionnaire d'objets `SourceReference(file, line, xml_id)` structurés, et interdire au LLM de valider une réponse sans citation précise.

---

## 5. Recommandations d'Ordre de Traitement pour le Sprint 2 (E2)

Conformément à la Definition of Ready, le backlog du Sprint 2 est réaligné directement sur ce rapport :

1. **Priorité 1 (Sécurité & Droits `ir.rule`) — Stories S2.1 & S2.2 (5 pts)** :
   * Implémenter le wrapper `with_user().search()` pour résoudre l'algorithme ET/OU sans bug.
2. **Priorité 2 (Logique en Données `ir.actions.server`) — Stories S2.3 & S2.4 (7 pts)** :
   * Indexer `ir.actions.server` et `base.automation` + lecture LLM bornée du champ `code` avec tag de confiance faible.
3. **Priorité 3 (Verrous Python & Semgrep) — Stories S2.5 & S2.6 (5 pts)** :
   * Rédiger les règles Semgrep pour capturer les listes d'e-mails en dur (`_VALIDATEURS_EXCEPTIONNELS`), les `ValidationError` et les `getattr` dynamiques (module 9).
4. **Priorité 4 (Discipline de Sourcing & Fidelity Checker) — Stories S2.7 & S2.8 (4 pts)** :
   * Imposer le sourcing fichier+ligne structuré et interdire le meublage du LLM.
