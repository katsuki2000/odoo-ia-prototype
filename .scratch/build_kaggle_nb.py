import json, nbformat
from nbformat.v4 import new_notebook, new_code_cell, new_markdown_cell

cells = []

cells.append(new_markdown_cell(r"""# MIRO AI -- Benchmark de precision, modele local (Kaggle, gratuit)

**Portage du notebook Colab** (`scripts/colab/local_llm_benchmark.ipynb`) vers Kaggle Notebooks. Meme objectif : heberger un LLM local (gpt-oss-20b par defaut) sur le GPU gratuit de Kaggle, l'exposer via un tunnel public, puis pointer le pipeline MIRO AI (qui tourne sur TA machine, avec l'acces a l'instance Odoo) vers cette URL pour rejouer le banc de 25 questions Bloc N1 en conditions "locales".

**Regle de confidentialite (ne pas contourner)** : ce notebook ne sert QU'A heberger le modele. Aucune donnee client ou instance Odoo reelle ne doit transiter par cette machine Kaggle -- seul le corpus synthetique du projet (`document_rag/documents/`, modules Odoo de test) doit etre utilise dans le benchmark qui appellera cette URL depuis ta machine.

**Differences vs Colab (a savoir avant de commencer)** :
1. **Reglages de session** : panneau lateral droit -> `Settings` -> `Accelerator` = GPU T4 x2 (ou P100 selon dispo) ; `Internet` = ON (necessaire pour `ollama pull` + le tunnel). Kaggle exige une verification par telephone (une seule fois, compte) pour activer GPU+Internet simultanement.
2. **Quota** : 30h GPU/semaine (remise a zero le lundi), session max ~9h. Le Notebook doit rester en session "Interactive" active pour que le tunnel reste ouvert -- pas de limite d'inactivite aussi stricte que Colab, mais la session se termine si tu fermes l'onglet sans avoir lance en `Save & Run All (Commit)`.
3. **Persistance des poids du modele** : Kaggle n'a pas d'equivalent direct de Google Drive monte en FUSE. L'alternative native est un **Kaggle Dataset prive** (creer une fois via l'API Kaggle, reutiliser en l'attachant en lecture seule aux sessions suivantes via `+ Add Input`). Voir section 2bis ci-dessous -- optionnelle, un re-telechargement complet (~13 Go) a chaque session reste raisonnable sur la bande passante Kaggle (generalement plus rapide que le montage Drive de Colab).
4. **Tunnel public** : Kaggle n'a **aucune fonctionnalite native** de tunnel/port public. `ngrok` fonctionne identiquement a Colab (meme lib `pyngrok`, meme authtoken, stocke cette fois via `Add-ons -> Secrets` au lieu de `userdata` Colab). **Alternative recommandee ici** : `cloudflared` (Cloudflare Quick Tunnel) -- **aucun compte, aucun token requis**, un simple binaire a telecharger. C'est l'option par defaut de ce notebook ; `ngrok` reste disponible en cellule optionnelle si tu preferes une URL plus stable/nommee."""))

cells.append(new_markdown_cell(r"""## 1. Verifier le GPU + les reglages de session"""))

cells.append(new_code_cell(r"""# 1. Verifier le GPU assigne (si erreur "no GPU found" : Settings -> Accelerator -> GPU T4 x2/P100,
# puis redemarrer la session -- ne pas continuer sans GPU, gpt-oss:20b est inutilisable en CPU-only)
!nvidia-smi"""))

cells.append(new_markdown_cell(r"""## 2. Installer Ollama"""))

cells.append(new_code_cell(r"""# 2. Installer Ollama
# zstd requis par l'installeur pour l'extraction ; pciutils (lspci) requis pour la detection GPU --
# l'image Kaggle de base (comme celle de Colab) ne les fournit pas par defaut.
!apt-get -qq update && apt-get -qq install -y zstd pciutils
!curl -fsSL https://ollama.com/install.sh | sh"""))

