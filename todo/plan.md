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
