# Guide Utilisateur : Assistant Odoo MIRO AI

Bienvenue sur le guide d'utilisation de **MIRO AI**, votre assistant intelligent intégré directement dans Odoo 17. 

Cet assistant est capable de répondre à vos questions sur les documents de l'entreprise (procédures, RH, facturation) et d'interroger directement les données commerciales de votre base Odoo, tout en respectant strictement vos droits d'accès.

---

## 1. Où trouver l'Assistant MIRO AI ?

Une fois le module installé par votre administrateur :
1. Connectez-vous à votre interface Odoo 17.
2. Cliquez sur l'icône **MIRO AI** dans le menu principal (en haut à gauche).
3. Une fenêtre de discussion (Chat) s'ouvre, similaire à une messagerie classique.

---

## 2. Que pouvez-vous lui demander ? (Exemples)

L'assistant possède deux cerveaux : le cerveau **Documentaire (RAG)** et le cerveau **Données ERP (Odoo)**. Il comprend automatiquement quel type de question vous posez.

### 🎯 Poser des questions sur les documents (Procédures, Wiki, RH)
L'assistant parcourt instantanément tous les PDF, Word et mémos de l'entreprise pour vous répondre.

- *« Comment dois-je créer une facture client selon la procédure interne ? »*
- *« Combien de jours de congés sont autorisés pour un mariage ? »*
- *« Résume-moi le contenu du fichier "manuel_facturation.pdf". »*

> **Astuce :** À la fin de sa réponse, l'assistant vous affichera toujours les **Sources** (ex: `Source: manuel_facturation.pdf (page 2)`). Vous pouvez vérifier l'information d'un coup d'œil !

### 📊 Poser des questions sur les données chiffrées Odoo (Ventes, Stocks, Factures)
L'assistant est connecté à Odoo en temps réel. S'il a besoin d'un chiffre, il va le chercher.

- *« Quel est le chiffre d'affaires généré par le client Rakoto ce mois-ci ? »*
- *« Reste-t-il du stock pour le produit "Clavier Mécanique RGB" ? »*
- *« Liste-moi les produits actuellement en rupture de stock. »*
- *« Quel est le total des factures impayées (draft) ? »*

### 🔄 Poser des questions hybrides ou suivre la discussion
L'assistant possède une mémoire de la conversation !

- *Vous : « Quel est le chiffre d'affaires de Rakoto en 2025 ? »*
- *Agent : « Le chiffre d'affaires est de 60 000 Ar. »*
- *Vous : « Et pour l'année 2026 ? »* (L'assistant comprendra que vous parlez toujours de Rakoto).

---

## 3. Comprendre les indicateurs visuels

### La jauge de Confiance (Confidence)
Sous chaque réponse, vous verrez un badge coloré :
- 🟢 **Confiance Haute (> 80%) :** L'assistant est très sûr de lui. Il a trouvé des sources solides ou la base de données a renvoyé des chiffres clairs.
- 🟡 **Confiance Moyenne (50% - 80%) :** L'assistant a trouvé des éléments mais certaines nuances lui échappent, vérifiez les sources.
- 🔴 **Confiance Basse (< 50%) :** L'assistant doute. L'information n'existe probablement pas ou il a été bloqué par sécurité.

### L'avertissement de Qualité (⚠️ OCR)
Si vous voyez ce symbole : ⚠️ `Attention, source issue d'un document scanné de mauvaise qualité`, cela signifie que l'assistant a lu un vieux PDF scanné. Des erreurs de lecture (chiffres flous, lettres manquantes) sont possibles. Revérifiez le document original.

---

## 4. Sécurité et Confidentialité (Important)

L'assistant **ne voit que ce que vous avez le droit de voir**. 

- **Cloisonnement total :** Si vous travaillez pour la société "Alpha" dans un Odoo multi-sociétés, l'assistant ne vous répondra jamais avec des données de la société "Beta", même si vous le forcez.
- **Droits d'accès :** Si vous n'êtes pas du service Comptabilité dans Odoo, l'assistant refusera de vous donner le total des factures de l'entreprise.
- **Lecture Seule :** Ne demandez jamais à l'assistant de créer, supprimer ou modifier une facture. **L'assistant n'a pas les droits d'écriture.** Il est là pour vous informer.

---

## 5. Foire Aux Questions (FAQ)

**Q : L'assistant me répond "Je n'ai pas de source fiable pour répondre à cette question", pourquoi ?**
*R : Soit le document n'a pas encore été importé dans le dossier de l'entreprise, soit la question sort complètement du cadre professionnel (ex: questions personnelles), soit vous n'avez pas les droits Odoo pour voir la donnée demandée.*

**Q : J'ai mis un nouveau PDF dans le dossier partagé, est-ce que l'assistant le connaît déjà ?**
*R : Oui ! Grâce à son système de "Watcher", dès qu'un document est déposé dans le répertoire, il est lu et mémorisé en **3 secondes environ**. Posez-lui la question !*

**Q : L'assistant peut-il se tromper sur un chiffre d'affaires ?**
*R : Rarement. Sur les données Odoo, l'assistant fait une vraie requête mathématique en base de données. Cependant, si vous demandez "Les ventes de Rakoto" et qu'il y a 3 clients nommés "Rakoto", il se peut qu'il additionne tout. Soyez le plus précis possible dans vos questions (ex: "Le client Rakoto SARL").*
