"""
code_intelligence/python_extractor.py

AST-based extractor for Python Odoo files.
Implements Task A1.1.2: Visiteur AST pour _name, _inherit, _inherits.
"""

import ast
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Union, Set


class ModelRelationType(Enum):
    BASE = "BASE"            # _name defined, no _inherit
    EXTENSION = "EXTENSION"   # _inherit without _name (modifies existing model)
    CLASSIC_INHERITANCE = "CLASSIC_INHERITANCE" # _name + _inherit (creates new model inheriting from existing)
    DELEGATION = "DELEGATION" # _inherits dict (delegation via foreign key, e.g. product.product -> product.template)


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


class OdooClassVisitor(ast.NodeVisitor):
    """
    AST Visitor to extract Odoo model declarations (_name, _inherit, _inherits)
    from Python AST nodes.
    """

    def __init__(self, filepath: str = ""):
        self.filepath = filepath
        self.declarations: List[OdooModelDeclaration] = []

    def visit_ClassDef(self, node: ast.ClassDef):
        # We check if class looks like an Odoo model class (inherits from models.Model/TransientModel/AbstractModel or has _name/_inherit)
        model_decl = self._extract_odoo_model_declaration(node)
        if model_decl and (model_decl.name or model_decl.inherit or model_decl.inherits):
            self.declarations.append(model_decl)
        
        # Continue visiting nested structures if any
        self.generic_visit(node)

    def _extract_odoo_model_declaration(self, node: ast.ClassDef) -> Optional[OdooModelDeclaration]:
        decl = OdooModelDeclaration(
            class_name=node.name,
            filepath=self.filepath,
            lineno=node.lineno,
        )

        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        attr_name = target.id
                        val = self._extract_ast_value(stmt.value)
                        
                        if attr_name == "_name" and isinstance(val, str):
                            decl.name = val
                        elif attr_name == "_inherit":
                            if isinstance(val, str):
                                decl.inherit = [val]
                            elif isinstance(val, list):
                                decl.inherit = [v for v in val if isinstance(v, str)]
                        elif attr_name == "_inherits" and isinstance(val, dict):
                            # val is dict mapping parent_model -> field_name
                            clean_inherits = {}
                            for k, v in val.items():
                                if isinstance(k, str) and isinstance(v, str):
                                    clean_inherits[k] = v
                            decl.inherits = clean_inherits
                        elif attr_name == "_description" and isinstance(val, str):
                            decl.description = val
                        elif isinstance(stmt.value, ast.Call):
                            field_decl = self._extract_field_declaration(attr_name, stmt.value)
                            if field_decl:
                                decl.fields.append(field_decl)
            elif isinstance(stmt, ast.FunctionDef):
                method_decl = self._extract_method_declaration(stmt)
                if method_decl:
                    decl.methods.append(method_decl)
                            
        return decl

    def _extract_field_declaration(self, field_name: str, call_node: ast.Call) -> Optional[OdooFieldDeclaration]:
        field_type = None
        if isinstance(call_node.func, ast.Attribute):
            field_type = call_node.func.attr
        elif isinstance(call_node.func, ast.Name):
            field_type = call_node.func.id

        known_fields = {
            "Many2one", "One2many", "Many2many",
            "Char", "Text", "Integer", "Float", "Boolean",
            "Selection", "Monetary", "Datetime", "Date", "Binary", "Html", "Image"
        }
        if not field_type or field_type not in known_fields:
            return None

        kwargs = {}
        for kw in call_node.keywords:
            if kw.arg:
                kwargs[kw.arg] = self._extract_ast_value(kw.value)

        positional_args = []
        for arg in call_node.args:
            positional_args.append(self._extract_ast_value(arg))

        comodel_name = kwargs.get("comodel_name")
        inverse_name = kwargs.get("inverse_name")
        relation_table = kwargs.get("relation")
        column1 = kwargs.get("column1")
        column2 = kwargs.get("column2")
        related = kwargs.get("related")
        compute = kwargs.get("compute")
        string_val = kwargs.get("string")

        # Handle positional arguments for relational fields
        if field_type == "Many2one":
            if not comodel_name and len(positional_args) > 0 and isinstance(positional_args[0], str):
                comodel_name = positional_args[0]
            if not string_val and len(positional_args) > 1 and isinstance(positional_args[1], str):
                string_val = positional_args[1]
        elif field_type == "One2many":
            if not comodel_name and len(positional_args) > 0 and isinstance(positional_args[0], str):
                comodel_name = positional_args[0]
            if not inverse_name and len(positional_args) > 1 and isinstance(positional_args[1], str):
                inverse_name = positional_args[1]
            if not string_val and len(positional_args) > 2 and isinstance(positional_args[2], str):
                string_val = positional_args[2]
        elif field_type == "Many2many":
            if not comodel_name and len(positional_args) > 0 and isinstance(positional_args[0], str):
                comodel_name = positional_args[0]
            if not relation_table and len(positional_args) > 1 and isinstance(positional_args[1], str):
                relation_table = positional_args[1]
            if not column1 and len(positional_args) > 2 and isinstance(positional_args[2], str):
                column1 = positional_args[2]
            if not column2 and len(positional_args) > 3 and isinstance(positional_args[3], str):
                column2 = positional_args[3]

        # Calculate store attribute
        explicit_store = kwargs.get("store")
        if explicit_store is not None and isinstance(explicit_store, bool):
            store_val = explicit_store
        elif compute is not None:
            store_val = False
        else:
            store_val = True

        return OdooFieldDeclaration(
            name=field_name,
            field_type=field_type,
            comodel_name=comodel_name,
            inverse_name=inverse_name,
            relation_table=relation_table,
            column1=column1,
            column2=column2,
            related=related,
            compute=compute,
            store=store_val,
            string=string_val,
        )

    def _extract_method_declaration(self, node: ast.FunctionDef) -> OdooMethodDeclaration:
        method_decl = OdooMethodDeclaration(
            name=node.name,
            lineno=node.lineno,
            end_lineno=getattr(node, "end_lineno", None),
        )
        is_api_model = False
        is_instance = True

        for dec in node.decorator_list:
            dec_type, trigger_fields = self._parse_decorator(dec)
            if dec_type:
                method_decl.decorators.append(
                    OdooMethodDecoration(
                        decorator_type=dec_type,
                        trigger_fields=trigger_fields
                    )
                )

            dec_name = self._get_decorator_name(dec)
            if dec_name in {"model", "model_create_multi", "classmethod", "staticmethod"}:
                is_api_model = True
                is_instance = False

        method_decl.api_model = is_api_model
        method_decl.is_instance_method = is_instance
        return method_decl

    def _get_decorator_name(self, dec: ast.AST) -> Optional[str]:
        """Extract name of decorator node."""
        if isinstance(dec, ast.Name):
            return dec.id
        elif isinstance(dec, ast.Attribute):
            return dec.attr
        elif isinstance(dec, ast.Call):
            return self._get_decorator_name(dec.func)
        else:
            return None

    def _parse_decorator(self, dec: ast.AST) -> tuple[Optional[str], list[str]]:
        """Parse decorator node and return (decorator_name, list_of_trigger_fields)."""
        if not isinstance(dec, ast.Call):
            return None, []

        func_name = None
        if isinstance(dec.func, ast.Attribute):
            func_name = dec.func.attr
        elif isinstance(dec.func, ast.Name):
            func_name = dec.func.id

        if func_name not in {"depends", "constrains", "onchange"}:
            return None, []

        trigger_fields = []
        for arg in dec.args:
            extracted = self._extract_ast_value(arg)
            if isinstance(extracted, str):
                trigger_fields.append(extracted)
            elif isinstance(extracted, list):
                for item in extracted:
                    if isinstance(item, str):
                        trigger_fields.append(item)

        return func_name, trigger_fields

    def _extract_ast_value(self, node: ast.AST) -> Union[str, int, float, bool, list, dict, None]:
        """Extract literal values from AST nodes (strings, booleans, lists, dicts)."""
        if isinstance(node, ast.Constant):
            return node.value
        elif hasattr(ast, 'Str') and isinstance(node, ast.Str):
            return node.s
        elif hasattr(ast, 'NameConstant') and isinstance(node, ast.NameConstant):
            return node.value
        elif isinstance(node, (ast.List, ast.Tuple)):
            res = []
            for elt in node.elts:
                val = self._extract_ast_value(elt)
                if val is not None:
                    res.append(val)
            return res
        elif isinstance(node, ast.Dict):
            res = {}
            for k_node, v_node in zip(node.keys, node.values):
                if k_node is not None:
                    k_val = self._extract_ast_value(k_node)
                    v_val = self._extract_ast_value(v_node)
                    if k_val is not None and v_val is not None:
                        res[k_val] = v_val
            return res
        return None


def extract_odoo_models_from_file(filepath: Path) -> List[OdooModelDeclaration]:
    """Parse a python file and extract all Odoo model declarations."""
    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(filepath))
        visitor = OdooClassVisitor(filepath=str(filepath))
        visitor.visit(tree)
        return visitor.declarations
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")
        return []
