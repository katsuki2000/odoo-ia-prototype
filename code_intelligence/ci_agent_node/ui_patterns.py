"""
code_intelligence/ci_agent_node/ui_patterns.py

Regex-based extraction of UI element names (buttons/menus/fields) and
detection of module-level UI inquiries from a question. Extracted from the
former ci_agent_node.py monolith (refactor, see todo/contexte.txt).
Behavior unchanged.
"""

import re
from typing import Optional

_UI_NAME_STOPWORDS = {
    "visible", "visibles", "invisible", "invisibles",
    "specifique", "specifiques", "spécifique", "spécifiques",
    "particulier", "particuliers", "particuliere", "particulières", "particulière",
    "dedie", "dedies", "dédié", "dédiés", "dediee", "dédiée", "dediees", "dédiées",
    "nouveau", "nouveaux", "nouvelle", "nouvelles",
    "ajoute", "ajoutes", "ajouté", "ajoutés", "ajoutee", "ajoutée", "ajoutees", "ajoutées",
    "cree", "crees", "créé", "créés", "creee", "créée", "creees", "créées",
    "supplementaire", "supplementaires", "supplémentaire", "supplémentaires",
    "personnalise", "personnalises", "personnalisé", "personnalisés",
    "existant", "existants", "existante", "existantes",
    "present", "presents", "présent", "présents", "presente", "présente", "presentes", "présentes",
    "special", "speciaux", "spécial", "spéciaux", "speciale", "spéciale", "speciales", "spéciales",
    "custom", "new", "existing", "specific", "dedicated", "added", "created",
    "un", "une", "des", "le", "la", "les", "ce", "cette", "ces", "dans", "sur",
}

_MODULE_UI_PATTERN = re.compile(
    r"\b(?:modifie(?:-t-il)?\s+(?:une\s+)?vue|ajoute(?:-t-il)?\s+(?:un\s+)?bouton|dossier\s+views|vue\s+xml|interface)\b",
    re.IGNORECASE,
)


def matches_module_level_ui_inquiry(question: str) -> bool:
    return bool(_MODULE_UI_PATTERN.search(question))


def extract_ui_element_name(question: str) -> Optional[str]:
    """Best-effort extraction of the UI element (button/menu/field) name a
    question is asking about, filtering out generic qualifier words that
    are never themselves the element's name (see _UI_NAME_STOPWORDS)."""
    match = re.search(
        r"\b(?:bouton|button|menu|menuitem|champ|field)s?\s+(?:statistique\s+)?['\"«]([^'\"»]+)['\"»]",
        question, re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"\b(?:bouton|button|menu|champ|field)s?\s+(?:de\s+|d['’]\s*)?([a-zA-Z0-9_]+)\b",
            question, re.IGNORECASE,
        )
    if not match:
        match = re.search(
            r"\b(?:voir\s+ou\s+configurer|voir\s+ou\s+modifier|voir|configurer|modifier|afficher|masquer)\s+"
            r"(?:le|la|l['’]|les)?\s*([^?]+?)\s+sur\s+(?:la\s+fiche|le\s+formulaire|la\s+vue)",
            question, re.IGNORECASE,
        )
    if not match:
        return None
    name = match.group(1).strip()
    if name.lower() in _UI_NAME_STOPWORDS:
        return None
    return name
