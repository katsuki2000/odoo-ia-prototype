# S13 Documentary Non-Regression Report

**Score: 10/10 (100.0%) - PASS**

---

### [DOC-01] Comment créer une facture client dans Odoo 17 ?
**Status:** PASS
**Answer:** Pour créer une facture client dans Odoo 17, suivez ces étapes : Aller dans Comptabilité > Clients > Factures > Nouveau. Sélectionner le client, ajouter les lignes de produits, puis cliquer sur Confirm...
**Matched keywords:** ['comptabilité', 'clients', 'factures', 'nouveau', 'confirmer']
**Source found:** True (expected: ['manuel_facturation.pdf'])

---

### [DOC-02] Comment envoyer une facture par email depuis Odoo ?
**Status:** PASS
**Answer:** Pour envoyer une facture par email depuis Odoo, suivez ces étapes : Aller dans la facture confirmée, cliquer sur Envoyer et Imprimer. Odoo générera automatiquement un email avec le PDF de la facture e...
**Matched keywords:** ['envoyer et imprimer', 'email', 'pdf', "modèle d'email"]
**Source found:** True (expected: ['manuel_facturation.pdf'])

---

### [DOC-03] Comment créer un avoir (note de crédit) dans Odoo ?
**Status:** PASS
**Answer:** Pour créer un avoir (note de crédit) dans Odoo, suivez les étapes suivantes : Depuis la facture confirmée, cliquez sur Avoir. Choisissez la date et le journal, puis confirmez. L'avoir doit être approu...
**Matched keywords:** ['avoir', 'facture', 'directeur général', 'miro ke']
**Source found:** True (expected: ['manuel_facturation.pdf'])

---

### [DOC-04] Comment configurer les relances automatiques dans Odoo ?
**Status:** PASS
**Answer:** Pour configurer les relances automatiques dans Odoo, suivez ces étapes : 

1. Allez dans Comptabilité > Configuration > Niveaux de relance.
2. Sélectionnez le niveau de relance souhaité (rappel doux, ...
**Matched keywords:** ['relances', 'niveaux de relance', 'rappel doux', 'rappel ferme', 'mise en demeure']
**Source found:** True (expected: ['manuel_facturation.pdf'])

---

### [DOC-05] Qui peut approuver une mise à disposition selon le wiki interne ?
**Status:** PASS
**Answer:** Selon le wiki interne, une demande de mise à disposition doit être approuvée par le Directeur Technique si le montant est inférieur à 500 000 Ar, et par le Directeur Général si le montant est égal ou ...
**Matched keywords:** ['directeur technique', 'directeur général', '500 000 ar']
**Source found:** True (expected: ['wiki_approbation.txt'])

---

### [DOC-06] Quelle est la procédure de validation d'une facture selon le wiki ?
**Status:** PASS
**Answer:** Une facture est validée comme suit : Créée par le comptable, vérifiée par le Responsable Administratif, envoyée au client uniquement après double validation. Tout avoir doit être approuvé par le Direc...
**Matched keywords:** ['comptable', 'responsable administratif', 'double validation']
**Source found:** True (expected: ['wiki_approbation.txt'])

---

### [DOC-07] Quels sont les modules Odoo considérés comme sensibles et qui y a accès ?
**Status:** PASS
**Answer:** Les modules Odoo considérés comme sensibles sont la Comptabilité et RH. Le module Comptabilité est accessible aux Directeurs et aux Comptables, tandis que le module RH est accessible aux DRH et aux Di...
**Matched keywords:** ['comptabilité', 'rh', 'directeur', 'comptable', 'drh']
**Source found:** True (expected: ['wiki_approbation.txt'])

---

### [DOC-08] Quel est le délai de traitement pour une demande de mise à disposition ?
**Status:** PASS
**Answer:** 48 heures ouvrables

[Source: Documentation Odoo - WIKI INTERNE MIRO KE — Procédure d'approbation des demandes]...
**Matched keywords:** ['48h', '48 heures', 'ouvrables']
**Source found:** True (expected: ['wiki_approbation.txt'])

---

### [DOC-09] Qui doit approuver un avoir dans la politique interne de MIRO KE ?
**Status:** PASS
**Answer:** L'avoir doit être approuvé par le Directeur Général selon la politique interne de MIRO KE.

⚠️ *Cette information provient d'un document numérisé dont la qualité de lecture est limitée.*

[Source: Doc...
**Matched keywords:** ['directeur général']
**Source found:** True (expected: ['manuel_facturation.pdf', 'wiki_approbation.txt'])

---

### [DOC-10] Quels sont les trois niveaux de relance disponibles dans Odoo ?
**Status:** PASS
**Answer:** Les trois niveaux de relance disponibles dans Odoo sont : rappel doux, rappel ferme et mise en demeure.

[Source: Documentation Odoo - /home/user/odoo-ia-prototype/miro-rag/fake_data/documents/manuel_...
**Matched keywords:** ['rappel doux', 'rappel ferme', 'mise en demeure']
**Source found:** True (expected: ['manuel_facturation.pdf'])

---

