# Deploiement de MIRO AI : de l'etat actuel (poste de dev) a l'etat deploye

Ce guide suit le schema de deploiement retenu : une VM Azure (credit etudiant) qui heberge Odoo 17, PostgreSQL, l'API FastAPI et ChromaDB, et une instance AWS GPU qui sert Ollama. Les deux machines sont reliees par un tunnel SSH. L'utilisateur n'accede qu'a Odoo, en HTTPS, sur un sous-domaine du nom de domaine `.tech`.

Aucun changement de code n'est necessaire : tout passe par le `.env`, `odoo.conf` et des services systemd. Les commandes sont a lancer par toi, machine par machine.

Notations : `<user>` = utilisateur Linux de la VM Azure, `<user_aws>` = utilisateur Linux de l'instance AWS, `<IP_AZURE>` et `<IP_AWS>` = adresses publiques, `<domaine>.tech` = ton nom de domaine, `erp.<domaine>.tech` = le sous-domaine d'Odoo, `<base>` = nom de la base Odoo de production (par exemple `miro-prod`).

## 0. Vue d'ensemble

```text
Navigateur --HTTPS 443--> nginx --> Odoo (127.0.0.1:8069) --> PostgreSQL (127.0.0.1:5432)
                                       |
                                       +--HTTP 127.0.0.1:8000--> API FastAPI + ChromaDB
                                                                      |
Google Drive --synchro toutes les 5 min-------------------------------+
                                                                      |
                              tunnel SSH (127.0.0.1:11434 de la VM Azure vers 127.0.0.1:11434 d'AWS)
                                                                      |
                                                           Ollama sur AWS (gemma4:26b, bge-m3:latest)
```

Ports ouverts sur Internet : 80 et 443 (VM Azure), 22 (VM Azure et instance AWS, limite a des IP connues). Jamais 8069, 8000, 5432 ni 11434.

Ordre des etapes : 1 AWS, 2 Azure, 3 DNS, 4 systeme, 5 tunnel, 6 code, 7 PostgreSQL et Odoo, 8 base de donnees, 9 `.env`, 10 services, 11 nginx et HTTPS, 12 reglages MIRO AI, 13 verifications.

## 1. Instance AWS (Ollama)

1. Instance GPU avec assez de VRAM pour `gemma4:26b` et `bge-m3:latest` (voir `scripts/measure_vram_ec2.md` pour la mesure deja faite). Verifier avec `nvidia-smi` et `ollama ps` que le modele tient en VRAM.
2. Installer Ollama puis recuperer les modeles utilises par `config/settings.py` :
   ```bash
   ollama pull gemma4:26b
   ollama pull bge-m3:latest
   ```
3. Ollama doit ecouter en local seulement :
   ```bash
   ss -ltnp | grep 11434
   ```
   Attendu : `127.0.0.1:11434`. Si c'est `0.0.0.0` ou `*`, retirer la variable `OLLAMA_HOST=0.0.0.0` du service (`sudo systemctl edit ollama`) et redemarrer. Ollama n'a aucune authentification : ne jamais l'exposer.
4. Groupe de securite AWS : seul le port 22 est ouvert, de preference depuis `<IP_AZURE>` uniquement (IP statique, voir etape 2).
5. Sans IP elastique, l'IP publique change a chaque arret/demarrage de l'instance : mettre a jour `<IP_AWS>` dans le service du tunnel (etape 5).

## 2. VM Azure

1. Creer la VM : Debian 12 (Python 3.11, comme le poste de dev), 8 Go de RAM conseilles pour Odoo + PostgreSQL + API + ChromaDB, 64 Go de disque. Les tailles et regions autorisees dependent de l'abonnement etudiant : verifier dans le portail avant de creer.
2. Authentification SSH par cle uniquement.
3. Passer l'adresse IP publique en statique (sinon elle change quand la VM est desallouee et le DNS ne pointe plus au bon endroit).
4. Groupe de securite reseau (NSG) : entrant 80 et 443 depuis Internet, 22 depuis ton IP.

## 3. DNS

Chez le registrar du `.tech` : enregistrement de type A, nom `erp`, valeur `<IP_AZURE>`. Verifier :

```bash
dig +short erp.<domaine>.tech
```

La propagation peut prendre quelques minutes. Le certificat (etape 11) en depend.

## 4. Paquets systeme (VM Azure)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip python3-dev \
    postgresql postgresql-client libpq-dev \
    git build-essential libxml2-dev libxslt1-dev \
    libjpeg-dev libfreetype6-dev zlib1g-dev \
    libsasl2-dev libldap2-dev libssl-dev \
    node-less npm \
    nginx certbot python3-certbot-nginx autossh
