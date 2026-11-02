# Contenu à reporter dans le mémoire (Tableau 34 et références)

Contenu seulement : la forme et la mise en page restent à pmm. Les chiffres ERP de ce fichier datent du run du 30/10 (1 passe) et sont à remplacer après le run à 3 passes (option A appliquée entre-temps).

## 1. Tableau 34 (section 6.3), à la place du contenu actuel

**Tableau 34. Modèles de langage mesurés sur le banc documentaire (20 questions, 3 passes, 60 réponses par configuration)**

| Modèle | Paramètres et taille quantifiée | Faits restitués / réponses complètes | Sources citées / refus corrects | Délai médian (p90) | Remarque |
|---|---|---|---|---|---|
| qwen3:14b | 14,8 milliards, 9,3 Go | 100 % / 100 % | 98 % / 100 % | 20 s (32 s) | Retenu : seul modèle mesuré aussi sur le banc ERP |
| qwen3:14b sans raisonnement | 14,8 milliards, 9,3 Go | 98 % / 96 % | 97 % / 100 % | 8 s (15 s) | Banc ERP : 9 questions sur 16 (56 %) |
| qwen3:8b | 8,2 milliards, 5,2 Go | 98 % / 94 % | 98 % / 67 % | 12 s (19 s) | Un refus manqué sur trois à TRAP-02 |
| qwen3:30b-a3b | 30,5 milliards, 18,6 Go | 97 % / 93 % | 98 % / 100 % | 13 s (19 s) | Banc documentaire seul |
| qwen3.5:9b | 9,0 milliards, 6,6 Go | 100 % / 100 % | 97 % / 100 % | 14 s (38 s) | Banc documentaire seul |
| gemma4:26b | 25,2 milliards, 18,7 Go | 100 % / 100 % | 100 % / 100 % | 11 s (22 s) | Banc documentaire seul |
| mistral-small3.2:24b | 24,0 milliards, 15,2 Go | 100 % / 100 % | 97 % / 100 % | 10 s (30 s) | Banc documentaire seul |
| gpt-oss:20b | 20,9 milliards, 13,8 Go | 96 % / 89 % | 95 % / 100 % | 7 s (18 s) | Banc documentaire seul ; réponses incomplètes |

Notes du tableau : poids quantifiés Q4_K_M (MXFP4 pour gpt-oss:20b), tailles lues sur le serveur d'inférence ; contexte de 32 768 jetons, modèle entièrement en mémoire GPU, mêmes passages fournis à tous les modèles, température 0,3. « Refus corrects » : part des questions sans réponse dans les documents auxquelles le modèle s'est abstenu ; aucun modèle n'a refusé à tort une question qui avait une réponse. Délais hors recherche (passages pré-calculés). Source : `scripts/run_rag_model_eval.py`, tableau récapitulatif dans `scripts/benchresult.txt`.

## 2. Paragraphe suivant le Tableau 34 (remplace celui qui parle de Llama 3.1)

Les modèles du Tableau 34 sont ceux qui ont réellement été mesurés. Le banc documentaire est saturé : 20 questions réussies sur 20 établissent seulement un taux d'au moins 83,9 % (intervalle de Wilson, Wilson, 1927), et plusieurs modèles ne s'y séparent pas. Qwen3 14B, quantifié en Q4_K_M et entièrement chargé en mémoire GPU avec une fenêtre de contexte de 32 768 jetons, est retenu comme moteur de référence parce qu'il est le seul à avoir été mesuré aussi sur le banc ERP : 13 questions sur 16 (81 %) avec le raisonnement activé, 9 sur 16 (56 %) sans, en un seul passage par configuration. Les intervalles de Wilson à 95 % (57 à 93 % et 33 à 77 %) se chevauchent : l'écart n'est pas séparé du bruit d'un run. Le raisonnement fait passer le délai médian de l'agent ERP de 12 s à 49 s (p90 : 15 s et 104 s). Les autres modèles n'ont pas été mesurés sur le banc ERP : le tableau ne permet donc pas de conclure à leur infériorité pour cet usage. [Chiffres ERP à remplacer après le run à 3 passes.]

## 3. Références (citation, source, lien) pour la bibliographie et la webographie de pmm

Format dans le corps du texte : auteur-année, par exemple (Cormack et al., 2009). « Vérifiée » : identifiants et pages contrôlés par recherche le 01/11/2026.

