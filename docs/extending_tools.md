# Guide d'Extension du Catalogue d'Outils (ORM ReAct)

Ce guide est destiné aux développeurs Odoo ou Python souhaitant enrichir les capacités de l'Assistant MIRO RAG en lui apprenant à effectuer de nouvelles opérations sur la base de données Odoo.

---

## 1. Comment fonctionne le catalogue d'Outils ?

MIRO RAG utilise le concept de "Function Calling" (via `bind_tools` dans LangChain). Quand un utilisateur pose une question chiffrée, le modèle LLM lit les descriptions de tous les outils disponibles et **décide lui-même** lequel appeler avec quels arguments.

La liste complète des outils actuels se trouve dans `tools/odoo_tools.py`.

---

## 2. Structure d'un Outil (Template)

Pour ajouter un outil, vous devez créer une fonction Python annotée avec le décorateur `@tool` de LangChain.

### Template Type :
```python
from langchain_core.tools import tool
from tools.odoo_connector import connector, odoo_uid_ctx

@tool
def obtenir_nouveau_kpi(client_nom: str = "", statut: str = "done") -> str:
    """
    RÉSUMÉ STRICT DE L'OUTIL (Ce que lit le LLM pour décider d'utiliser l'outil).
    Exemple: Récupère la liste des expéditions pour un client donné.
    
    Args:
        client_nom (str): Nom ou partie du nom du client (ex: 'Rakoto'). Laissez vide pour tout le monde.
        statut (str): État du bon de livraison (ex: 'done', 'draft'). Par défaut 'done'.
    """
    # 1. Récupérer l'UID de l'utilisateur connecté (Sécurité RBAC)
    uid = odoo_uid_ctx.get()
    
    # 2. Construction du domaine de recherche
    domain = []
    if client_nom:
        domain.append(["partner_id.name", "ilike", client_nom])
    if statut:
        domain.append(["state", "=", statut])
        
    # 3. Appel au Connecteur Odoo (Read-Only)
    try:
        # search_read pour lister des données, read_group pour des sommes/agrégations
        records = connector.search_read(
            uid=uid,
            model_name="stock.picking",  # Modèle Odoo cible
            domain=domain,
            fields=["name", "date_done", "state"]
        )
        
        # 4. Formater la réponse pour l'Agent LLM
        if not records:
            return f"Aucune expédition trouvée pour le client {client_nom} avec le statut {statut}."
            
        result_str = f"Expéditions trouvées ({len(records)}):\n"
        for r in records:
            result_str += f"- {r.get('name')} (Date: {r.get('date_done')})\n"
            
        return result_str
        
    except Exception as e:
        return f"Erreur lors de la lecture d'Odoo: {str(e)}"
```

---

## 3. Conventions Strictes (Critique)

Pour que l'outil soit appelé avec succès par l'agent :

1. **Nommage en Français explicite :** Utilisez `obtenir_xyz` ou `lister_xyz`. Pas de noms génériques comme `search_data`.
2. **Docstring Parfaite :** Le LLM ne regarde **que** la docstring. Elle doit contenir :
   - Une phrase d'accroche très claire.
   - La définition de *chaque* argument (types et exemples).
3. **Arguments typés :** Fournissez des types stricts (`str`, `int`, `float`) et des valeurs par défaut si possible. Évitez de forcer l'Agent à deviner un ID numérique, demandez-lui un nom (`str`) et faites le `ilike` vous-même côté Odoo.
4. **Toujours utiliser `odoo_uid_ctx.get()` :** Ne passez jamais en dur `uid=2` ou le mode super-admin (`uid=1`). L'UID du contexte garantit que l'utilisateur n'accède qu'à ses propres droits Odoo.

---

## 4. Ajout de l'Outil au Pipeline (Déploiement)

Une fois votre fonction écrite dans `tools/odoo_tools.py` :

1. Allez dans `rag/pipeline.py` (ou `rag/graph.py` selon la version).
2. Ajoutez votre outil à la liste `ALL_TOOLS` ou au registre des compétences :
   ```python
   # Dans odoo_tools.py
   # Assurez-vous d'exporter l'outil
   ```
3. (Si RBAC) : Liez votre outil à un module Odoo dans l'API. Par exemple, si c'est un outil RH, assurez-vous qu'il ne soit mis à disposition que si l'utilisateur possède l'autorisation Odoo RH.

---

## 5. Procédure de Test

Avant de déployer :
1. Créez un test unitaire dans `tests/test_odoo_tools.py`.
2. Interrogez l'outil directement en Python sans le LLM pour vérifier que l'appel Odoo `search_read` ou `read_group` retourne bien la donnée.
3. Testez via l'Agent (Interface Chat) en posant une question en langage naturel pour vérifier si le routeur sélectionne correctement le nouvel outil.
