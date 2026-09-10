#!/usr/bin/env python3
"""Verification live de la rotation multi-cles Groq (todo/contexte.txt, section 265).

Contexte : `core/llm_client.py` (sections 263-264) tourne automatiquement sur la
cle Groq suivante de `GROQ_API_KEYS` des qu'un 429 (rate limit) est recu, via
`invoke_with_rate_limit(..., rebuild_llm=...)`. Ce mecanisme est deja confirme
par lecture de code et par la suite pytest complete (section 265, 918 passed,
0 failed) -- mais aucune de ces verifications n'a provoque de VRAI 429 reseau.

Ce script fait exactement ca : il appelle `invoke_with_rate_limit()` -- le
meme chemin de code que la production, pas un chemin de test parallele -- avec
des messages volontairement volumineux, en boucle rapprochee, jusqu'a
declencher un 429 reel aupres de Groq (le flake documente en sections
254/255/262 montrait un budget TPM de 8000 sur ce compte -- quelques appels
consecutifs suffisent a le depasser). Il n'invente rien : c'est le meme
`get_chat_llm()`/`invoke_with_rate_limit()` que `ci_agent_node.py` et,
depuis la section 264, `business_resolver.py`/`generate_node.py`/
`orm_agent_node.py`.

Ce que le script NE fait PAS :
- Il ne modifie aucun fichier de production.
- Il ne peut PAS etre execute par Claude dans cette session (acces
  filesystem uniquement, pas de reseau sortant vers Groq) -- a executer par
  l'utilisateur sur son poste, depuis la racine du depot :
      python scripts/verify_groq_key_rotation_live.py
  ou, pour forcer davantage d'appels si le budget TPM du compte a change :
      python scripts/verify_groq_key_rotation_live.py --rounds 12 --chars 9000

Lecture du resultat :
- Si `GROQ_API_KEYS` ne contient qu'une seule cle : le script previent
  explicitement (pas de rotation possible, le WARNING de rotation ne peut
  pas apparaitre -- seule l'attente dynamique existante serait observee).
- Si un WARNING "Groq API key N/M exhausted -- rotating to key N+1/M"
  apparait dans les logs : la rotation reelle est CONFIRMEE en conditions
  reseau reelles, pas seulement par lecture de code.
- Le script imprime aussi un resume final : nombre d'appels reussis, nombre
  de 429 rencontres, index de cle final vs. index de depart (via l'etat
  partage `core.llm.llm_client._groq_key_index`, lu en diagnostic uniquement).
"""

import argparse
import logging
import sys
import time
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from langchain_core.messages import HumanMessage

from config.settings import GROQ_API_KEYS
import core.llm.llm_client as llm_client
from core.llm.llm_client import get_chat_llm, invoke_with_rate_limit


def _build_bulky_message(n_chars: int) -> list:
    """Message volontairement gros pour consommer du budget TPM rapidement.
    Contenu neutre et repetitif -- seul le volume de tokens compte ici, pas
    le sens du texte (le LLM n'a pas besoin de produire une reponse utile
    pour ce test)."""
    filler = (
        "Ceci est un texte de remplissage utilise uniquement pour consommer "
        "du budget TPM Groq dans le cadre d'une verification live de la "
        "rotation multi-cles. "
    )
    repeated = (filler * ((n_chars // len(filler)) + 1))[:n_chars]
    return [HumanMessage(content=repeated + "\n\nReponds simplement par: OK.")]


def _rebuild():
    return get_chat_llm(temperature=0.0, max_retries=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=8, help="Nombre d'appels a tenter (defaut: 8)")
    parser.add_argument("--chars", type=int, default=7000, help="Taille approx. (caracteres) du message par appel (defaut: 7000)")
    parser.add_argument("--pause", type=float, default=0.0, help="Pause additionnelle (s) entre appels, au-dela du throttle interne de 5s (defaut: 0)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger("verify_groq_key_rotation_live")

    n_keys = len(GROQ_API_KEYS)
    logger.info("GROQ_API_KEYS : %d cle(s) configuree(s).", n_keys)
    if n_keys <= 1:
        logger.warning(
            "Une seule cle configuree -- la rotation ne peut PAS etre observee "
            "ce tour (aucun WARNING 'rotating to key N+1/M' possible). Ajouter "
            "au moins une 2e cle a GROQ_API_KEYS dans .env pour ce test."
        )

    start_index = llm_client._groq_key_index[0]
    n_ok = 0
    n_rate_limited_seen = 0

    messages = _build_bulky_message(args.chars)
    llm = get_chat_llm(temperature=0.0, max_retries=0)

    for i in range(args.rounds):
        logger.info("--- Appel %d/%d (cle courante index=%d) ---", i + 1, args.rounds, llm_client._groq_key_index[0])
        try:
            result, waited = invoke_with_rate_limit(llm, messages, max_retries=5, rebuild_llm=_rebuild)
            n_ok += 1
            logger.info("Appel %d/%d OK (attente cumulee interne: %.1fs).", i + 1, args.rounds, waited)
        except Exception as e:
            n_rate_limited_seen += 1
            logger.error("Appel %d/%d a echoue apres tous les retries: %s", i + 1, args.rounds, e)
        # invoke_with_rate_limit() reconstruit deja `llm` en interne via
        # rebuild_llm en cas de rotation -- on relit l'objet le plus recent
        # pour le prochain tour en reconstruisant nous-memes sur la cle
        # courante (coherent avec le pattern *_llm_box des fichiers de prod).
        llm = get_chat_llm(temperature=0.0, max_retries=0)
        if args.pause:
            time.sleep(args.pause)

    end_index = llm_client._groq_key_index[0]

    print("\n" + "=" * 70)
    print("RESUME")
    print("=" * 70)
    print(f"Cles configurees        : {n_keys}")
    print(f"Index de cle au depart  : {start_index}")
    print(f"Index de cle a la fin   : {end_index}")
    print(f"Appels reussis          : {n_ok}/{args.rounds}")
    print(f"Appels finalement echoues (tous retries epuises) : {n_rate_limited_seen}/{args.rounds}")
    if end_index > start_index:
        print(
            f"\n>>> ROTATION REELLE CONFIRMEE : la cle a avance de l'index "
            f"{start_index} a {end_index} suite a au moins un 429 reel. "
            f"Chercher la ligne de log 'Groq API key N/M exhausted -- "
            f"rotating to key N+1/M' ci-dessus pour la preuve textuelle."
        )
    elif n_rate_limited_seen == 0 and n_ok == args.rounds:
        print(
            "\n>>> Aucun 429 rencontre ce tour -- le budget TPM du compte n'a "
            "pas ete depasse avec ces parametres. Relancer avec --rounds plus "
            "eleve et/ou --chars plus eleve pour forcer le depassement."
        )
    else:
        print(
            "\n>>> Aucune rotation observee malgre un/des echec(s) -- verifier "
            "que GROQ_API_KEYS contient bien plus d'une cle dans .env."
        )
    print("=" * 70)


if __name__ == "__main__":
    main()
