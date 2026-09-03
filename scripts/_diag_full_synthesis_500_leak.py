#!/usr/bin/env python3
"""
todo/contexte.txt section 498 -- Bug 3, third candidate source.

Rejoue la synthese COMPLETE (question exacte de San Goku, via
code_intelligence_agent() en entier -- pas un hop isole) pour tester
l'hypothese de la section 498 : la LLM de synthese finale genere elle-meme
un paragraphe "[FAIT DETERMINISTIQUE]" en imitant le format decrit dans son
propre prompt, sans que le backfill Python (deja exclu comme source,
sections 495-497) n'y soit pour rien.

Meme pattern que scripts/replay_q1_2_vip.py (deja existant) mais avec le
libelle EXACT de la question originale (les deux volets : qui peut
approuver + y a-t-il un piege), et plusieurs tirages en une seule execution
pour observer la variance.

Un run complet = plusieurs appels LLM reels (meme cout qu'une question
normale posee au widget). Par defaut 3 tirages -- ajuster via argv[1] si
besoin.
"""

import re
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph import code_intelligence_agent

QUESTION = "Qui a le droit d'approuver un avoir pour un client VIP, et y a-t-il un piège dans le code ?"

_AMOUNT_NEAR_FAIT_RE = re.compile(
    r"\[FAIT D[ÉE]TERMINISTIQUE\][^\n]*", re.IGNORECASE
)
_ANY_AMOUNT_RE = re.compile(r"(\d[\d\s]*\d)\s*€")


def run_once(n: int) -> None:
    print("=" * 80)
    print(f" TIRAGE {n} -- DIAG synthese complete")
    print(f" Question: {QUESTION}")
    print("=" * 80)

    state = {"question": QUESTION, "chat_history": [], "user_groups": []}
    res = code_intelligence_agent(state)

    answer_obj = res.get("response")
    verbatim_answer = answer_obj.answer if answer_obj else res.get("raw_answer", "Aucune reponse")

    print("\n--- REPONSE FINALE COMPLETE ---\n")
    print(verbatim_answer)
    print("\n--- FIN REPONSE ---\n")

    fait_lines = _AMOUNT_NEAR_FAIT_RE.findall(verbatim_answer)
    print(f"Paragraphes '[FAIT DETERMINISTIQUE]' trouves : {len(fait_lines)}")
    for line in fait_lines:
        print(f"  - {line.strip()}")

    amounts = _ANY_AMOUNT_RE.findall(verbatim_answer)
    print(f"\nMontants (€) mentionnes dans la reponse finale : {amounts}")
    if "500" in amounts and "5000" not in "".join(amounts):
        print("  [ALERTE] '500' present sans correspondre a un 5000/20000 tronque -- a examiner.")

    print("\n" + "=" * 80 + "\n")


def main():
    n_runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    for i in range(1, n_runs + 1):
        run_once(i)


if __name__ == "__main__":
    main()
