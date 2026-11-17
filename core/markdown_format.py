"""Plain-text subset rendered by the Odoo assistant panel (odoo_addons/miro_ai/static/src/js/miro_ai_markdown.js)."""

MARKDOWN_FORMAT_RULES = (
    "Écris en texte simple, en paragraphes courts. Seuls le **gras**, l'*italique*, le `code` "
    'et les liens ("[texte](url)") sont mis en forme à l\'écran. '
    'N\'utilise ni tableau, ni titre ("#"), ni liste numérotée, ni sous-liste, ni balise HTML : '
    "ils seraient affichés tels quels, illisibles pour l'utilisateur. "
    'Pour énumérer, écris une ligne par élément, chacune commençant par "- " ; '
    "restitue un tableau ligne par ligne, sous la forme \"- libellé : valeur\"."
)
