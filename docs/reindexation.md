# Guide de Réindexation et Ingestion MIRO RAG

Ce document explique le fonctionnement du pipeline d'ingestion de documents de MIRO RAG. Le système maintient la base vectorielle (Qdrant/Chroma) à jour avec les fichiers présents dans le dossier `fake_data/docs/` (ou votre répertoire de production équivalent) afin d'assurer que l'assistant réponde toujours avec les données les plus récentes.

---

## 1. Comment ajouter ou modifier des documents

L'approche de MIRO RAG repose sur une architecture en **File System surveillé**. Vous n'avez pas besoin d'utiliser d'interface complexe pour uploader des documents.

1. **Ajouter un document :** Glissez-déposez simplement un PDF, un TXT, ou un fichier XML dans le dossier correspondant sous `fake_data/docs/`.
2. **Modifier un document :** Éditez et écrasez le fichier existant.
3. **Supprimer un document :** Supprimez le fichier du répertoire.

Le système détecte l'action automatiquement !

---

## 2. Le Watchdog (Indexation Continue)

L'indexation automatique est gérée par le script `ingestion/watcher.py` (qui utilise la librairie `watchdog`). 

### Comment ça marche ?
1. **Surveillance :** Le processus scrute continuellement toute création, modification, ou suppression dans le dossier `fake_data/docs/`.
2. **Debounce (Anti-rebond) :** S'il détecte une modification, il attend **2 secondes** d'inactivité avant de lancer le traitement. Cela évite d'indexer un fichier incomplet en cours de copie.
3. **OCR (Scan PDF) :** Si le fichier est un PDF constitué uniquement d'images (scan), le module `pytesseract` est automatiquement appelé pour en extraire le texte.
4. **Mise à jour vectorielle :** 
   - *Fichier ajouté/modifié :* Il est découpé en "chunks" (morceaux), vectorisé via `nomic-embed-text`, et ajouté/mis à jour dans Qdrant.
   - *Fichier supprimé :* Tous les vecteurs portant les métadonnées `source: <nom_du_fichier>` sont purgés de la base.

### Lancer le Watcher
Dans un environnement de production, ce processus tourne en tâche de fond (daemon/systemd) :
```bash
python ingestion/watcher.py
```

---

## 3. L'Indexation Incrémentielle (Optimisation)

Pour éviter de surcharger le processeur avec des calculs d'embeddings redondants (qui prennent du temps), MIRO RAG utilise un algorithme **incrémentiel** (défini dans `ingestion/incremental.py`).

1. **Génération de Hash (MD5) :** Avant d'indexer un fichier, le système calcule l'empreinte MD5 du contenu.
2. **Vérification d'historique :** Ce Hash est comparé à celui stocké lors de la dernière indexation du fichier.
3. **Action conditionnelle :** 
   - *Hashes identiques* = Le fichier n'a pas changé. L'indexation est **ignorée**.
   - *Hashes différents* = Le fichier a changé. Ses anciens vecteurs sont supprimés et remplacés par les nouveaux.

---

## 4. Déclenchement Manuel via API

Dans certains cas (maintenance, arrêt prolongé du watcher, reconstruction d'index), vous pouvez forcer la réindexation complète ou partielle sans redémarrer le Watcher.

Le backend FastAPI propose une route dédiée pour cela :

**POST `/api/v1/reindex`**
```json
{
  "scope": "full" // Options: "full" (force tout) ou "incremental" (respecte les Hash MD5)
}
```

*Exemple avec `curl` :*
```bash
curl -X POST http://localhost:8000/api/v1/reindex \
     -H "Content-Type: application/json" \
     -d '{"scope": "incremental"}'
```

Le système retournera un rapport JSON des fichiers traités, ignorés et des erreurs éventuelles.
