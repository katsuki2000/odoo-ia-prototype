"""Static alias targets validated against the loaded instance graph."""

from typing import List, Sequence


def alias_targets_in_graph(G, targets: Sequence[str]) -> List[str]:
    """Keep the alias targets that exist in G; without a loaded graph, keep them all.

    When a custom.* target and a native one are both present, only the custom one
    is kept (todo/contexte.txt section 730).
    """
    if G is None or G.number_of_nodes() == 0:
        return list(targets)
    existing = [
        target for target in targets
        if G.has_node(f"model:{target}") or G.has_node(f"module:{target}")
    ]
    is_alternatives = (
        len(targets) == 2
        and any(target.startswith("custom.") for target in targets)
        and not all(target.startswith("custom.") for target in targets)
    )
    if is_alternatives and existing:
        custom = [target for target in existing if target.startswith("custom.")]
        return [custom[0] if custom else existing[0]]
    return existing
