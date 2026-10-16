"""Distinct display labels of a graph node."""

from typing import Dict, List


def node_labels(data: Dict) -> List[str]:
    labels = [str(data.get('description') or data.get('label') or data.get('name') or '').strip()]
    labels.extend(str(item.get('label') or '').strip() for item in data.get('business_labels', []))
    return list(dict.fromkeys(label for label in labels if label))
