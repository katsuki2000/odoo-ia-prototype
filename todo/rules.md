pas de fix chirurgical, voir la root cause
code in english
don't use emojis
think first
clean code
find best algorithm
make the work like it was built by an human. no "plagiat", at least reformulate first
put all installed packages in requirements(we work in venv)
put everything you change in todo/contexte.txt
ne JAMAIS lancer `pytest tests/ -v` (suite complète) tel quel sur cette machine -- prend plus de 30 min et fait planter la machine (pas d'AVX2, cf todo/contexte.txt section 85). Toujours utiliser `pytest tests/ -v -m "not integration"` par défaut (marqueur déjà dans pytest.ini). Les 3 tests marqués `integration` (`test_scalability_benchmark_under_6_minutes`, `test_e2e_live_add_delete_query_cycle`, `test_groq_chat_model_connectivity`) ne se lancent qu'à part, volontairement, jamais dans un run "complet" par défaut






