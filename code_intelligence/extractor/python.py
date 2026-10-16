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
    implied_group: Optional[str] = None
    selection: Optional[List[str]] = None
    selection_add: Optional[List[str]] = None


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
    written_states: List[str] = field(default_factory=list)
    called_self_methods: List[str] = field(default_factory=list)
    returned_states: List[str] = field(default_factory=list)
    write_argument_methods: List[str] = field(default_factory=list)


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

# ── AST Extractor ──────────────────────────────────────────────────────────

"""
code_intelligence/extractor/python_extractor.py

AST-based extractor for Python Odoo files.
Implements Task A1.1.2: Visiteur AST pour _name, _inherit, _inherits.
"""

import ast
from pathlib import Path
from typing import List, NamedTuple, Optional, Union



# Positional-argument order for relational field constructors, matching the
# Odoo field signatures: Many2one(comodel_name, string=...), One2many(comodel_name,
# inverse_name, string=...), Many2many(comodel_name, relation, column1, column2, ...).
POSITIONAL_ARG_ORDER = {
    "Many2one": ["comodel_name", "string"],
    "One2many": ["comodel_name", "inverse_name", "string"],
    "Many2many": ["comodel_name", "relation", "column1", "column2"],
}


ODOO_FIELD_TYPES = frozenset({
    "Many2one", "One2many", "Many2many", "Many2oneReference", "Reference",
    "Char", "Text", "Html", "Integer", "Float", "Monetary", "Boolean",
    "Selection", "Date", "Datetime", "Binary", "Image", "Json", "Properties", "PropertiesDefinition",
})
STATE_FIELD = "state"
SELECTION_KWARGS = frozenset({"selection", "selection_add"})
SELF_RECORDSET_METHODS = frozenset({
    "filtered", "filtered_domain", "sudo", "with_context", "with_user", "with_company", "with_env",
})


def selection_values(value) -> Optional[List[str]]:
    if not isinstance(value, list):
        return None
    values = [
        item[0] for item in value
        if isinstance(item, list) and item and isinstance(item[0], str)
    ]
    return values or None


