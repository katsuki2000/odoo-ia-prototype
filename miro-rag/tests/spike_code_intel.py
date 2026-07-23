"""
tests/spike_code_intel_v2.py
Spike v2 : au lieu d'exposer des outils fins et de laisser le LLM
orchestrer la traversée du graphe lui-même, la traversée est faite
en code Python déterministe. Le LLM ne choisit que QUEL outil
composite appeler, pas COMMENT naviguer le graphe.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_groq import ChatGroq
from config.settings import GROQ_MODEL, GROQ_API_KEY

# ── Graphe factice (identique aux runs précédents) ──────────────
FAKE_GRAPH = {
    "account.move": {"inherits_from": [], "extended_by": ["l10n_mg_account"], "rules": ["rule_account_move_1"]},
    "rule_account_move_1": {"groups": ["account.group_account_manager"], "perm": "read,write"},
    "account.group_account_manager": {"implies": ["account.group_account_user"]},
}
ROLE_MAPPING = {"account.group_account_manager": "Directeur comptable",
                "account.group_account_user": "Comptable"}


# ── Traversée déterministe (le "cerveau" du graphe, pas le LLM) ─
def _traverser_qui_a_acces(modele: str) -> dict:
    """Fait tout le trajet modèle → règles → groupes → hiérarchie → rôles en code pur."""
    info = FAKE_GRAPH.get(modele)
    if not info:
        return {"trouve": False, "raison": f"Modèle '{modele}' introuvable dans le corpus indexé."}

    rules = info.get("rules", [])
    if not rules:
        return {"trouve": False, "raison": f"Aucune ir.rule définie pour '{modele}'."}

    tous_les_groupes = set()
    for rule_id in rules:
        rule_info = FAKE_GRAPH.get(rule_id, {})
        tous_les_groupes.update(rule_info.get("groups", []))

    if not tous_les_groupes:
        return {"trouve": False, "raison": f"Règles trouvées pour '{modele}' mais aucun groupe associé."}

    # Étendre avec la hiérarchie transitive (implies)
    groupes_complets = set(tous_les_groupes)
    a_traiter = list(tous_les_groupes)
    while a_traiter:
        g = a_traiter.pop()
        implies = FAKE_GRAPH.get(g, {}).get("implies", [])
        for sub in implies:
            if sub not in groupes_complets:
                groupes_complets.add(sub)
                a_traiter.append(sub)

    roles = {g: ROLE_MAPPING.get(g, f"(rôle métier inconnu pour {g})") for g in groupes_complets}

    return {
        "trouve": True,
        "modele": modele,
        "regles": rules,
        "groupes_directs": sorted(tous_les_groupes),
        "groupes_avec_hierarchie": sorted(groupes_complets),
        "roles": roles,
    }


def _traverser_modules_et_regles(modele: str) -> dict:
    """Modules qui étendent le modèle + règles de sécurité, en un seul appel."""
    info = FAKE_GRAPH.get(modele)
    if not info:
        return {"trouve": False, "raison": f"Modèle '{modele}' introuvable."}
    return {
        "trouve": True,
        "modele": modele,
        "modules_extension": info.get("extended_by", []),
        "regles": info.get("rules", []),
    }


# ── Outils composites exposés au LLM (haut niveau seulement) ────
@tool
def qui_a_acces_a(modele_odoo: str) -> str:
    """Retourne, en une seule fois, les groupes (avec hiérarchie) et les rôles métier
    ayant accès à un modèle Odoo donné, en traversant règles → groupes → rôles."""
    r = _traverser_qui_a_acces(modele_odoo)
    if not r["trouve"]:
        return r["raison"]
    return (
        f"Règles: {r['regles']}\n"
        f"Groupes directs: {r['groupes_directs']}\n"
        f"Groupes avec hiérarchie: {r['groupes_avec_hierarchie']}\n"
        f"Rôles métier: {r['roles']}"
    )

@tool
def modules_et_regles_dun_modele(modele_odoo: str) -> str:
    """Retourne les modules qui étendent un modèle et ses règles de sécurité, en un seul appel."""
    r = _traverser_modules_et_regles(modele_odoo)
    if not r["trouve"]:
        return r["raison"]
    return f"Modules qui étendent {r['modele']}: {r['modules_extension']}\nRègles: {r['regles']}"


ALL_TOOLS = [qui_a_acces_a, modules_et_regles_dun_modele]
TOOL_MAP = {t.name: t for t in ALL_TOOLS}

# ── Mêmes questions que les runs précédents, chemin attendu = 1 seul outil ──
TEST_CASES = [
    {
        "question": "Qui a le droit de modifier les écritures comptables (account.move), en rôle métier ?",
        "expected_sequence": ["qui_a_acces_a"],
    },
    {
        "question": "Quels modules étendent account.move et quelles sont ses règles de sécurité ?",
        "expected_sequence": ["modules_et_regles_dun_modele"],
    },
    {
        "question": "Quel groupe hiérarchiquement supérieur donne accès à account.move, et quel est son rôle métier ?",
        "expected_sequence": ["qui_a_acces_a"],
    },
]

SYSTEM_PROMPT = (
    "Tu es un agent de navigation dans le code Odoo. "
    "Utilise l'outil composite disponible qui correspond le mieux à la question. "
    "Ne réponds jamais en devinant des informations que les outils ne t'ont pas données."
)


def run_case(question: str, expected_sequence: list[str], max_iterations: int = 4):
    llm = ChatGroq(model=GROQ_MODEL, api_key=GROQ_API_KEY, temperature=0.0)
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=question)]
    actual_sequence, actual_calls = [], []
    seen_calls = set()
    loop_detected = False
    format_errors = 0
    final_answer = None
    i = 0

    for i in range(max_iterations):
        try:
            ai_msg = llm_with_tools.invoke(messages)
        except Exception as e:
            format_errors += 1
            print(f"    [itération {i+1}] ERREUR format: {e}")
            break

        messages.append(ai_msg)

        if not getattr(ai_msg, "tool_calls", None):
            final_answer = ai_msg.content
            break

        for tc in ai_msg.tool_calls:
            name, args, tid = tc["name"], tc["args"], tc["id"]
            sig = (name, tuple(sorted(args.items())))
            actual_sequence.append(name)
            actual_calls.append((name, args))

            if sig in seen_calls:
                loop_detected = True
                obs = "BOUCLE DÉTECTÉE : réponds avec l'information déjà obtenue, n'insiste pas."
            else:
                seen_calls.add(sig)
                if name not in TOOL_MAP:
                    obs = f"Outil '{name}' inconnu."
                else:
                    try:
                        obs = TOOL_MAP[name].invoke(args)
                    except Exception as e:
                        obs = f"Erreur: {e}"
            messages.append(ToolMessage(content=str(obs), tool_call_id=tid))

    return {
        "question": question, "expected": expected_sequence, "actual": actual_sequence,
        "actual_calls": actual_calls, "iterations_used": i + 1, "format_errors": format_errors,
        "loop_detected": loop_detected, "final_answer": final_answer,
        "sequence_match": actual_sequence == expected_sequence,
    }


if __name__ == "__main__":
    results = []
    for case in TEST_CASES:
        print(f"\n▶ {case['question']}")
        r = run_case(case["question"], case["expected_sequence"])
        results.append(r)
        print(f"  Attendu : {r['expected']}")
        print(f"  Obtenu  : {r['actual']}")
        print("  Détail des appels (outil ← arguments) :")
        for name, args in r["actual_calls"]:
            print(f"    - {name} ← {args}")
        print(f"  Match exact : {r['sequence_match']} | Itérations : {r['iterations_used']} "
              f"| Erreurs format : {r['format_errors']} | Boucle détectée : {r['loop_detected']}")
        print(f"  Réponse finale : {r['final_answer']}")

    ok = sum(1 for r in results if r["sequence_match"])
    print(f"\n{'='*50}\nRésultat spike v2 : {ok}/{len(results)} séquences correctes\n{'='*50}")