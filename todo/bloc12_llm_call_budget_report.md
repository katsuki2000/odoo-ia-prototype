# Rapport Bloc 12 / J48 -- Budget LLM par branche

**Source :** `/home/user/odoo-ia-prototype/miro-rag/captures/reasoning_trace.jsonl`

**Nombre total de questions tracees :** 9

---

## Comparaison par branche

| Branche | N questions | Appels LLM (moy/med/max) | Hops (moy/med/max) | Plafond de sauts atteint |
|---|---|---|---|---|
| Code Intelligence (agent composite) | 9 | 1.78 / 2.0 / 2 | 2.67 / 2.0 / 5 | 3/9 (33%) |

*Plafond de sauts par question (J48) : `code_intelligence` applique `CI_MAX_HOPS=4` (rag/graph.py), `donnees_erp` applique `REACT_RECURSION_LIMIT=6`, `documentaire` ne fait jamais de hop (0 par construction). Valeur generique de reference : `MAX_HOPS_PER_QUESTION=4` (code_intelligence.reasoning_trace_logger).*

---
## Lecture

- `documentaire` (RAG simple) sert de plancher de comparaison : 0 hop, 1-2 appels LLM (1 en generation structuree, +1 seulement si le fallback texte-brut est declenche).
- `donnees_erp` (Function Calling) fait jusqu'a `REACT_RECURSION_LIMIT` (6) allers-retours outil+LLM, plus 1 appel de synthese forcee si la limite est atteinte sans reponse finale.
- `code_intelligence` est la branche la plus couteuse : 1 appel resolveur (seulement en cas d'arbitrage LLM ambigu), jusqu'a `CI_MAX_HOPS` (4) appels de selection d'outil, et 1-2 appels de synthese (le second uniquement en cas de retry anti-repetition).
