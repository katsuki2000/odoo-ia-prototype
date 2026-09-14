corrige tout ce qui ne respecte pas ces règles
faut que le projet soit scalable et interoperable : pas de "ça marche sur ma machine" -- aucun chemin absolu, ID numerique (ir.model.data/xml_id a la place), ou config specifique a un poste code en dur ; toute valeur machine-dependante passe par .env/variable d'env avec un fallback explicite (skip propre) si absente. cf. todo/contexte.txt sections 217 (chemins corpus) et 219 (IDs res.groups) pour deux cas reels de violation de cette regle
plan est le plan à suivre, ça doit etre  une feuille de rout, doit pas etre pollué, le changement devrait etrer rare
pas de fix chirurgical, voir la root cause
ne remplis pas de commentaire dans le code , écris que si c necessaire et sois bref, tu as deja deja contexte et readme pour les details
code in english
don't use emojis
think first
clean code (très important)
find best algorithm
make the work like it was built by an human. no "plagiat", at least reformulate first
put all installed packages in requirements(we work in venv)
put everything you change in todo/contexte.txt

meme convention de nommage(snake_case pour les fichiers et PascalCase pour les classes, camel case pour les variables)
DRY (Don't Repeat Yourself)
respect d'architecture LLM recommandé 
a clean architecture with subpackages and packages
fait que la transition vers local soit facile en modifiant qu'un seul fichier (.env)