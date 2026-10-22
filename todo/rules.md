corrige tout ce qui ne respecte pas ces règles quand tu vois un fichier
faut que le projet soit scalable et interoperable : pas de "ça marche sur ma machine" -- aucun chemin absolu, ID numerique (ir.model.data/xml_id a la place), ou config specifique a un poste code en dur ; toute valeur machine-dependante passe par .env/variable d'env ou config avec un fallback explicite (skip propre) si absente.
verifie si ce qui est demandé est deja fait, avant d'agir. on simplifie le code, à retirer ce que je comprends pas et qui n'a aucun impact sur architecture.md
architecture est l'objectif à atteindre 
pas de fix chirurgical, voir la root cause
ne remplis pas le code de commentaires, écris que si c necessaire et sois bref (je ne veux pas voir de d'après contexte, ou un truc du genre), tu as deja contexte et readme pour les details
code in english
don't use emojis
think first
clean code (très important)
find best algorithm (avec moins de complexité, et plus court que possible)
make the work understooden easily by anyone (très important, je vais relire le code à un moment donné)
put all installed packages in requirements(we work in venv)
put everything you change in todo/contexte.txt, and read the last lines before anything

meme convention de nommage
DRY (Don't Repeat Yourself)
utilise des trucs universels et standard , n'invente pas, au pire dis moi qu ça sort de l'ordinaire 
fait que la transition vers aws soit facile en modifiant qu'un seul fichier (config/settings.py par exemple)

> lorsque plusieurs options s"ouvrent , il faut se demander : est ce que là l'ia pourra repondre correctement sur n'importe quel instance odoo 17?

focus addon Odoo : `miro_ai` seulement. Ne pas modifier, tester, ni prioriser `miro_ai_discuss` 
