# Guide d'Installation de MIRO RAG

Ce guide détaille les étapes nécessaires pour déployer le système MIRO RAG (Odoo 17 + FastAPI + LangGraph) depuis zéro, que ce soit sur une infrastructure Docker (On-Premise) ou via un environnement de développement type Github Codespaces.

---

## 1. Prérequis Système

- **Système d'exploitation :** Linux (Ubuntu/Debian recommandé) ou Windows avec WSL2.
- **Docker & Docker Compose :** Pour l'orchestration des bases de données Odoo, PostgreSQL et Qdrant.
- **Python 3.10+** (Testé avec Python 3.10.12).
- **Tesseract OCR :** Pour le traitement des PDF scannés.
  - *Debian/Ubuntu :* `sudo apt-get install tesseract-ocr tesseract-ocr-fra poppler-utils`

---

## 2. Déploiement de l'Infrastructure (Docker)

Le projet fournit un fichier `docker-compose.yml` qui démarre Odoo 17, sa base PostgreSQL et la base vectorielle Qdrant.

1. **Lancer les conteneurs :**
   ```bash
   cd miro-rag
   docker-compose up -d
   ```
2. **Vérifier l'état des services :**
   - Odoo : http://localhost:8069
   - Qdrant (Dashboard) : http://localhost:6333/dashboard

---

## 3. Configuration du Backend AI (FastAPI)

Le moteur MIRO RAG s'exécute dans un environnement Python isolé.

### 3.1. Installation des dépendances
```bash
python -m venv venv_miro
source venv_miro/bin/activate  # Sur Windows: .\venv_miro\Scripts\activate
pip install -r requirements.txt
```

### 3.2. Variables d'Environnement (`.env`)
Créez un fichier `.env` à la racine de `miro-rag` :

```env
# Authentification Odoo
ODOO_URL=http://localhost:8069
ODOO_DB=odoo
ODOO_USER=admin
ODOO_PASSWORD=admin

# Choix du Vectorstore (chroma ou qdrant)
VECTORSTORE_TYPE=qdrant
QDRANT_URL=http://localhost:6333

# Moteur LLM (Groq Cloud ou Ollama Local)
LLM_PROVIDER=groq
GROQ_API_KEY=votre_cle_api_groq
GROQ_MODEL=llama-3.1-8b-instant

# Clé secrète pour les Tokens JWT (API)
JWT_SECRET_KEY=cle_secrete_ultra_securisee_12345
```

> [!TIP]
> **Production On-Premise :** Pour éviter que vos données ne sortent sur internet, passez `LLM_PROVIDER=ollama` et assurez-vous qu'Ollama tourne en local avec le modèle `llama3.1:8b`.

---

## 4. Configuration d'Odoo 17

L'interface de l'assistant se trouve dans un module Odoo personnalisé nommé `miro_ai`.

1. **Lien Symbolique / Copie :** Copiez le dossier `miro_ai` dans le répertoire d'addons monté par Docker.
2. **Installation :**
   - Activez le mode développeur dans Odoo.
   - Allez dans *Applications* > *Mettre à jour la liste des applications*.
   - Cherchez **"MIRO AI"** et cliquez sur *Activer*.
3. **Paramétrage :**
   - Allez dans *Configuration* > *MIRO AI Settings*.
   - Renseignez l'URL de l'API FastAPI (ex: `http://localhost:8000`).
   - Activez les compétences (Ventes, Comptabilité, Stocks).

---

## 5. Démarrage Rapide (First Run)

1. **Lancer l'API FastAPI :**
   ```bash
   uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
   ```
2. **Lancer le Watcher d'Ingestion (dans un autre terminal) :**
   ```bash
   python ingestion/watcher.py
   ```
3. **Tester depuis Odoo :**
   Ouvrez l'interface MIRO AI dans Odoo et posez une question simple comme *« Quel est mon rôle ? »* ou *« Résume les documents existants »*.

**C'est prêt !** Votre plateforme MIRO RAG est désormais opérationnelle.