cells.append(new_markdown_cell(r"""## 2bis. Persistance des poids du modele (optionnel -- Kaggle Dataset prive)

Deux modes, choisis un seul :

- **Mode A (par defaut, le plus simple)** : pas de persistance -- les modeles sont telecharges dans `/kaggle/working/ollama_models` a chaque nouvelle session (perdus a la fin de la session). Bande passante Kaggle generalement rapide (~13 Go en quelques minutes) : acceptable si tu ne relances pas le notebook tous les jours.
- **Mode B (persistant, plus de setup)** : les modeles sont stockes dans un **Kaggle Dataset prive** que tu crees une fois via l'API Kaggle, puis attaches en lecture seule (`+ Add Input` dans le panneau lateral) aux sessions suivantes -- plus de re-telechargement. Necessite un token API Kaggle (`kaggle.json`, recuperable sur https://www.kaggle.com/settings -> `Create New Token`), a stocker via `Add-ons -> Secrets` (nom : `KAGGLE_API_TOKEN`, colle le contenu JSON complet du fichier).

La cellule suivante detecte automatiquement le mode : si un dataset est deja attache (visible sous `/kaggle/input/`), il est utilise directement en lecture seule (Mode B, session de reutilisation) ; sinon on retombe sur `/kaggle/working` (Mode A, ou Mode B en premiere execution -- voir la cellule de sauvegarde optionnelle en fin de notebook)."""))

cells.append(new_code_cell(r"""# 2bis. Detection automatique Mode A / Mode B + configuration OLLAMA_MODELS
import os, glob

# Si tu as attache un Kaggle Dataset contenant les poids (ex: slug "ollama-models-miro"),
# adapte ce prefixe de recherche a ton propre slug de dataset si besoin.
_existing_datasets = glob.glob("/kaggle/input/*ollama*")

if _existing_datasets:
    OLLAMA_MODELS_DIR = _existing_datasets[0]
    READONLY_MODELS = True
    print(f"Mode B (reutilisation) : dataset attache detecte -> {OLLAMA_MODELS_DIR} (lecture seule, pas de pull necessaire).")
else:
    OLLAMA_MODELS_DIR = "/kaggle/working/ollama_models"
    os.makedirs(OLLAMA_MODELS_DIR, exist_ok=True)
    READONLY_MODELS = False
    print(f"Mode A (ephemere) : aucun dataset attache -> {OLLAMA_MODELS_DIR} (telechargement necessaire ci-dessous).")

os.environ["OLLAMA_MODELS"] = OLLAMA_MODELS_DIR"""))

cells.append(new_markdown_cell(r"""## 3. Demarrer le serveur Ollama en arriere-plan"""))

cells.append(new_code_cell(r"""# 3. Demarrer le serveur Ollama en arriere-plan
import subprocess, time, requests

# Tuer tout ollama serve deja lance (orphelin d'une execution precedente de cette cellule sans
# restart complet du runtime) -- sinon le nouveau process echoue au bind du port 11434 silencieusement.
# Rend la cellule rejouable telle quelle (meme precaution que sur Colab).
!pkill -f "ollama serve" || true
time.sleep(2)  # laisser le temps au port de se liberer avant le nouveau bind

# OLLAMA_ORIGINS=* : desactive le controle CORS sur le header Origin. Ne couvre PAS le rejet
# 403 du header Host (protection anti DNS-rebinding distincte, whitelist localhost/127.0.0.1
# uniquement) -- confirme todo/contexte.txt section 2213. La requete traversant le tunnel
# (Host = <xxx>.trycloudflare.com) doit etre corrigee cote tunnel (voir cellule 6, --http-host-header).
os.environ["OLLAMA_ORIGINS"] = "*"

# OLLAMA_CONTEXT_LENGTH=16384 : la fenetre de contexte par defaut d'Ollama (4096 tokens,
# prompt+completion CUMULES) coupe la generation en cours de synthese sur les questions
# multi-hop (observations de plusieurs outils CI concatenes dans le prompt) -- meme root cause
# que sur Colab (todo/contexte.txt Section 710). 16384 laisse une marge large au-dela du pire
# cas observe (4-6 hops, observation_cap 9000 caracteres/outil).
os.environ["OLLAMA_CONTEXT_LENGTH"] = "16384"

# keep_alive=-1 : ne jamais decharger le modele de la VRAM entre deux appels -- le chargement
# initial (surtout en Mode B, lecture depuis le mount /kaggle/input) peut etre plus lent qu'un
# disque local ; un dechargement/rechargement en plein benchmark reintroduirait le meme
# ReadTimeout que le premier appel a froid.
os.environ["OLLAMA_KEEP_ALIVE"] = "-1"

ollama_proc = subprocess.Popen(
    ["ollama", "serve"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    env=os.environ,  # necessaire pour que OLLAMA_MODELS (cellule 2bis) et OLLAMA_KEEP_ALIVE soient pris en compte
)

for _ in range(30):
    try:
        r = requests.get("http://localhost:11434")
        if r.status_code == 200:
            print("Ollama pret.")
            break
    except requests.exceptions.ConnectionError:
        pass
    time.sleep(1)
else:
    raise RuntimeError("Ollama n'a pas demarre a temps -- verifier les logs du processus (ollama_proc.stderr.read()).")"""))

