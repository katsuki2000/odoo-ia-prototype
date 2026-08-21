# Rapport de Benchmark — S4 / Jalon J1

**Date :** 03 juillet 2026
**Environnement :** Groq API (cloud, free tier)
**Protocole :** 30 questions soumises à chaque modèle, score qualitatif (1-5) basé sur la présence de mots-clés attendus dans la réponse.

---

## 1. Modèles testés

| Modèle | Provider | Équivalent local visé | Taille |
|--------|----------|----------------------|--------|
| **Llama 3.1 8B** | Groq (`llama-3.1-8b-instant`) | Hermes 3 8B Q4 / Mistral 7B Q4 | ~4.5 Go Q4 |
| **Llama 4 Scout 17B** | Groq (`meta-llama/llama-4-scout-17b-16e-instruct`) | N/A (testé pour référence) | ~10 Go Q4 |

> Les modèles cibles du plan (Mistral 7B, Hermes 3 8B, Phi-3.5 Mini) n'étant pas disponibles via Groq, le benchmark a porté sur les modèles Groq les plus proches en capacité. Le test local sur GPU (RTX 3060 12 Go) est prévu en S5-S6 une fois l'environnement Ubuntu installé.

---

## 2. Résultats globaux

| Modèle | Score moyen | Temps moyen/rép. | Tokens/s | Score total |
|--------|-----------|-----------------|---------|------------|
| Llama 3.1 8B | **2.03 / 5** | 3.79 s | 125.2 | 61 / 150 |
| Llama 4 Scout 17B | **2.03 / 5** | 1.18 s | 347.7 | 61 / 150 |

### 2.1 Scores par catégorie

| Catégorie | Questions | Llama 3.1 8B | Llama 4 Scout 17B |
|-----------|-----------|-------------|-------------------|
| **Documentaire** (PDF, wiki) | 10 | 1.9 / 5 | 2.2 / 5 |
| **Code source** | 8 | 3.4 / 5 | 3.0 / 5 |
| **ERP chiffré** | 8 | 1.4 / 5 | 1.4 / 5 |
| **Hors périmètre** (repli) | 4 | 1.0 / 5 | 1.0 / 5 |

---

## 3. Analyse détaillée

### 3.1 Questions documentaires (DOC-01 à DOC-10)

Les deux modèles produisent des réponses **génériques et correctes sur Odoo**, mais ne citent pas les documents spécifiques de MIRO KE (manuel de facturation, wiki interne). C'est **comportement attendu** : sans RAG, le modèle répond de mémoire, sans accès aux documents spécifiques.

**Exemple — DOC-05 « Qui peut approuver une mise à disposition ? » :**
> *Réponse Llama 3.1 :* « Je n'ai pas accès à la documentation interne de MIRO KE, mais je peux vous donner les informations générales sur Odoo 17... »

Les réponses sont prudentes et honnêtes, ce qui est positif pour un usage professionnel. Le score bas (1.9-2.2) est dû à l'absence de contexte documentaire — il sera résolu par l'intégration RAG en S5-S8.

### 3.2 Questions code source (CODE-01 à CODE-08)

Meilleur score des deux modèles (3.0-3.4/5). Les réponses sur la structure des modules Odoo sont correctes grace à la connaissance générale des modèles sur l'architecture Odoo.

**Llama 3.1 8B** est légèrement meilleur sur le code source (3.4 vs 3.0), mais les deux identifient correctement les modèles et fichiers clés.

### 3.3 Questions ERP chiffrées (ERP-01 à ERP-08)

Score faible (1.4/5) pour les deux modèles. Les réponses sont générales ou prudentes (« je n'ai pas accès aux données en temps réel »). **Comportement attendu** : le function calling ERP traitera ces questions à partir de S11.

### 3.4 Questions hors périmètre (HORS-01 à HORS-04)

Les modèles ne refusent pas systématiquement : ils tentent de répondre aux blagues et recettes, ou répondent de manière neutre. Le mécanisme de repli explicite (refus poli) devra être implémenté dans le prompt système + logique de routage (S9).

### 3.5 Function calling

Test supplémentaire : 4 questions de function calling soumises à Llama 3.1 8B :

| Question | Fonction identifiée | Paramètres | Correct ? |
|----------|-------------------|------------|-----------|
| Stock du produit "Portable X200" | `obtenir_stock` | `{produit: "Portable X200"}` | ✅ |
| Ventes client Dupont 2025 | `obtenir_ventes` | `{client: "Dupont", periode: "2025"}` | ✅ |
| Statut commande #1234 | `obtenir_statut_commande` | `{id_commande: 1234}` | ✅ |
| Total factures impayées | `obtenir_total_factures` | `{statut: "impayée"}` | ✅ |

**Résultat : 4/4 appels corrects.** Llama 3.1 8B démontre une excellente capacité de function calling native.

---

## 4. Synthèse et décision

### 4.1 Atteinte des objectifs du jalon

| Critère | Objectif | Résultat |
|---------|----------|----------|
| Score qualitatif | ≥ 3,5 / 5 | **2,03 / 5** (sans RAG) |
| Temps de réponse | ≤ 15 s | **3,79 s** (✅ largement sous la cible) |
| Jeu de test versionné | ✅ | 30 questions dans `benchmark_questions.json` |

> **Note :** L'objectif de score ≥ 3,5/5 sera atteignable uniquement **après intégration du RAG** (S5-S8) et du **function calling ERP** (S11-S12). Le benchmark S4 mesure le score **baseline** des modèles bruts — indispensable pour mesurer l'amélioration apportée par le pipeline complet.

### 4.2 Modèle retenu

**Modèle principal : Llama 3.1 8B (Groq → local Q4)**

Justification :
1. **Function calling natif** : 4/4 appels corrects, capacité essentielle pour le routage et l'appel ORM.
2. **Taille locale compatible** : une version Q4 tient dans ~5 Go VRAM sur la RTX 3060 (12 Go).
3. **Disponibilité sur Groq** : permet de développer et tester immédiatement sans GPU local.
4. **Score code source** : meilleur que Llama 4 Scout sur les questions de code (3.4 vs 3.0).

**Modèle secondaire à tester localement : Hermes 3 8B Q4**
- Fine-tuné spécifiquement pour le tool-use structuré
- À comparer avec Llama 3.1 8B une fois le GPU local disponible (S5)
- Si Hermes 3 se révèle supérieur en function calling → devient le modèle principal

**Modèle rejeté : Llama 4 Scout 17B**
- Trop volumineux pour la RTX 3060 (12 Go VRAM)
- Score global équivalent à Llama 3.1 8B (2.03 vs 2.03)
- Temps de réponse plus rapide sur Groq mais non pertinent pour le déploiement local

### 4.3 Prochaines étapes (S5)

1. Installation du GPU local (Ubuntu, CUDA, Ollama) — Lun 06/07
2. Téléchargement de **Llama 3.1 8B Q4** et **Hermes 3 8B Q4** via Ollama
3. Re-benchmark local pour confirmer les scores avec inférence locale
4. Début de l'extraction et du chunking des documents

---

## 5. Fichiers livrés

| Fichier | Description |
|---------|-------------|
| `tests/benchmark_questions.json` | Jeu de 30 questions de test (versionné) |
| `tests/benchmark_results.json` | Résultats bruts des benchmarks |
| `tests/benchmark_report.md` | Ce rapport d'analyse |
| `tests/benchmark_runner.py` | Script de benchmark reproductible |