def is_self_recordset(node: ast.AST, self_names: Set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in self_names
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr in SELF_RECORDSET_METHODS and is_self_recordset(node.func.value, self_names)
    return False


def state_in_write_dict(node: ast.AST) -> Optional[str]:
    if not isinstance(node, ast.Dict):
        return None
    for key, value in zip(node.keys, node.values):
        if isinstance(key, ast.Constant) and key.value == STATE_FIELD:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
    return None


class StateActivity(NamedTuple):
    written: List[str]
    called: List[str]
    returned: List[str]
    write_arguments: List[str]


def self_recordset_names(function_node: ast.AST) -> Set[str]:
    names: Set[str] = {"self"}
    for _ in range(2):
        for child in ast.walk(function_node):
            if isinstance(child, ast.For) and isinstance(child.target, ast.Name):
                if is_self_recordset(child.iter, names):
                    names.add(child.target.id)
            elif isinstance(child, ast.Assign) and is_self_recordset(child.value, names):
                names.update(target.id for target in child.targets if isinstance(target, ast.Name))
    return names


def scan_state_activity(function_node: ast.AST) -> StateActivity:
    """States a method writes or returns for its own recordset, and the methods it calls on it."""
    self_names = self_recordset_names(function_node)
    activity = StateActivity([], [], [], [])
    for child in ast.walk(function_node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            if not is_self_recordset(child.func.value, self_names):
                continue
            if child.func.attr == "write":
                for argument in child.args:
                    state = state_in_write_dict(argument)
                    if state and state not in activity.written:
                        activity.written.append(state)
                    if isinstance(argument, ast.Call) and isinstance(argument.func, ast.Attribute):
                        if is_self_recordset(argument.func.value, self_names) and argument.func.attr not in activity.write_arguments:
                            activity.write_arguments.append(argument.func.attr)
            elif child.func.attr not in SELF_RECORDSET_METHODS and child.func.attr not in activity.called:
                activity.called.append(child.func.attr)
        elif isinstance(child, ast.Assign):
            value = child.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                for target in child.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and target.attr == STATE_FIELD
                        and is_self_recordset(target.value, self_names)
                        and value.value not in activity.written
                    ):
                        activity.written.append(value.value)
        elif isinstance(child, ast.Return):
            state = state_in_write_dict(child.value) if child.value is not None else None
            if state and state not in activity.returned:
                activity.returned.append(state)
    return activity


class OdooClassVisitor(ast.NodeVisitor):
    """
    AST Visitor to extract Odoo model declarations (_name, _inherit, _inherits)
    from Python AST nodes.
    """

    def __init__(self, filepath: str = ""):
        self.filepath = filepath
        self.declarations: List[OdooModelDeclaration] = []
        self.constants: Dict[str, ast.AST] = {}

    def visit_Module(self, node: ast.Module):
        for statement in node.body:
            if (
                isinstance(statement, ast.Assign)
                and isinstance(statement.value, (ast.List, ast.Tuple))
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
            ):
                self.constants[statement.targets[0].id] = statement.value
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        # We check if class looks like an Odoo model class
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

        if field_type not in ODOO_FIELD_TYPES:
            return None

        kwargs = {}
        for kw in call_node.keywords:
            if kw.arg:
                kwargs[kw.arg] = self._extract_ast_value(kw.value, resolve_names=kw.arg in SELECTION_KWARGS)

        positional_args = []
        for arg in call_node.args:
            is_selection_argument = field_type == "Selection" and not positional_args
            positional_args.append(self._extract_ast_value(arg, resolve_names=is_selection_argument))

        # Handle positional arguments for relational fields: fill in whichever
        # kwargs are still missing (falsy, matching prior behaviour), in the
        # constructor's positional order.
        for i, key in enumerate(POSITIONAL_ARG_ORDER.get(field_type, [])):
            if not kwargs.get(key) and i < len(positional_args) and isinstance(positional_args[i], str):
                kwargs[key] = positional_args[i]

        comodel_name = kwargs.get("comodel_name")
        inverse_name = kwargs.get("inverse_name")
        relation_table = kwargs.get("relation")
        column1 = kwargs.get("column1")
        column2 = kwargs.get("column2")
        related = kwargs.get("related")
        compute = kwargs.get("compute")
        string_val = kwargs.get("string")
        implied_group = kwargs.get("implied_group")
        selection = selection_values(kwargs.get("selection"))
        if selection is None and field_type == "Selection" and positional_args:
            selection = selection_values(positional_args[0])
        selection_add = selection_values(kwargs.get("selection_add"))

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
            implied_group=implied_group,
            selection=selection,
            selection_add=selection_add,
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
        activity = scan_state_activity(node)
        method_decl.written_states = activity.written
        method_decl.called_self_methods = activity.called
        method_decl.returned_states = activity.returned
        method_decl.write_argument_methods = activity.write_arguments
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

    def _extract_ast_value(
        self, node: ast.AST, resolve_names: bool = False,
    ) -> Union[str, int, float, bool, list, dict, None]:
        """Extract literal values from AST nodes (strings, booleans, lists, dicts)."""
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, (ast.List, ast.Tuple)):
            res = []
            for elt in node.elts:
                val = self._extract_ast_value(elt, resolve_names)
                if val is not None:
                    res.append(val)
            return res
        elif isinstance(node, ast.Dict):
            res = {}
            for k_node, v_node in zip(node.keys, node.values):
                if k_node is not None:
                    k_val = self._extract_ast_value(k_node, resolve_names)
                    v_val = self._extract_ast_value(v_node, resolve_names)
                    if k_val is not None and v_val is not None:
                        res[k_val] = v_val
            return res
        elif resolve_names and isinstance(node, ast.Name) and node.id in self.constants:
            return self._extract_ast_value(self.constants[node.id])
        return None


def extract_odoo_models_from_file(
    filepath: Path,
    *,
    source: Optional[str] = None,
    tree: Optional[ast.Module] = None,
) -> List[OdooModelDeclaration]:
    """Extract Odoo model declarations from a file or an already parsed AST."""
    try:
        if tree is None:
            content = source if source is not None else filepath.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(filepath))
        visitor = OdooClassVisitor(filepath=str(filepath))
        visitor.visit(tree)
        return visitor.declarations
    except (OSError, UnicodeDecodeError, SyntaxError) as error:
        print(f"Error parsing {filepath}: {error}")
        return []


__all__ = [
    "ModelRelationType",
    "OdooFieldDeclaration",
    "OdooMethodDecoration",
    "OdooMethodDeclaration",
    "OdooModelDeclaration",
    "OdooClassVisitor",
    "extract_odoo_models_from_file",
]