cells.append(new_code_cell(r"""# 3bis. Verifier qu'Ollama a bien detecte le GPU (pas seulement croire le log d'install)
!ollama --version
!nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv"""))

cells.append(new_markdown_cell(r"""## 4. Telecharger les modeles (Mode A) ou verifier leur presence (Mode B)"""))

cells.append(new_code_cell(r"""# 4. Telecharger le modele candidat -- saute en Mode B (dataset deja pull, lecture seule :
# un `ollama pull` echouerait de toute facon en tentant d'ecrire dans /kaggle/input, monte read-only).
# Candidat principal : meme famille que le modele cloud actuel (GROQ_MODEL=openai/gpt-oss-20b)
MODEL = "gpt-oss:20b"

# Alternative de comparaison (si besoin, decommenter) :
# MODEL = "qwen3:14b"

if not READONLY_MODELS:
    !ollama pull {MODEL}
else:
    print(f"Mode B : {MODEL} suppose deja present dans {OLLAMA_MODELS_DIR} -- verification via 'ollama list' :")
    !ollama list"""))

cells.append(new_code_cell(r"""# 4ter. Telecharger le modele d'embedding (repointage RAG) -- meme logique Mode A/B que ci-dessus.
# nomic-embed-text (~274 Mo) -- meme serveur Ollama que le LLM de chat, aucun conflit VRAM
# reel avec gpt-oss:20b (~13 Go) sur les 15-16 Go d'un T4.
EMBED_MODEL = "nomic-embed-text"

if not READONLY_MODELS:
    !ollama pull {EMBED_MODEL}
else:
    print(f"Mode B : {EMBED_MODEL} suppose deja present dans {OLLAMA_MODELS_DIR}.")"""))

cells.append(new_markdown_cell(r"""## 5. Prechauffage + sanity check tool-calling"""))

cells.append(new_code_cell(r"""# 5. Prechauffer le modele en VRAM avant le sanity check
# (le premier appel charge ~13 Go en VRAM -- peut depasser un timeout court, surtout en Mode B
# ou la lecture passe par le mount /kaggle/input)
# IMPORTANT : le payload doit etre identique (y compris 'tools') a celui de la cellule suivante --
# Ollama instancie un runner different selon la presence de 'tools', donc un prechauffage sans
# 'tools' ne prechauffe pas le runner tool-calling reellement utilise ensuite.
import requests, time

_t0 = time.time()
requests.post(
    "http://localhost:11434/v1/chat/completions",
    json={
        "model": MODEL,
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Renvoie la meteo pour une ville donnee.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }],
        "stream": False,
    },
    timeout=600,
)
print(f"Modele charge en VRAM ({time.time() - _t0:.1f}s).")"""))

cells.append(new_code_cell(r"""# 5bis. Sanity check local -- verifier que le tool-calling natif fonctionne
# (condition necessaire pour que le pipeline LangGraph/ReAct de MIRO AI puisse utiliser ce modele)
import requests, json as _json

test_payload = {
    "model": MODEL,
    "messages": [{"role": "user", "content": "Quel temps fait-il a Paris ?"}],
    "tools": [{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Renvoie la meteo pour une ville donnee.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }],
    "stream": False,
}

resp = requests.post("http://localhost:11434/v1/chat/completions", json=test_payload, timeout=300)  # large par securite, le modele est deja prechauffe
resp.raise_for_status()
data = resp.json()
tool_calls = data["choices"][0]["message"].get("tool_calls")
print("Tool calls recus :", _json.dumps(tool_calls, indent=2, ensure_ascii=False))
assert tool_calls, "Le modele n'a pas produit d'appel d'outil -- tool-calling natif KO, ne pas continuer avec ce modele."
print("OK -- tool-calling natif confirme.")"""))

