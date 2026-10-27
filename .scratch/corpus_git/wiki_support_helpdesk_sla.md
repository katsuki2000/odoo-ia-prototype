# WIKI INTERNE MIRO KE — Procédure Helpdesk et Gestion des Incidents (SLA)

> Ce document définit l'organisation du support informatique interne et client, la classification des tickets ainsi que les engagements de niveau de service (Service Level Agreement).

---

## 1. Canaux de contact et création de tickets

Tous les incidents et demandes d'assistance doivent impérativement être enregistrés dans le module Odoo Helpdesk.

- **Portail web** : https://support.miroke.mg/helpdesk
- **Email entrant** : support@miroke.mg (création automatique du ticket)
- **Ligne directe d'urgence** : Poste interne 404 (exclusivement réservée aux blocages P1)

Aucune demande transmise par messagerie instantanée privée (Slack, WhatsApp) ne sera traitée sans création préalable d'un ticket.

---

## 2. Matrice de priorité et Engagements de Service (SLA)

Les délais de prise en charge et de résolution dépendent de l'impact métier et du niveau de sévérité attribué :

| Priorité | Description de l'impact | Temps de 1ère réponse | Temps de résolution cible |
| --- | --- | --- | --- |
| P1 - Critique | Blocage complet de la production ou de la facturation Odoo | < 30 minutes | < 4 heures |
| P2 - Majeur | Dégradation sévère d'une fonctionnalité clé sans contournement | < 2 heures | < 8 heures ouvrées |
| P3 - Normal | Incident impactant un seul utilisateur avec solution de contournement | < 4 heures | < 24 heures ouvrées |
| P4 - Mineur | Demande d'évolution, question d'usage ou amélioration cosmétique | < 24 heures | Selon sprint bi-mensuel |

---

## 3. Workflow de résolution et escalade Odoo Helpdesk

Chaque ticket suit un cycle de vie standard dans les colonnes du Kanban Odoo :

1. **Nouveau** : Ticket reçu, non assigné. Le dispatcher vérifie la complétude des informations.
2. **En cours** : Pris en charge par un technicien N1 ou N2. Diagnostic et reproduction de l'anomalie.
3. **En attente tiers/client** : Mise en pause automatique du compteur SLA en attendant les compléments.
4. **Escalade R&D (N3)** : Si le problème nécessite un correctif de code Python ou XML dans les modules custom.
5. **Résolu** : Solution appliquée et validée en environnement de pré-production / staging.
6. **Fermé** : Clôture définitive après confirmation de l'utilisateur ou après 72h sans réponse.

---

## 4. Enquête de satisfaction et amélioration continue

À la fermeture de chaque ticket, une enquête de satisfaction automatique à 3 niveaux (Satisfait, Neutre, Insatisfait) est envoyée par email. 

Toute note d'insatisfaction déclenche un appel de suivi sous 24h par le Responsable Qualité Support.