```

## 5. Tunnel SSH vers Ollama

Sur la VM Azure, une cle dediee (la cle AWS personnelle ne quitte jamais ton poste) :

```bash
ssh-keygen -t ed25519 -f ~/.ssh/tunnel_ollama -N "" -C tunnel-azure
cat ~/.ssh/tunnel_ollama.pub
```

Sur l'instance AWS, ajouter la cle publique a `~/.ssh/authorized_keys` en la restreignant au seul port d'Ollama :

```text
restrict,port-forwarding,permitopen="127.0.0.1:11434" ssh-ed25519 AAAA...cle-publique... tunnel-azure
```

Test depuis la VM Azure :

```bash
ssh -N -L 127.0.0.1:11434:127.0.0.1:11434 -i ~/.ssh/tunnel_ollama <user_aws>@<IP_AWS> &
curl http://127.0.0.1:11434/api/tags
```

Attendu : la liste des modeles d'Ollama. Arreter le test (`kill %1`), puis creer le service `/etc/systemd/system/miro-tunnel.service` :

```ini
[Unit]
Description=SSH tunnel to Ollama (AWS)
After=network-online.target
Wants=network-online.target

[Service]
User=<user>
Environment=AUTOSSH_GATETIME=0
ExecStart=/usr/bin/autossh -M 0 -N \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new \
  -i /home/<user>/.ssh/tunnel_ollama \
  -L 127.0.0.1:11434:127.0.0.1:11434 <user_aws>@<IP_AWS>
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now miro-tunnel
curl http://127.0.0.1:11434/api/tags
```

## 6. Code et environnements Python (VM Azure)

Le projet et Odoo ont chacun leur venv, comme sur le poste de dev. Le projet doit etre clone a cote d'Odoo (`ODOO_SOURCE_PATH` a pour defaut `../odoo-17.0`).

```bash
cd ~
git clone https://github.com/katsuki2000/odoo-ia-prototype.git
cd odoo-ia-prototype
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

cd ~
git clone https://github.com/odoo/odoo.git --branch 17.0 --depth 1 odoo-17.0
cd odoo-17.0
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

Le dossier `secrets/` n'est pas dans Git : copier `secrets/miro-drive-reader.json` depuis ton poste (`scp`) puis `chmod 600`.

## 7. PostgreSQL et Odoo

Mot de passe fort (ne pas reprendre `odoo/odoo` du README, valable en local seulement) :

```bash
sudo -u postgres createuser -s odoo
sudo -u postgres psql -c "ALTER USER odoo WITH PASSWORD '<mot-de-passe-pg>';"
sudo -u postgres createdb -O odoo <base>
```

Fichier `~/odoo-17.0/odoo.conf` (`chmod 600`) :

```ini
[options]
db_host = 127.0.0.1
db_port = 5432
db_user = odoo
db_password = <mot-de-passe-pg>
db_name = <base>
dbfilter = ^<base>$
list_db = False
admin_passwd = <mot-de-passe-maitre-odoo>
addons_path = addons,/home/<user>/odoo-ia-prototype/odoo_addons
http_interface = 127.0.0.1
http_port = 8069
proxy_mode = True
workers = 0
```

`proxy_mode` fait qu'Odoo fait confiance aux en-tetes de nginx (liens en `https://`). `http_interface = 127.0.0.1` interdit l'acces direct par le port 8069. `list_db = False` cache le gestionnaire de bases. Avec `workers = 0` (suffisant pour le PoC), le websocket passe par le port 8069 ; avec `workers > 0` il faudrait une route `/websocket` vers le port 8072 dans nginx.

## 8. Base de donnees

Deux options.

Option A, base neuve avec donnees de demonstration :

```bash
cd ~/odoo-17.0
.venv/bin/python odoo-bin -c odoo.conf -i base,miro_ai --stop-after-init
```

Ajouter `--without-demo=all` pour une base vide. Ajouter `-i maintenance` seulement si les questions de banc d'essai sont rejouees.

Option B, reprise de la base de dev :

