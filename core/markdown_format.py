"""Markdown subset rendered by the Odoo assistant panel (odoo_addons/miro_ai/static/src/js/miro_ai_markdown.js)."""

MARKDOWN_FORMAT_RULES = (
    "Écris exclusivement en Markdown standard : **gras**, *italique*, `code`, "
    'listes à puces ("- item") ou numérotées ("1. item") avec sous-listes indentées de trois espaces, '
    'tableaux (ligne d\'en-tête, ligne de séparation "| --- | --- |", puis une ligne par enregistrement), '
    'titres ("##", "###"), liens ("[texte](url)"). '
    'N\'utilise JAMAIS de balise HTML brute (aucune séquence "<...>" du type <strong>, <br>, <div>, <em>, <ul>, etc.), '
    "même en complément du Markdown : le moteur d'affichage interprète uniquement du Markdown, "
    "toute balise HTML serait affichée littéralement à l'écran, illisible pour l'utilisateur."
)
