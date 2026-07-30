# MIRO RAG - Prototype Assistant IA & Instance Odoo 17.0

Ce dépôt contient le prototype de l'assistant IA **MIRO RAG**, connecté en temps réel à une base ERP **Odoo 17.0** via XML-RPC. Il s'appuie sur une architecture multi-agents LangGraph combinant le RAG documentaire (procédures et documentation) et le querying en direct de la base de données ERP (Ventes, Comptabilité, Stock, Tickets de Support).

---

## 🚀 Guide Rapide de Réplication (Installer la même instance Odoo sur un autre PC)

Pour obtenir **exactement la même instance Odoo 17.0** avec les mêmes données, modules, utilisateurs, commandes de vente et tickets de support sur une autre machine, suivez les étapes ci-dessous.

### 📋 Prérequis

- **Docker** & **Docker Compose**
- **Python 3.10+** & `pip`
- **Git**

---

### 1. Clonage du dépôt et environnement Python

```bash
git clone <URL_DU_DEPOT> odoo-ia-prototype
cd odoo-ia-prototype

# Création et activation de l'environnement virtuel Python
python3 -m venv .venv
source .venv/bin/activate

# Installation des dépendances Python
pip install -r requirements.txt
```

---

### 2. Configuration des variables d'environnement (`.env`)

Créez le fichier `miro-rag/.env` avec vos clés d'API (notamment la clé LLM Groq) :

```env
GROQ_API_KEY=votre_cle_groq_api
LLM_PROVIDER=groq
NOMIC_API_KEY=votre_cle_nomic
HF_TOKEN=votre_token_huggingface
```

---

### 3. Lancement des conteneurs Docker (Odoo 17, PostgreSQL, Qdrant)

Démarrez la pile d'infrastructure Docker située dans `odoo17-dev` :

```bash
cd ~/odoo-ia-prototype/odoo17-dev
docker compose up -d
```

Les services suivants seront alors en cours d'exécution :
- **Odoo 17.0** : [http://localhost:8069](http://localhost:8069)
- **Base PostgreSQL 16** (Interne)
- **Qdrant Vector DB** : Ports 6333 / 6334
- **Miro RAG API** : Port 8000

---

### 4. Initialisation de la Base de Données Odoo via le Navigateur

1. Ouvrez votre navigateur sur **[http://localhost:8069](http://localhost:8069)**.
2. Si vous accédez à l'écran de création de base de données (*Database Manager*), remplissez le formulaire avec **exactement les paramètres suivants** :
   - **Database Name** : `odoo-dev` *(Indispensable pour la connexion de l'IA)*
   - **Email / Login Admin** : `admin`
   - **Password** : `admin` (ou `odoo`)
   - **Language** : `French / Français`
   - **Country** : `Madagascar` (ou votre choix)
   - **Demo data** : Décoché (les données de test seront injectées proprement par script)
3. Connectez-vous en tant qu'administrateur (`admin`) et rendez-vous dans le menu **Applications (Apps)** pour installer les modules ERP de base :
   - **Ventes** (`sale_management`)
   - **Facturation / Comptabilité** (`account`)
   - **Projets** (`project`)
   - **Inventaire / Stock** (`stock`)

---

### 5. Ingestion et Configuration Automatique des Données Identiques (`full_setup.py`)

Une fois la base `odoo-dev` créée et les applications activées, lancez le script d'initialisation complet pour peupler automatiquement l'instance Odoo avec les données identiques :

```bash
cd ~/odoo-ia-prototype/miro-rag
python3 tools/full_setup.py
```

#### Ce que le script `full_setup.py` crée automatiquement dans Odoo :
- **Société dédiée** : `Company Alpha`
- **Journal comptable** : Journal de ventes `SJA` (*Sales Journal*)
- **Compte de revenus** : Compte `400000` attribué à la catégorie de produits
- **7 Utilisateurs spécialisés** :
  - `Alice Admin` (Admin Ventes/Projets)
  - `Bob Buyer` (Achats/Stock)
  - `Charlie CRM` (Vendeur)
  - `Diana Support` (Support Technique)
  - `Evan Engineer` (Ingénieur Projets)
  - `Fiona Finance` (Facturation)
  - `Miro Manager` (`manager@miro.com` / `password123`)
- **8 Clients (Partenaires)** : *Société Dupont, Madagascar Tech, Telma Madagascar, Groupe Socimex, Brasseries Star, Air Madagascar, Shoprite Madagascar, MIRO KE interne*
- **10 Produits & Services** : *Implémentation Odoo 17, Formation, Support mensuel, Audit ERP, Migration, Développement sur mesure, Maintenance annuelle, Hébergement Cloud, Intégration API, Consulting*
- **Commandes de Ventes (Sale Orders)** : Historique d'achats avec statuts devis (`draft`), confirmé (`sale`), facturé (`posted`) et annulé (`cancel`) issus de `fake_data/sales.json`.
- **Tickets de Support / Projets** : Projet *MIRO Support Tickets* et tâches associées aux clients issues de `fake_data/tickets.json`.

---

### 6. Exécution du Benchmark de Précision IA

Pour vérifier que tout fonctionne et que l'assistant IA répond correctement sur votre nouvelle instance :

```bash
python3 tests/test_erp_accuracy.py
```

Le rapport d'évaluation complet sera généré dans `miro-rag/captures/erp_accuracy_report.md`.

---

## 📁 Structure du Projet

- **`odoo17-dev/`** : Configuration Docker Compose pour Odoo 17, PostgreSQL 16, Qdrant et le dossier des modules personnalisés `addons/`.
- **`miro-rag/`** : Code source de l'assistant IA RAG, des outils XML-RPC Odoo, des prompts LangGraph et du moteur d'évaluation.
- **`miro-rag/tools/full_setup.py`** : Script d'injection unifié et d'initialisation de la base de données `odoo-dev`.
- **`miro-rag/fake_data/`** : Datasets JSON sources (ventes, tickets, stocks).
- **`scripts/`** : Benchmarks contradictoires et scripts d'extraction de métadonnées Odoo.