```bash
# sur le poste de dev
pg_dump -Fc odoo-dev > odoo-dev.dump
tar czf filestore.tgz -C ~/.local/share/Odoo/filestore odoo-dev

# copie vers la VM
scp odoo-dev.dump filestore.tgz <user>@<IP_AZURE>:~

# sur la VM
pg_restore --no-owner --role=odoo -d <base> odoo-dev.dump
mkdir -p ~/.local/share/Odoo/filestore
tar xzf filestore.tgz -C ~/.local/share/Odoo/filestore
mv ~/.local/share/Odoo/filestore/odoo-dev ~/.local/share/Odoo/filestore/<base>
cd ~/odoo-17.0 && .venv/bin/python odoo-bin -c odoo.conf -u miro_ai --stop-after-init
```

Apres une reprise, verifier aussi : le mot de passe du compte `admin` (a changer), `web.base.url` (etape 12) et les reglages MIRO AI (une seule configuration, voir section 1578 du journal).

## 9. Fichier `.env` du projet

```bash
cd ~/odoo-ia-prototype
cp .env.example .env
chmod 600 .env
```

Valeurs a renseigner :

```dotenv
LLM_TARGET=aws
OLLAMA_HOST=http://127.0.0.1:11434
ODOO_URL=http://127.0.0.1:8069
ODOO_DB=<base>
ODOO_ADMIN_LOGIN=admin
ODOO_ADMIN_PASSWORD=<mot-de-passe-du-compte-admin-odoo>
JWT_SECRET=<secret-32-octets-minimum>
GOOGLE_DRIVE_FOLDER_IDS=<id1>,<id2>
GOOGLE_APPLICATION_CREDENTIALS=secrets/miro-drive-reader.json
GOOGLE_DRIVE_APPROVED_FOR_RAG=true
```

- `OLLAMA_HOST` pointe sur le tunnel local, pas sur l'adresse AWS.
- `ODOO_URL` reste en `http://127.0.0.1:8069` : l'API parle a Odoo directement, sans passer par nginx.
- `JWT_SECRET` doit etre identique au champ `api_token` des reglages MIRO AI dans Odoo (etape 12). Generer par exemple : `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`.
- Ne pas mettre `ODOO_BENCH_PASSWORD` sur la VM (inutile au fonctionnement) ni `API_HOST` (la valeur par defaut `127.0.0.1` est la bonne) ni `CORS_ALLOWED_ORIGINS`.

## 10. Services Odoo et API

`/etc/systemd/system/odoo.service` :

```ini
[Unit]
Description=Odoo 17
After=network-online.target postgresql.service

[Service]
User=<user>
WorkingDirectory=/home/<user>/odoo-17.0
ExecStart=/home/<user>/odoo-17.0/.venv/bin/python odoo-bin -c odoo.conf
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/miro-api.service` (sans `--reload`, en ecoute locale) :

```ini
[Unit]
Description=MIRO AI API
After=network-online.target miro-tunnel.service odoo.service
Wants=miro-tunnel.service

[Service]
User=<user>
WorkingDirectory=/home/<user>/odoo-ia-prototype
ExecStart=/home/<user>/odoo-ia-prototype/.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Le `.env` est lu par le code (`config/settings.py`), pas besoin de `EnvironmentFile`. L'API synchronise le Drive au demarrage puis toutes les 5 minutes : la premiere synchro calcule les embeddings `bge-m3` a travers le tunnel, elle est lente. Ne pas lancer `google_drive_cli` pendant que l'API tourne (voir README, Step 9).

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now odoo miro-api
sudo systemctl status odoo miro-api miro-tunnel
```

## 11. nginx et HTTPS

