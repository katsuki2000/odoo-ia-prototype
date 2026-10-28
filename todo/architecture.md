# Architecture cible de MIRO AI

## 1. Objectif

MIRO AI est un assistant privé qui aide les utilisateurs métier à comprendre le fonctionnement réel d'une instance Odoo 17 et à consulter les données auxquelles ils ont accès. Les réponses doivent être compréhensibles et  vérifiables.

Le PoC distingue deux modes :
- **Selon le système Odoo** : investiguer les données runtime de l'instance.
- **D'après la documentation** : chercher dans les documents internes indexés et répondre à partir des passages retrouvés.

L'utilisateur peut choisir le mode dans l'interface. Sans choix explicite, MIRO sélectionne la source la plus probable. Si la source reste incertaine, il demande une précision au lieu de choisir silencieusement.

## 2. Périmètre fonctionnel

### 2.1 Données ERP

Les questions portant sur des valeurs actuelles — statut, nombre, liste ou agrégation — doivent utiliser les outils ORM existants en lecture seule. Les opérations de création, modification et suppression sont hors périmètre du PoC.

La lecture d'une donnée métier s'effectue sous l'identité authentifiée du demandeur, avec le contexte de société correspondant. L'identité et les permissions ne proviennent jamais du LLM. L'accès technique utilisé pour lire des métadonnées ne doit pas servir de raccourci pour lire des données métier à la place de l'utilisateur.

### 2.3 Documentation interne

La branche documentaire utilise le RAG déjà présent dans le projet. Une réponse doit être fondée sur les passages récupérés et signaler les limites lorsque ces passages ne suffisent pas.


## 4. Architecture du PoC

Le PoC conserve les composants existants et privilégie le chemin le plus simple.

```text
Question utilisateur
        |
        v
Choix explicite de la source, sinon classification avec confiance
        |
        +-------------------------+
        |                         |
        v                         v
Documentation                Système Odoo
RAG existant                  Agent système unique
ChromaDB + recherche          
lexicale/vectorielle          
        |                     - outils ORM typés en lecture seule
        |                         |
        +------------+------------+
                     |
                     v
         Dossier de preuves existant
                     |
                     v
         Vérification et réponse
```

## 7. Évaluation avant livraison

L'évaluation doit séparer les tests logiciels, les tests d'intégration et la qualité métier.