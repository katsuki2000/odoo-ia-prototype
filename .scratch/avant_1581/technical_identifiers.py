"""Keep technical model names out of the user-facing answer."""

import re

import networkx as nx

from code_intelligence.agent.node_labels import node_labels

TECHNICAL_IDENTIFIER = re.compile(
    r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b|\b[a-z]{2,}[a-z0-9]*(?:\.[a-z]{2,}[a-z0-9_]*)+\b"
)
_QUOTED_IDENTIFIER = re.compile(rf"`?({TECHNICAL_IDENTIFIER.pattern})`?")


def replace_model_identifiers(answer: str, G: nx.DiGraph) -> str:
    """Replace each model name found in the graph by its business label; anything else is left as is."""
    def business_label(match):
        node = G.nodes.get('model:' + match.group(1))
        return node_labels(node)[0] if node else match.group(0)

    return _QUOTED_IDENTIFIER.sub(business_label, answer)
