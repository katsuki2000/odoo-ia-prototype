"""
code_intelligence/extractor/python_models.py

Data models and enums representing Odoo Python declarations extracted via AST.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Set


class ModelRelationType(Enum):
    BASE = "BASE"            # _name defined, no _inherit
    EXTENSION = "EXTENSION"   # _inherit without _name (modifies existing model)
    CLASSIC_INHERITANCE = "CLASSIC_INHERITANCE"  # _name + _inherit (creates new model inheriting)
    DELEGATION = "DELEGATION" # _inherits dict (delegation via foreign key)


@dataclass
class OdooFieldDeclaration:
    name: str
    field_type: str
    comodel_name: Optional[str] = None
    inverse_name: Optional[str] = None
    relation_table: Optional[str] = None
    column1: Optional[str] = None
    column2: Optional[str] = None
    related: Optional[str] = None
    compute: Optional[str] = None
    store: bool = True
    string: Optional[str] = None


@dataclass
class OdooMethodDecoration:
    decorator_type: str
    trigger_fields: List[str] = field(default_factory=list)


@dataclass
class OdooMethodDeclaration:
    name: str
    lineno: int
    decorators: List[OdooMethodDecoration] = field(default_factory=list)
    api_model: bool = False
    is_instance_method: bool = True
    # End line number of the method source AST node if available
    end_lineno: Optional[int] = None


@dataclass
class OdooModelDeclaration:
    class_name: str
    filepath: str
    lineno: int
    name: Optional[str] = None
    inherit: List[str] = field(default_factory=list)
    inherits: Dict[str, str] = field(default_factory=dict)
    description: Optional[str] = None
    methods: List[OdooMethodDeclaration] = field(default_factory=list)
    fields: List[OdooFieldDeclaration] = field(default_factory=list)

    @property
    def relation_types(self) -> Set[ModelRelationType]:
        types = set()
        if self.name and not self.inherit:
            types.add(ModelRelationType.BASE)
        elif not self.name and self.inherit:
            types.add(ModelRelationType.EXTENSION)
        elif self.name and self.inherit:
            types.add(ModelRelationType.CLASSIC_INHERITANCE)

        if self.inherits:
            types.add(ModelRelationType.DELEGATION)

        return types
