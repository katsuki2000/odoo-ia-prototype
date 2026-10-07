"""

Portee volontairement etroite (Bug B, option intermediaire, section 896) :
- Utilise UNIQUEMENT par `scripts/run_bloc_n1_benchmark.py` comme filet pour
  les questions du banc -- PAS cable en production (`context_extractors.py`/
  dispatch), qui ne doit jamais inventer une identite depuis du texte libre
  d'un vrai utilisateur. Generaliser au-dela du banc est une decision
  separee, non prise ici.
- Le xmlid du groupe INCLUS doit etre au format `module.identifiant` (un
  point litteral) : jamais de prefixe de module devine. Un groupe cite sans
  prefixe (ex. ACC-Q1 : "group_account_manager") est ignore par construction
  -- faux negatif accepte plutot qu'un xmlid invente.
- Le groupe EXCLU ("sans X") est repere mais jamais ajoute aux groupes de la
  persona -- il sert seulement a decrire ce qu'elle N'A PAS.
- Une persona detectee mais non necessaire est sans risque : la presence de
  `security_principals` n'ajoute qu'une invitation au system prompt
  (loop.py, bloc [PERSONAS DE LA QUESTION]), jamais un dispatch force (verifie
  section 896).
"""

import re
import unicodedata
from typing import Dict, List

# Section 896 (corrige apres un faux positif reel sur MNT-Q1 -- "une fiche
# equipement (maintenance.equipment)" matchait aussi le motif "Un/Une X
# (xmlid)" pose initialement, car "une" est un article indefini courant
# n'importe ou dans la phrase, pas seulement pour introduire une persona) :
# le xmlid INCLUS doit avoir "group_" comme identifiant (convention Odoo pour
# TOUT groupe de securite), ce qui exclut par construction un nom de modele
# technique comme "maintenance.equipment" tout en gardant "base.group_user",
# "sales_team.group_sale_salesman", etc.
_PERSONA_PATTERN = re.compile(
    r"\bUne?\s+(?P<label>'[^']+'|[^(),.]{2,60}?)\s*"
    r"\(\s*(?P<xmlid>[a-z][a-z0-9_]*\.group_[a-z0-9_]*)\s*"
    r"(?:,\s*sans\s+[^)]+)?\)",
    re.IGNORECASE,
)


def _slugify(label: str) -> str:
    label = label.strip().strip("'\"")
    label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    label = re.sub(r"[^a-zA-Z0-9]+", "_", label).strip("_").lower()
    return label or "principal"


def detect_security_principals_from_question(question: str) -> Dict[str, Dict[str, List[str]]]:
    """Retourne un dict au meme format que `security_principals` du bank JSON
    (888/889), construit uniquement a partir de personas nommees explicitement
    dans le texte avec un xmlid de groupe INCLUS au format `module.identifiant`.
    Dict vide si aucune persona de ce type n'est trouvee -- jamais une erreur."""
    principals: Dict[str, Dict[str, List[str]]] = {}
    used_ids = set()
    for m in _PERSONA_PATTERN.finditer(question):
        xmlid = m.group("xmlid")
        base_id = _slugify(m.group("label"))
        principal_id = base_id
        suffix = 2
        while principal_id in used_ids:
            principal_id = f"{base_id}_{suffix}"
            suffix += 1
        used_ids.add(principal_id)
        principals[principal_id] = {"group_xmlids": [xmlid]}
    return principals