| Citation dans le texte | Référence complète | Lien | Statut |
|---|---|---|---|
| (Lewis et al., 2020) | Lewis, P. et al. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. NeurIPS 33. | https://arxiv.org/abs/2005.11401 | Vérifiée |
| (Yao et al., 2023) | Yao, S. et al. (2023). ReAct: Synergizing Reasoning and Acting in Language Models. ICLR 2023. | https://arxiv.org/abs/2210.03629 | Vérifiée |
| (Es et al., 2024) | Es, S., James, J., Espinosa Anke, L., Schockaert, S. (2024). RAGAs: Automated Evaluation of Retrieval Augmented Generation. Proceedings of EACL 2024, System Demonstrations, pp. 150-158. | https://aclanthology.org/2024.eacl-demo.16 (doi:10.18653/v1/2024.eacl-demo.16) | Vérifiée |
| (Thakur et al., 2021) | Thakur, N., Reimers, N., Rücklé, A., Srivastava, A., Gurevych, I. (2021). BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of Information Retrieval Models. NeurIPS 2021, Datasets and Benchmarks Track. | https://arxiv.org/abs/2104.08663 ; https://neurips.cc/virtual/2021/poster/29903 | Vérifiée |
| (Zheng et al., 2023) | Zheng, L. et al. (2023). Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. | https://arxiv.org/abs/2306.05685 | Vérifiée |
| (Cormack et al., 2009) | Cormack, G. V., Clarke, C. L. A., Büttcher, S. (2009). Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods. SIGIR '09, pp. 758-759. | https://doi.org/10.1145/1571941.1572114 | Vérifiée |
| (Robertson et Zaragoza, 2009) | Robertson, S., Zaragoza, H. (2009). The Probabilistic Relevance Framework: BM25 and Beyond. Foundations and Trends in Information Retrieval 3(4), pp. 333-389. | https://doi.org/10.1561/1500000019 | Vérifiée |
| (Chen et al., 2024) | Chen, J., Xiao, S., Zhang, P., Luo, K., Lian, D., Liu, Z. (2024). M3-Embedding: Multi-Linguality, Multi-Functionality, Multi-Granularity Text Embeddings Through Self-Knowledge Distillation. Findings of ACL 2024. | https://arxiv.org/abs/2402.03216 | Vérifiée |
| (Yang et al., 2025) | Yang, A. et al. (2025). Qwen3 Technical Report. | https://arxiv.org/abs/2505.09388 | Vérifiée |
| (Krawczyk et al., 1997) | Krawczyk, H., Bellare, M., Canetti, R. (1997). HMAC: Keyed-Hashing for Message Authentication. RFC 2104. | https://doi.org/10.17487/RFC2104 ; https://www.rfc-editor.org/info/rfc2104 | Vérifiée |
| (Wilson, 1927) | Wilson, E. B. (1927). Probable Inference, the Law of Succession, and Statistical Inference. Journal of the American Statistical Association 22(158), pp. 209-212. | https://doi.org/10.1080/01621459.1927.10502953 (JSTOR : https://doi.org/10.2307/2276774) | Vérifiée le 01/11/2026 (ce fichier) |

### Sources web (consultées le 01/11/2026)

| Source | Lien | Remarque |
|---|---|---|
| Documentation Odoo 17, API externe | https://www.odoo.com/documentation/17.0/developer/reference/external_api.html | |
| Documentation Odoo 17, référence ORM | https://www.odoo.com/documentation/17.0/developer/reference/backend/orm.html | Adresse déduite de la page `orm/changelog.html`, non confirmée directement |
| FastAPI | https://fastapi.tiangolo.com/ | |
| LangGraph | https://reference.langchain.com/python/langgraph/overview | |
| Chroma | https://docs.trychroma.com/ | |
| Ollama, API | https://docs.ollama.com/api | |
| BGE-M3 (BAAI) | https://huggingface.co/BAAI/bge-m3 | |
| Qwen3-14B | https://huggingface.co/Qwen/Qwen3-14B | 14,8 milliards de paramètres, 32 768 jetons natifs, raisonnement activé par défaut |
| Model Context Protocol | https://modelcontextprotocol.io | |
| RFC 2104 (HMAC) | https://www.rfc-editor.org/info/rfc2104 | |
