30 min 
# PARTIE 5 — Limites connues du plan

- **Inference cloud, pas locale (le point le plus important)** : le prototypage a date (B0 a Bloc 9) valide l'architecture et la methodologie de l'agent de Code Intelligence, mais entierement sur Groq (API cloud, `openai/gpt-oss-20b`, MoE 21B) — la contrainte de confidentialite fondatrice du projet n'est pas encore demontree en pratique. Modele local cible : Qwen3-14B via Ollama. Voir Bloc P3.
- **Budget de latence non representatif du deploiement final** : le chiffre mesure (p90=6.84s) reflete le temps algorithmique hors attente reseau Groq — pas une mesure de ce que donnera Qwen3-14B en local.
- **Fiabilite structurellement dependante d'un scaffolding deterministe lourd** : dispatch force, gating, garde-fous compensent les limites du modele. Caracteristique assumee de l'architecture — a nommer explicitement comme choix de conception dans le memoire. Le passage de 8B (llama-3.1-8b-instant, abandonne) a 14-21B (Qwen3-14B / gpt-oss-20b) reduit ce risque.
- **Volume et diversite du jeu adversarial encore limites** : 9 questions de base + modules custom synthetiques. Le Bloc P6 (vrai code MiroKE) reste la seule preuve qui compte a terme.
- **Infrastructure de production hors perimetre** : multi-tenant et stack de production (Qdrant, vLLM a charge) explicitement hors du planning actuel.
- **RAG documentaire non detaille dans ce plan** : le pipeline documentaire (PDF, wikis) du document source (Sprint B) n'apparait pas dans le detail, centre sur l'agent de Code Intelligence seul.

---

# PARTIE 6 — Ce que ce plan ne couvre pas

- **RAG documentaire** (Sprint B du document source) — chantier parallele non repris dans ce fichier.
- **Infrastructure multi-tenant / production** — explicitement hors perimetre de stage.

---

# PARTIE 7 — Perspectives (au-dela de la fin de stage)

- Fine-tuning cible (Option C du document source, differee a 12-18 mois) sur les patterns ou le modele echoue le plus souvent malgre le dispatch force (ex. synthese multi-volets, priorisation de findings contradictoires).
- Multi-tenant (isolation stricte entre clients, Qdrant en production) des qu'un deuxieme client rejoint le perimetre.
- Integration au RAG documentaire via le meme principe de routage/resolution de conflit (Bloc 6).
- Suite de regression OCA (Bloc P5) : piste de valorisation externe (publication, contribution communautaire).

---

# PARTIE 8 — Explicitement hors de ce planning

Ces points restent dans le plan source mais **ne doivent consommer aucun jour ci-dessus** tant que la condition de declenchement n'est pas remplie :

- **Interoperabilite multi-tenant** — hors scope tant que MiroKE reste l'unique client cible.
- **Infrastructure locale, POC demonstrable** — hors scope tant que le materiel local n'est pas arrive (voir Bloc P3 pour la validation d'inference locale elle-meme, distincte de ce point d'infrastructure de production).

---

# PARTIE 9 — Perimetre de validation du PoC : module Documentaire implemente mais non score

**Decision (2026-08-19)** : le PoC reste architecture sur 3 branches -- Code Intelligence, ERP, Documentaire (voir le diagramme dans `architecture.md`, non modifie) -- mais l'evaluation principale du PoC ne porte que sur un sous-ensemble explicite de cette architecture.

**Ce qui EST evalue** :
- Code Intelligence (agent, resolution de business terms, tracabilite des hops)
- ERP Runtime (donnees reelles, execution)
- Tracabilite des preuves (dossier de preuves, Evidence Builder)

**Ce qui est implemente mais explicitement HORS du perimetre de l'evaluation principale** :
- Module Documentaire (RAG classique -- embeddings, reranker, ingestion de documents) -- code non supprime, conserve tel quel, simplement non compte dans le score du PoC.
- Sa contribution a la branche HYBRIDE de `route()` (cas ou une question combine un terme documentaire/quantitatif) suit la meme regle : implementee, non scoree.

**Pourquoi cette decision, pas une suppression** : le module documentaire ne resout pas le probleme le plus risque du projet -- comprendre le comportement reel d'un code Odoo inconnu -- qui est deja couvert, largement resolu ailleurs (embeddings, reranking, qualite documentaire sont des problemes matures). Le sortir du perimetre de *validation* recentre l'evaluation sur ce qui est original et non demontre ailleurs, sans perdre le code ni la couverture de tests qui en depend deja (`test_hybrid_detects_doc_anchor_not_only_doc_keyword`, cas DOC/HYBRIDE de `tests/test_j18_routing_fewshot.py`).

**Argument de soutenance** : si la question "et les documents internes ?" est posee, la reponse est "l'architecture le permet deja, le module existe (voir le code et les tests), mais l'objectif du PoC etait de valider la comprehension du comportement reel d'Odoo -- la partie la plus risquee et la moins couverte par les solutions existantes". Cette reponse ne tient que si le diagramme et le code documentaire restent visibles et testes -- d'ou le choix de ne rien supprimer.

**Limite a ne pas survendre** : cette decision de perimetre ne change PAS le score actuel de `tests/eval_routing_accuracy.py` (94.6%, 35/37 -- voir `todo/contexte.txt` sections 63bis et 65). Les 2 echecs connus a cette date (DOC-09 "qui doit approuver un avoir", ERP-13 melange procedures+montant) sont des limites du script d'evaluation lui-meme, pas des problemes de qualite documentaire -- ne pas presenter cette decision de perimetre comme la cause d'une amelioration de ce chiffre, le jury peut verifier.

**Non tranche ici, volontairement** : ceci est une decision de *perimetre d'evaluation*, pas de *desactivation runtime*. Si le module documentaire devait un jour etre reellement desactive (pas seulement exclu du score), il faudrait d'abord decider explicitement ce que devient la branche HYBRIDE de `route()` dans `rag/routing.py` (repli sur `donnees_erp` seul, ou sur `documentaire` seul) -- question de routage a part entiere, pas cosmetique, qui n'est pas posee par la decision de ce tour.

**Suggere, non fait ce tour** : adapter `tests/eval_routing_accuracy.py` pour rapporter separement l'accuracy sur le sous-ensemble Code Intelligence/ERP (le perimetre score) et sur le reste (Documentaire/Hybride, hors perimetre), plutot que de melanger les deux dans un seul pourcentage.