cells.append(new_markdown_cell(r"""## 6. Exposer le serveur via un tunnel public

Kaggle n'a **aucun tunnel natif**. Deux options :

- **Option recommandee : `cloudflared` (Cloudflare Quick Tunnel)** -- aucun compte, aucun token, un binaire a telecharger. URL du type `https://xxx-xxx-xxx.trycloudflare.com`, valable tant que le process tourne. C'est la cellule executee par defaut ci-dessous.
- **Option alternative : `ngrok`** -- identique a Colab, mais le token est stocke via `Add-ons -> Secrets` (icone en haut a droite du notebook Kaggle) au lieu de `userdata` Colab. Cellule fournie plus bas, desactivee par defaut (mettre `USE_NGROK = True` si tu preferes)."""))

cells.append(new_code_cell(r"""# 6. Tunnel via cloudflared (par defaut -- recommande, aucun compte requis)
import subprocess, re, time

!curl -fsSL -o /usr/local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
!chmod +x /usr/local/bin/cloudflared

# --http-host-header="localhost:11434" : reecrit le Host recu par Ollama en localhost, meme
# correctif que celui deja applique a la cellule ngrok (6bis) -- sans ca, Ollama voit
# Host=<xxx>.trycloudflare.com et rejette la requete en 403 silencieux avant tout traitement
# (root cause confirmee todo/contexte.txt sections 682-2213, jamais portee sur le chemin
# cloudflared jusqu'ici -- c'est la cause du 403 systematique observe sur le banc N1).
cloudflared_proc = subprocess.Popen(
    ["cloudflared", "tunnel", "--url", "http://localhost:11434",
     "--http-host-header", "localhost:11434"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
)

public_url = None
_t0 = time.time()
for line in cloudflared_proc.stdout:
    m = re.search(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com", line)
    if m:
        public_url = m.group(0)
        break
    if time.time() - _t0 > 60:
        break

if public_url:
    print("URL publique (temporaire, valable tant que ce notebook tourne) :")
    print(public_url)
else:
    raise RuntimeError("URL cloudflared non trouvee dans les logs apres 60s -- verifier cloudflared_proc.stdout manuellement.")"""))

cells.append(new_code_cell(r"""# 6bis. Alternative ngrok (desactivee par defaut -- mettre USE_NGROK = True pour l'utiliser
# a la place de cloudflared ci-dessus ; ne pas executer les deux tunnels simultanement sur le
# meme port sans raison).
USE_NGROK = False

if USE_NGROK:
    !pip install -q pyngrok
    from pyngrok import ngrok, conf
    from kaggle_secrets import UserSecretsClient

    # Secret Kaggle (icone Add-ons -> Secrets en haut a droite) -- nom exact attendu : NGROK_AUTHTOKEN
    # https://dashboard.ngrok.com/get-started/your-authtoken
    # Ne jamais coller le token en dur ici : ce notebook peut etre partage/versionne.
    user_secrets = UserSecretsClient()
    NGROK_AUTHTOKEN = user_secrets.get_secret("NGROK_AUTHTOKEN")
    conf.get_default().auth_token = NGROK_AUTHTOKEN

    # host_header="localhost:11434" (rewrite) : Ollama rejette en 403 silencieux toute requete
    # dont le header Host ne correspond pas a localhost/127.0.0.1 (protection anti DNS-rebinding,
    # verification distincte du controle CORS Origin couvert par OLLAMA_ORIGINS).
    public_url = ngrok.connect(11434, "http", host_header="localhost:11434")
    print("URL publique ngrok (temporaire, valable tant que ce notebook tourne) :")
    print(public_url)
else:
    print("USE_NGROK=False -- cloudflared (cellule precedente) reste le tunnel actif.")"""))

