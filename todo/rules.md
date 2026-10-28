corrige tout ce qui ne respecte pas ces règles quand tu vois un fichier
faut que le projet soit scalable et interoperable : pas de "ça marche sur ma machine" -- aucun chemin absolu, ID numerique (ir.model.data/xml_id a la place), ou config specifique à un poste codé en dur ; 
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

config/settings.py : l'environnement ne porte que ce qui change d'un poste ou d'un déploiement à l'autre : secrets, adresses de connexion (serveur LLM, instance Odoo, API) et emplacements des installations externes (sources Odoo, odoo.conf, odoo-bin, interpréteur), chacun avec un défaut portable (jamais un chemin absolu ni propre à un OS) ; tout le reste (modèles, budgets, seuils, limites, comportement) est une constante de config/settings.py, rien d'autre dans .env

> lorsque plusieurs options s"ouvrent , il faut se demander : est ce que là l'ia pourra repondre correctement sur n'importe quel instance odoo 17?


