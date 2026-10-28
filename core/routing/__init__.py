"""
core/routing/__init__.py

Regroupement : routing.py (choix de la source : documentation ou systeme).
"""

from .routing import (
    logger,
    route,
    route_decision,
)

__all__ = [
    "logger",
    "route",
    "route_decision",
]