cells.append(new_markdown_cell(r"""## 7. Cote de ta machine (ou tourne le pipeline MIRO AI / l'acces Odoo)

Dans le `.env` de `odoo-ia-prototype` (ou en variables d'environnement de la session), positionner temporairement :

```
LLM_PROVIDER=ollama
LOCAL_LLM_BASE_URL=<URL_TUNNEL_CI_DESSUS>/v1
LOCAL_LLM_MODEL=gpt-oss:20b
LOCAL_LLM_API_KEY=ollama
```

(`get_chat_llm()` dans `core/llm/llm_client.py` est deja cable pour ce provider.)

Puis, sur ta machine, pour rejouer le banc complet de 25 questions Bloc N1 (aucun id/module en argument = pas de filtre) :

```bash
python scripts/run_bloc_n1_benchmark.py
```

Le rapport sort dans `captures/bloc_n1_verbatim.json` / `.md`, comme pour un run cloud (Groq) -- comparer au dernier run connu.

**Ne pas oublier de remettre `LLM_PROVIDER=groq` (ou de retirer les 4 lignes ci-dessus) une fois le test termine**, pour revenir au comportement par defaut.

**Limite Kaggle gratuit** : 30h GPU/semaine (remise a zero le lundi), session ~9h max. Garder l'onglet/la session active pendant tout le run des 25 questions."""))

cells.append(new_markdown_cell(r"""## 8. (Optionnel) Sauvegarder les poids dans un Kaggle Dataset prive pour la prochaine session

A executer **une seule fois**, en Mode A (premiere session, modeles fraichement telecharges dans `/kaggle/working/ollama_models`), pour eviter de re-telecharger ~13 Go a chaque fois. Necessite le secret `KAGGLE_API_TOKEN` (contenu complet de ton `kaggle.json`, via `Add-ons -> Secrets`). Une fois le dataset cree, attache-le aux sessions suivantes via `+ Add Input -> tes Datasets` : la cellule 2bis le detectera automatiquement (Mode B)."""))

cells.append(new_code_cell(r"""# 8. Push optionnel vers un Kaggle Dataset prive (desactive par defaut)
SAVE_TO_KAGGLE_DATASET = False

if SAVE_TO_KAGGLE_DATASET and not READONLY_MODELS:
    import json, os
    from kaggle_secrets import UserSecretsClient

    # Nouveau systeme Kaggle "API Tokens" (recommande, remplace les Legacy API
    # Credentials) : le secret est directement la chaine du token (KGAT_...),
    # pas un kaggle.json complet -- exposee en variable d'environnement
    # KAGGLE_API_TOKEN, reconnue nativement par la CLI kaggle >= 1.8.0.
    user_secrets = UserSecretsClient()
    os.environ["KAGGLE_API_TOKEN"] = user_secrets.get_secret("KAGGLE_API_TOKEN")

    DATASET_SLUG = "ollama-models-miro"  # adapte a ton pseudo Kaggle : <username>/ollama-models-miro
    metadata = {
        "title": "ollama-models-miro",
        "id": DATASET_SLUG,
        "licenses": [{"name": "CC0-1.0"}],
    }
    with open(os.path.join(OLLAMA_MODELS_DIR, "dataset-metadata.json"), "w") as f:
        json.dump(metadata, f)

    !pip install -q kaggle
    # Premiere creation : 'datasets create' ; mises a jour ulterieures : 'datasets version -m "update"'
    !kaggle datasets create -p {OLLAMA_MODELS_DIR} --dir-mode zip
    print("Dataset cree/mis a jour -- attache-le via '+ Add Input' dans les sessions suivantes.")
else:
    print("SAVE_TO_KAGGLE_DATASET=False (ou Mode B deja actif) -- rien a faire.")"""))

nb = new_notebook(cells=cells)
nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
nb.metadata["language_info"] = {"name": "python"}

path = "/home/user/odoo-ia-prototype/scripts/kaggle/local_llm_benchmark_kaggle.ipynb"
with open(path, "w") as f:
    nbformat.write(nb, f)

nbformat.validate(nb)
print("OK - notebook written and validated:", path)
print("cells:", len(nb.cells))
