# Journal annexe — decisions et candidats du resolveur

## 2026-10-15 — lot de decision fermee

Suite du mandat de 18:36, des rules relues et de `todo/resolver_fix_change_log.md`. Exception de journal annexe deja autorisee; principal distant intact.

- Le chemin actif du fuzzy consomme uniquement le pool dense deja filtre par dense_lookup : pas de deuxieme recherche dense non filtree dans ce chemin. Les anciens helpers exportes de candidates.py ne sont pas supprimes dans ce lot.
- Une liste de bons candidats lexicaux n'est plus promue integralement en cibles certaines. Une seule candidature stricte sans concurrent peut etre deterministe; sinon arbitrage ou abstention.
- Contrat LLM : tableau JSON ferme de noms techniques; plusieurs entrees seulement pour des sujets independants explicitement demandes. Tableau vide = abstention. Tout modele hors liste invalide la selection complete. Anciennes reponses singleton/NONE encore acceptees.
- Les choix explicites multiples sont conserves; la presence dans la liste n'est pas une preuve que le LLM a correctement compris les sujets. Qualite semantique a mesurer en integration, pas revendiquee par les fixtures.
- Trace d'arbitrage : tentatives reelles de invoke, statut, attente renvoyee par le rate limiter. Si l'appel echoue sans rendre d'attente, cette attente reste inconnue/zero, pas une mesure exhaustive des echecs.

22 regressions isolees et compilation reussies avant publication. Aucune invocation reelle des services Kaggle/Odoo. Le partage routeur/runner et le report de ces compteurs sont le lot suivant.
