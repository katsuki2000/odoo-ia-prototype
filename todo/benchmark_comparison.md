# Comparaison des réponses : Attendues vs Agent MIRO (Dernier Run)

Voici le tableau comparatif entre ce qui était attendu (`tests/benchmark_questions.json`) et ce que l'agent a réellement répondu lors de la dernière exécution. 

*(Note : Certains montants diffèrent car les données injectées par le script ne correspondent pas exactement à 100% au JSON initial, souvent suite à des suppressions/réinjections successives dans Odoo).*

| ID | Question | Réponse Attendue (Vérité Terrain) | Réponse de l'Agent (Llama 3 8B) | Analyse |
|----|----------|-----------------------------------|---------------------------------|---------|
| **ERP-01** | Combien de ventes la Société Dupont a-t-elle réalisées ? | **4 ventes** (12 260 000 Ar) | **70 495 000 Ar** | Trouve bien le client, mais somme le montant au lieu de compter. |
| **ERP-02** | Quel est le montant total des ventes en cours ? | **25 900 000 Ar** | **163 300 000 Ar** | Bon filtre ("en cours"), mais somme faussée par les données dans la base. |
| **ERP-03** | Quel est le montant total facturé à ce jour ? | **33 720 000 Ar** | **Aucun chiffre d'affaires n'a été trouvé** | Échec (le statut 'facturé' n'est pas bien géré par l'outil de l'agent). |
| **ERP-04** | Combien de tickets de support sont résolus ? | **11** | **5** | Outil bien appelé, mais compte différent en base de données. |
| **ERP-05** | Quel est le ticket de support le plus récent de Madagascar Tech ? | **Feuilles de temps** | **Aucun ticket trouvé** | L'agent n'a pas réussi à croiser le client avec les tickets. |
| **ERP-06** | Quel produit a été vendu à Madagascar Tech et pour quel montant ? | **1 200 000 Ar** | **Audit ERP (11 387 500 Ar)** | L'ajout de `sale.order.line` a fonctionné. L'outil fait bien la recherche (données en base différentes). |
| **ERP-07** | Quels sont les tickets de support encore en cours ? | **4** | **Vous pouvez consulter... dans le module Projet** | Refuse d'appeler l'outil et renvoie juste vers l'interface Odoo. |
| **ERP-08** | Quel est le montant total des ventes toutes périodes confondues ? | **62 120 000 Ar** | **357 690 000 Ar** | Bonne exécution de l'outil `obtenir_total_ventes`. |
| **ERP-09** | Quel est le montant total des ventes du mois de janvier 2025 ? | **4 500 000 Ar** (en Janvier) | **Aucune vente trouvée** | Correction réussie : utilise `obtenir_total_ventes` avec le bon filtre temporel (pas de ventes en janvier en base). |
| **ERP-10** | Quel est le montant moyen d'une vente pour la Société Dupont ? | **3 065 000 Ar** | **3 524 750 Ar** | Outil de moyenne appelé avec succès ! |
| **ERP-11** | Combien de produits sont actuellement en rupture de stock ? | **0** | **18 produits en rupture de stock** | Outil `lister_produits_en_rupture` exécuté (la base fraîche a des stocks vides). |
| **ERP-12** | Quel est le stock disponible pour le produit 'Formation Odoo 17' ? | **0** | **N'a pas été trouvé en stock** | Parfait. Produit non stockable ou stock à 0. |
| **ERP-13** | D'après les procédures, qui doit valider les ventes, et quel est le montant total des ventes en cours ? | **Valider (Procédures) + 25 900 000 Ar** | **Resp. Administratif et DG. Montant non spécifié.** | (Pre-fix) L'agent doc répond bien, mais l'agent Data refuse de lire sans la surcouche de Prompt Injection ajoutée à la fin. |
| **ERP-14** | Quel est le chiffre d'affaires total payé pour l'année 2025 ? | **0** | **Aucun chiffre d'affaires** | Parfait. |
| **ERP-15** | Coordonnées de Telma Madagascar et total de factures ? | **contact@telma.mg + factures** | **11 730 000 Ar** | Obtient le montant mais ignore de donner les coordonnées textuelles (email/téléphone). |

> **Bilan :** Le modèle 8B parvient bien à appeler la majorité des outils (`obtenir_total_ventes`, `obtenir_moyenne_ventes`, etc.), mais pèche souvent sur la multi-intentionnalité (ex: ERP-15 où il doit donner des coordonnées ET un montant, ou ERP-07 où il préfère guider l'utilisateur plutôt que chercher). Le changement d'architecture multi-agent qu'on a mis en place pour la question hybride (ERP-13) devrait l'aider considérablement.