`/etc/nginx/sites-available/odoo` :

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    server_name erp.<domaine>.tech;
    client_max_body_size 100m;

    proxy_read_timeout 720s;
    proxy_connect_timeout 720s;
    proxy_send_timeout 720s;

    location / {
        proxy_pass http://127.0.0.1:8069;
        proxy_redirect off;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/odoo /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d erp.<domaine>.tech
sudo certbot renew --dry-run
```

Certbot ajoute le bloc 443 et la redirection HTTP vers HTTPS, et renouvelle le certificat tout seul. Prerequis : l'enregistrement DNS de l'etape 3 doit deja pointer sur la VM et le port 80 etre ouvert dans le NSG.

## 12. Reglages dans Odoo

1. Connexion sur `https://erp.<domaine>.tech` avec le compte `admin` ; changer son mot de passe.
2. Parametres, Parametres systeme (mode developpeur) : `web.base.url` = `https://erp.<domaine>.tech`.
3. MIRO AI, Configuration, Settings (une seule configuration) :
   - URL de l'API : `http://127.0.0.1:8000` ;
   - secret `api_token` : le meme que `JWT_SECRET` du `.env` (copier l'un vers l'autre, puis `sudo systemctl restart miro-api`) ;
   - delai maximal de requete : superieur au delai LLM (`LLM_REQUEST_TIMEOUT_SECONDS` = 90 s dans `config/settings.py`), par exemple 300 s, car un chargement a froid du modele a travers le tunnel est plus lent.

## 13. Verifications

Sur la VM :

```bash
curl http://127.0.0.1:11434/api/tags      # tunnel et Ollama
curl http://127.0.0.1:8000/health         # API
curl -I https://erp.<domaine>.tech        # Odoo derriere nginx, certificat valide
sudo ss -ltnp | grep -E '8069|8000|11434|5432'   # tous sur 127.0.0.1
journalctl -u miro-api -n 50 --no-pager   # synchro Drive, erreurs
```

Depuis un autre poste : `nc -zv <IP_AZURE> 8069` et `nc -zv <IP_AZURE> 8000` doivent echouer.

Dans le navigateur :
1. Poser une question en mode « From the documentation » : la reponse doit finir par une ligne `Sources:` avec des liens Drive cliquables.
2. Poser une question en mode « From the system » (par exemple le nombre de partenaires) : la reponse doit correspondre aux droits de l'utilisateur connecte.
3. Rouvrir la conversation depuis l'historique : la reponse y est toujours.

## 14. Exploitation courante

- Economiser le credit : arreter la VM depuis le portail Azure (etat « desalloue »). Un `shutdown` depuis le systeme laisse la VM facturee. Arreter aussi l'instance AWS GPU quand elle ne sert pas.
- Au redemarrage : les services demarrent seuls ; verifier le tunnel (`systemctl status miro-tunnel`). Si l'IP AWS a change, corriger `<IP_AWS>` dans le service puis `sudo systemctl daemon-reload && sudo systemctl restart miro-tunnel miro-api`.
- Mise a jour du code :
  ```bash
  cd ~/odoo-ia-prototype && git pull && .venv/bin/pip install -r requirements.txt
  sudo systemctl restart miro-api
  cd ~/odoo-17.0 && .venv/bin/python odoo-bin -c odoo.conf -u miro_ai --stop-after-init
  sudo systemctl restart odoo
  ```
- Sauvegarde : `pg_dump -Fc <base> > sauvegarde.dump` et copie du filestore (`~/.local/share/Odoo/filestore/<base>`). Le dossier ChromaDB se reconstruit par la synchro Drive.
- Journaux : `journalctl -u odoo`, `journalctl -u miro-api`, `journalctl -u miro-tunnel`.

## 15. Securite : liste de controle

- Ports 8069, 8000, 5432 et 11434 fermes depuis Internet (NSG Azure, groupe de securite AWS).
- Ollama en `127.0.0.1` sur AWS ; cle du tunnel dediee et restreinte par `permitopen`.
- `.env`, `odoo.conf` et `secrets/` en `chmod 600`, jamais dans Git.
- Mots de passe changes : PostgreSQL, compte `admin` Odoo, mot de passe maitre `admin_passwd`.
- `list_db = False`, `proxy_mode = True`, `http_interface = 127.0.0.1`.
- SSH par cle uniquement, port 22 limite a des IP connues.

## 16. Pannes frequentes

- Message d'erreur de connexion ou reponses qui n'arrivent plus : tunnel tombe ou IP AWS changee (`systemctl status miro-tunnel`, `curl http://127.0.0.1:11434/api/tags`).
- Reponse coupee apres un long moment : delai des reglages MIRO AI ou `proxy_read_timeout` trop court.
- Erreur d'authentification entre Odoo et l'API : `api_token` different de `JWT_SECRET`.
- Mode documentation sans source : `GOOGLE_DRIVE_APPROVED_FOR_RAG` a `false`, identifiants Drive manquants, ou premiere synchro encore en cours (`journalctl -u miro-api`).
- Liens en `http://` ou boucle de redirection : `proxy_mode` absent ou en-tete `X-Forwarded-Proto` manquant dans nginx.
- Certificat refuse : le DNS ne pointe pas encore sur la VM ou le port 80 est ferme.

## 17. Plan B pour le LLM : Kaggle

Utilisable pour une demonstration ponctuelle seulement (session limitee, URL qui change). Dans le `.env` : `LLM_TARGET=kaggle` et `KAGGLE_OLLAMA_HOST=https://<tunnel-ngrok>`, puis `sudo systemctl restart miro-api`. Le notebook doit exposer Ollama par un tunnel sortant (ngrok ou cloudflared), car Kaggle n'accepte aucune connexion entrante.
