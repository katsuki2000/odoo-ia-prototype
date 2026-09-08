"""
code_intelligence/ci_agent_node/business_context.py

Builds the "[BUSINESS TERM RESOLVER S2.0]" system-prompt addition once the
business_resolver has resolved a concept -- extracted from the former
ci_agent_node.py monolith (refactor, see todo/contexte.txt). Behavior
unchanged.
"""

from code_intelligence.ci_agent_node.module_inference import rank_custom_modules_for_models


def build_business_context_prompt(question: str, concept, G) -> str:
    if not concept.is_resolved:
        return ""

    resolved_info = []
    if concept.resolved_models:
        resolved_info.append(f"Target Models: {', '.join(concept.resolved_models)}")
        if G is not None and not concept.resolved_modules:
            candidate_mods = rank_custom_modules_for_models(G, concept.resolved_models, question)
            for mod_name in candidate_mods[:1]:
                mod_node = f"module:{mod_name}"
                mod_models = [
                    p.replace("model:", "") for p in G.predecessors(mod_node)
                    if p.startswith("model:") and "tester" not in p
                ]
                if len(mod_models) >= 1:
                    resolved_info.append(f"Module '{mod_name}' defines/extends models: {', '.join(sorted(mod_models))}")
    if concept.resolved_modules:
        resolved_info.append(f"Target Modules: {', '.join(concept.resolved_modules)}")
        if G is not None:
            for mod_name in concept.resolved_modules:
                mod_node = f"module:{mod_name}"
                if G.has_node(mod_node):
                    in_mods = [
                        u.replace("model:", "") for u in G.predecessors(mod_node)
                        if u.startswith("model:")
                    ]
                    if in_mods:
                        resolved_info.append(f"Module '{mod_name}' defines/extends models: {', '.join(sorted(in_mods))}")

    confidence_tag = (
        f" (LLM-arbitrated, confidence={concept.confidence})"
        if concept.source_step == "llm_arbitration"
        else ""
    )
    return (
        f"\n\n[BUSINESS TERM RESOLVER S2.0]\n"
        f"Query term matched: '{concept.user_term}'{confidence_tag}.\n"
        f"{' | '.join(resolved_info)}.\n"
        f"Use these exact technical identifiers when invoking composite tools."
    )
