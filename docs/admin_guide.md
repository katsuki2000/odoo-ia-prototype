# Guide Administrateur : MIRO RAG (Odoo 17)

Ce guide est destiné aux administrateurs système et fonctionnels d'Odoo souhaitant superviser, configurer et dépanner le système MIRO AI.

---

## 1. Paramétrage Général et Compétences (Skills)

Toute la configuration fonctionnelle de l'assistant se trouve dans Odoo :
**Menu :** `Configuration` > `MIRO AI Settings`

### 1.1 Bascules de Compétences (Skill Toggles)
Vous disposez de cases à cocher pour activer ou désactiver des "compétences" (ex: *Ventes*, *Achats*, *RH*). 
- **Si une compétence est désactivée :** Les outils correspondants sont retirés dynamiquement du cerveau de l'IA (LangGraph) pour toute l'entreprise. L'IA refusera poliment de répondre aux questions liées à ce domaine.
- **Utilité :** Très pratique lors du déploiement progressif de l'outil ou en cas de maintenance d'un module Odoo.

### 1.2 Le Dashboard de Couverture (Module Coverage)
Dans ces mêmes paramètres, un tableau de bord se génère dynamiquement via l'API. Il classe les modules Odoo installés en 3 catégories :
- ✅ **Supportés :** Des outils ORM (Python) existent. L'IA peut interroger et agréger ces données.
- 📄 **Code Seulement :** L'IA connaît le code source du module (indexé dans Qdrant), mais n'a pas d'outils pour interagir avec les données.
- ❌ **Non Couverts :** Le module est inconnu de l'IA.

---

## 2. Sécurité et Gestion Multi-Tenant

MIRO AI respecte rigoureusement l'architecture Multi-Société (Multi-Tenant) d'Odoo.

### Isolation par Société (`company_id`)
Lorsque l'utilisateur pose une question, Odoo transmet son `company_id` via le token JWT au backend FastAPI.
- **RAG (Documents) :** Le backend interroge **uniquement** la collection Qdrant spécifique à cette société (ex: `collection_company_1`). Une fuite de documents entre filiales est impossible.
- **ORM (Données) :** Les outils effectuent des requêtes XML-RPC en utilisant le `uid` exact de l'utilisateur. Les `ir.rule` d'Odoo (qui limitent l'accès aux enregistrements de la société actuelle) s'appliquent automatiquement !

### Isolation RBAC
De même, l'IA vérifie les groupes (`res.groups`) de l'utilisateur. Un utilisateur n'appartenant pas au groupe "Comptabilité" verra sa requête rejetée par Odoo si l'IA tente d'appeler l'outil `obtenir_total_factures`.

---

## 3. Supervision et Logs

L'historique complet des intéractions est conservé à des fins d'audit et d'amélioration.

### Vue des Logs dans Odoo
**Menu :** `MIRO AI` > `Historique des requêtes` (Accessible uniquement aux administrateurs)
- Vous y trouverez une liste (Tree View) de chaque question posée.
- **Colonnes clés :** Utilisateur, Question, Mécanisme (`DOCUMENTAIRE` ou `DONNEES_ERP`), Temps de réponse, Confiance.
- **Filtrage :** Filtrez facilement les requêtes où l'IA a eu une "Confiance Basse" (< 50%) pour identifier des documents manquants ou des outils défaillants.

---

## 4. Troubleshooting (Dépannage)

### 4.1 "L'assistant me dit qu'il n'a pas trouvé le document"
1. **Vérifiez le Watchdog :** Assurez-vous que le script `ingestion/watcher.py` tourne sur le serveur.
2. **Vérifiez les logs d'ingestion :** Regardez dans `logs/ingestion.log` si le document a bien été scanné. Si c'est un PDF protégé ou corrompu, une erreur y figurera.
3. **Indexation manuelle :** Si besoin, relancez un scan complet depuis le terminal : 
   `curl -X POST http://localhost:8000/api/v1/reindex -d '{"scope": "full"}'`

### 4.2 "L'assistant est lent (plus de 10 secondes)"
- Si vous êtes sur Groq (Cloud) : Vérifiez que vous n'êtes pas bridé par la limite "Rate Limit" (429).
- Si vous êtes sur Ollama (Local) : Vérifiez la consommation RAM/VRAM de votre serveur. Un modèle `llama3.1:8b` nécessite au minimum 8GB de RAM unifiée (GPU recommandé).

### 4.3 "Un utilisateur a accès à des outils qu'il ne devrait pas avoir"
Vérifiez la configuration RBAC dans l'API FastAPI. Le mappage entre les ID de groupes Odoo (`group_sale_salesman`) et les compétences (`ventes`) doit être synchronisé avec votre configuration Odoo.
