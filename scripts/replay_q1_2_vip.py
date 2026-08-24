#!/usr/bin/env python3
"""
scripts/replay_q1_2_vip.py

Rejeu isole de Q1.2 ("Qui a le droit d'approuver un avoir pour un client VIP ?"),
le cas reel qui a revele le bug override_sites (Bloc 9, trace fb42dd5a1de2 --
account.move._reverse_moves rapporte comme "2 modules" de facon suspecte /
tronquee). Le fix (accumulation de tous les sites de surcharge au lieu d'un
overwrite silencieux) est deja present dans graph_builder.py::
_add_model_field_method_nodes -- ce script sert a verifier qu'il tient sur
le cas reel, sans repayer tout le benchmark de 9 questions (couteux en TPM
Groq) juste pour ce point.

Usage:
    cd /home/user/odoo-ia-prototype
    python scripts/replay_q1_2_vip.py
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph import code_intelligence_agent

QUESTION = "Qui a le droit d'approuver un avoir pour un client VIP ?"


def main():
    print("=" * 80)
    print(" REJEU ISOLE -- Q1.2 (cascade avoirs VIP)")
    print(f" Question: {QUESTION}")
    print("=" * 80)

    state = {"question": QUESTION, "chat_history": [], "user_groups": []}
    res = code_intelligence_agent(state)

    answer_obj = res.get("response")
    if answer_obj:
        verbatim_answer = answer_obj.answer
    else:
        verbatim_answer = res.get("raw_answer", "Aucune reponse")

    timing_info = res.get("timing", {})
    print(f"\nHops: {timing_info.get('ci_hop_count', '?')} | "
          f"Effectif: {timing_info.get('ci_effective_time', '?')}s | "
          f"Groq wait: {timing_info.get('ci_groq_wait_time', '?')}s\n")
    print(verbatim_answer)
    print("\n" + "=" * 80)

    # Verification cible : la chaine de surcharge de _reverse_moves (et/ou
    # action_valider_avoir) doit lister TOUS les modules reels qui la
    # surchargent, pas un decompte tronque/errone. Verification manuelle
    # attendue par l'utilisateur -- ce script n'automatise pas l'assertion
    # (le nombre exact de modules attendus depend du fixture corpus et n'est
    # pas fige ici), il affiche juste la sortie verbatim pour relecture.
    if "_reverse_moves" in verbatim_answer or "action_valider_avoir" in verbatim_answer:
        print("[OK] La reponse mentionne bien la chaine de surcharge -- relire "
              "le detail des modules listes ci-dessus pour confirmer le fix.")
    else:
        print("[INFO] La reponse ne mentionne pas explicitement la chaine de "
              "surcharge cette fois -- peut varier selon le chemin ReAct pris "
              "par le LLM (non-deterministe). Relancer si besoin.")


if __name__ == "__main__":
    main()
