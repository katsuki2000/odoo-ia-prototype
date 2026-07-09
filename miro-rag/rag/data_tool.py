"""
rag/data_tool.py

Deterministic data query engine for structured ERP data.
Loads sales.json and tickets.json and executes exact Python
operations (sum, count, filter, list, max, min) — no LLM math.
"""

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from rag.schemas import DataQueryIntent

logger = logging.getLogger(__name__)

FAKE_DATA_DIR = Path(__file__).resolve().parent.parent / "fake_data"

# Supported data sources and their file paths
DATA_SOURCES = {
    "sales": FAKE_DATA_DIR / "sales.json",
    "tickets": FAKE_DATA_DIR / "tickets.json",
}


@lru_cache(maxsize=4)
def _load_json(file_path: str) -> list[dict[str, Any]]:
    """Load and cache a JSON file. Cached to avoid repeated disk reads."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info("Loaded %d records from %s", len(data), file_path)
        return data
    except FileNotFoundError:
        logger.error("Data file not found: %s", file_path)
        return []
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in %s: %s", file_path, e)
        return []


class DataQueryEngine:
    """Executes deterministic queries on structured ERP data."""

    def load_data(self, source: str) -> list[dict[str, Any]]:
        """Load data for a given source name."""
        file_path = DATA_SOURCES.get(source)
        if file_path is None:
            logger.error("Unknown data source: %s. Available: %s", source, list(DATA_SOURCES.keys()))
            return []
        return _load_json(str(file_path))

    def execute(self, intent: DataQueryIntent) -> str:
        """
        Execute a data query intent and return a formatted French string result.

        Args:
            intent: The structured intent describing the operation.

        Returns:
            A human-readable string with the result in French.
        """
        if intent.data_source not in DATA_SOURCES:
            raise ValueError(f"Unknown data source '{intent.data_source}', falling back to generate")
        data = self.load_data(intent.data_source)
        if not data:
            return f"Aucune donnée trouvée pour la source '{intent.data_source}'."

        # Apply filters
        filtered = self._apply_filters(data, intent.filters)
        logger.info(
            "DataQueryEngine: source=%s, op=%s, filters=%s → %d records after filter",
            intent.data_source, intent.operation, intent.filters, len(filtered)
        )

        operation = intent.operation.lower().strip()

        if operation == "count":
            return self._op_count(filtered, intent)
        elif operation == "sum":
            return self._op_sum(filtered, intent)
        elif operation == "filter" or operation == "list":
            return self._op_list(filtered, intent)
        elif operation == "max":
            return self._op_max(filtered, intent)
        elif operation == "min":
            return self._op_min(filtered, intent)
        else:
            logger.error("Unknown operation: %s", operation)
            return f"Opération '{operation}' non supportée."

    # ── Filter Logic ──────────────────────────────────────────────────────

    def _apply_filters(self, data: list[dict], filters: dict[str, str]) -> list[dict]:
        """Filter records by matching key-value pairs (case-insensitive)."""
        if not filters:
            return data

        result = []
        for record in data:
            match = True
            for key, value in filters.items():
                record_val = str(record.get(key, "")).lower().strip()
                filter_val = str(value).lower().strip()
                if record_val != filter_val:
                    match = False
                    break
            if match:
                result.append(record)
        return result

    # ── Operations ────────────────────────────────────────────────────────

    def _op_count(self, filtered: list[dict], intent: DataQueryIntent) -> str:
        """Count the number of records."""
        count = len(filtered)
        filter_desc = self._describe_filters(intent.filters)
        source_label = "ventes" if intent.data_source == "sales" else "tickets"
        return f"Il y a {count} {source_label}{filter_desc}."

    def _op_sum(self, filtered: list[dict], intent: DataQueryIntent) -> str:
        """Sum a numeric field across filtered records."""
        field = intent.target_field
        if not field:
            return "Erreur : aucun champ cible spécifié pour l'opération 'sum'."

        total = 0
        details = []
        for record in filtered:
            val = record.get(field, 0)
            try:
                numeric_val = float(val)
            except (ValueError, TypeError):
                logger.warning("Non-numeric value for field '%s': %s", field, val)
                numeric_val = 0.0
            total += numeric_val
            # Build detail line
            label = record.get("client", record.get("titre", f"#{record.get('id', '?')}"))
            product = record.get("produit", record.get("titre", ""))
            details.append(f"  - {label} ({product}) : {self._format_number(numeric_val)} Ar")

        filter_desc = self._describe_filters(intent.filters)
        result = f"Le montant total{filter_desc} est de {self._format_number(total)} Ar."
        if details:
            result += "\n\nDétail :\n" + "\n".join(details)
        return result

    def _op_list(self, filtered: list[dict], intent: DataQueryIntent) -> str:
        """List filtered records in a readable format."""
        if not filtered:
            filter_desc = self._describe_filters(intent.filters)
            return f"Aucun enregistrement trouvé{filter_desc}."

        source_label = "ventes" if intent.data_source == "sales" else "tickets"
        lines = [f"Voici les {source_label} trouvé(e)s ({len(filtered)} résultats) :"]

        for record in filtered:
            if intent.data_source == "sales":
                line = (
                    f"  - #{record.get('id', '?')} : {record.get('client', '?')} — "
                    f"{record.get('produit', '?')} — {self._format_number(record.get('montant', 0))} Ar "
                    f"({record.get('statut', '?')})"
                )
            elif intent.data_source == "tickets":
                line = (
                    f"  - #{record.get('id', '?')} : {record.get('titre', '?')} — "
                    f"Client: {record.get('client', '?')} — Statut: {record.get('statut', '?')}"
                )
            else:
                line = f"  - {record}"
            lines.append(line)

        return "\n".join(lines)

    def _op_max(self, filtered: list[dict], intent: DataQueryIntent) -> str:
        """Find the record with the maximum value for a field."""
        return self._op_extreme(filtered, intent, mode="max")

    def _op_min(self, filtered: list[dict], intent: DataQueryIntent) -> str:
        """Find the record with the minimum value for a field."""
        return self._op_extreme(filtered, intent, mode="min")

    def _op_extreme(self, filtered: list[dict], intent: DataQueryIntent, mode: str) -> str:
        """Find the min or max record for a given field."""
        field = intent.target_field
        if not field:
            return f"Erreur : aucun champ cible spécifié pour l'opération '{mode}'."
        if not filtered:
            return "Aucun enregistrement trouvé."

        best = None
        best_val = None
        for record in filtered:
            val = record.get(field, 0)
            try:
                numeric_val = float(val)
            except (ValueError, TypeError):
                continue

            if best_val is None:
                best_val = numeric_val
                best = record
            elif mode == "max" and numeric_val > best_val:
                best_val = numeric_val
                best = record
            elif mode == "min" and numeric_val < best_val:
                best_val = numeric_val
                best = record

        if best is None:
            return f"Impossible de calculer le {mode} pour le champ '{field}'."

        label = best.get("client", best.get("titre", f"#{best.get('id', '?')}"))
        word = "maximum" if mode == "max" else "minimum"
        return f"La valeur {word} pour '{field}' est {self._format_number(best_val)} Ar ({label})."

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _format_number(value: float) -> str:
        """Format a number with space separators (French convention)."""
        if value == int(value):
            return f"{int(value):,}".replace(",", " ")
        else:
            return f"{value:,.2f}".replace(",", " ")

    @staticmethod
    def _describe_filters(filters: dict[str, str]) -> str:
        """Build a human-readable filter description."""
        if not filters:
            return ""
        parts = [f"{k} = '{v}'" for k, v in filters.items()]
        return " (filtres : " + ", ".join(parts) + ")"
