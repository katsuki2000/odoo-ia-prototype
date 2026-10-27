# Guide de Déploiement et Maintenance des Modules Odoo 17

> Procédure standard de gestion de versions, tests automatisés et mise en production pour l'infrastructure Miro K.E.

---

## 1. Environnements et conventions Git

Le cycle de vie du code repose sur 3 environnements distincts :

- **Local / Dev** : Poste individuel avec base SQLite ou PostgreSQL locale.
- **Staging / Recette** : `https://staging.miroke.mg` miroir de la production, synchronisé chaque lundi matin.
- **Production** : `https://erp.miroke.mg` hébergé sur le cluster sécurisé d'Ankorondrano.

### Stratégie de branches Git
- `main` : Reflète l'état exact déployé en production. Protégée contre les push directs.
- `staging` : Branche d'intégration pour les tests utilisateurs et la validation QA.
- `feature/<nom-module>-<ticket>` : Branche de développement isolée issue de `staging`.

---

## 2. Déploiement et mise à jour de la base de données (-u)

Pour déployer une mise à jour d'un module personnalisé, la commande `odoo-bin` doit être invoquée avec l'option `-u` ciblée :

```bash
# Exemple de mise à jour sécurisée du module de facturation Miro
./odoo-bin -c /etc/odoo/odoo.conf -d miroke_prod -u miro_facturation --stop-after-init --log-level=warn
```

### Vérifications pré-déploiement
- Vérifier que toutes les migrations de schéma dans le dossier `migrations/` sont idempotentes.
- Exécuter la suite de tests automatisés :
```bash
pytest tests/ -m "not slow"
```
- Effectuer un snapshot PostgreSQL avant toute mise à jour majeure :
```bash
pg_dump -Fc -U odoo miroke_prod > /backup/miroke_prod_pre_deploy_$(date +%Y%m%d_%H%M).dump
```

---

## 3. Procédure de Rollback et plan de secours

En cas d'échec critique lors de l'initialisation du service :

1. Arrêter immédiatement le service systemd :
```bash
sudo systemctl stop odoo
```
2. Restaurer la version antérieure du code via Git :
```bash
git checkout HEAD~1
```
3. Si le schéma de base de données est corrompu, restaurer le dump pris à l'étape préalable :
```bash
dropdb -U odoo miroke_prod && createdb -U odoo miroke_prod
pg_restore -U odoo -d miroke_prod /backup/miroke_prod_pre_deploy_*.dump
```
4. Relancer le service et vérifier les journaux d'erreurs :
```bash
sudo systemctl start odoo && sudo journalctl -u odoo -n 100 -f
```

---

## 4. Checklist de mise en production

- [ ] Revue de code approuvée par au moins un Lead Développeur
- [ ] Tests de non-régression passés avec succès
- [ ] Fenêtre de maintenance annoncée aux utilisateurs (mardi ou jeudi à 20h00)
- [ ] Cache navigateur et assets statiques Odoo régénérés (`--dev=all` désactivé)
- [ ] Notification envoyée au canal `#deploiements-erp`
