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
    written_values: Dict[str, List[str]] = field(default_factory=dict)
    called_self_methods: List[str] = field(default_factory=list)
    returned_values: Dict[str, List[str]] = field(default_factory=dict)
    write_argument_methods: List[str] = field(default_factory=list)
    # field -> state -> context flags guarding each write occurrence ([] = unguarded)
    written_guards: Dict[str, Dict[str, List[List[str]]]] = field(default_factory=dict)
    # callee -> context flags set by with_context() on the call receiver ('*' = unknown)
    call_context_flags: Dict[str, List[str]] = field(default_factory=dict)


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


def constants_in_write_dict(node: ast.AST) -> Dict[str, str]:
    if not isinstance(node, ast.Dict):
        return {}
    return {
        key.value: value.value
        for key, value in zip(node.keys, node.values)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
        and isinstance(value, ast.Constant) and isinstance(value.value, str)
    }


def add_constant(values: Dict[str, List[str]], field_name: str, constant: str) -> None:
    bucket = values.setdefault(field_name, [])
    if constant not in bucket:
        bucket.append(constant)


class StateActivity(NamedTuple):
    written: Dict[str, List[str]]
    called: List[str]
    returned: Dict[str, List[str]]
    write_arguments: List[str]
    written_guards: Dict[str, Dict[str, List[List[str]]]]
    call_context_flags: Dict[str, List[str]]


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


def context_flag_of(node: ast.AST) -> Optional[str]:
    """Flag read by `<x>.env.context.get('f')`, `<x>.env.context['f']` or `<x>._context.get('f')`.

    A `.get` whose default is truthy is not a guard: the branch runs when the flag is absent."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
        container, key = node.func.value, node.args[0]
        if len(node.args) > 1 and not (isinstance(node.args[1], ast.Constant) and not node.args[1].value):
            return None
    elif isinstance(node, ast.Subscript):
        container, key = node.value, node.slice
    else:
        return None
    if not (isinstance(key, ast.Constant) and isinstance(key.value, str) and isinstance(container, ast.Attribute)):
        return None
    on_env = isinstance(container.value, ast.Attribute) and container.value.attr == "env"
    return key.value if container.attr == "_context" or (container.attr == "context" and on_env) else None


def context_flags_of_test(test: ast.AST) -> List[str]:
    """Context flags a true `if` test necessarily requires: its context reads, alone or joined by `and`."""
    operands = test.values if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And) else [test]
    return [flag for flag in (context_flag_of(operand) for operand in operands) if flag]


def context_guards_by_node(function_node: ast.AST) -> Dict[int, List[str]]:
    """Context flags required to reach each node, from the `if` bodies enclosing it."""
    guards: Dict[int, List[str]] = {}

    def visit(node: ast.AST, active: List[str]) -> None:
        guards[id(node)] = active
        inside = active
        if isinstance(node, ast.If):
            inside = active + [flag for flag in context_flags_of_test(node.test) if flag not in active]
        for field_name, value in ast.iter_fields(node):
            for child in value if isinstance(value, list) else [value]:
                if isinstance(child, ast.AST):
                    visit(child, inside if isinstance(node, ast.If) and field_name == "body" else active)

    visit(function_node, [])
    return guards


def receiver_context_flags(receiver: ast.AST) -> Set[str]:
    """Context keys set by the `with_context(...)` calls chained on a call receiver; '*' when unreadable."""
    flags: Set[str] = set()
    node = receiver
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in SELF_RECORDSET_METHODS:
        if node.func.attr == "with_context":
            flags.update(keyword.arg or "*" for keyword in node.keywords)
            if node.args:
                flags.add("*")
        node = node.func.value
    return flags


def add_guarded_constant(guards: Dict[str, Dict[str, List[List[str]]]], field_name: str, constant: str, flags: List[str]) -> None:
    occurrences = guards.setdefault(field_name, {}).setdefault(constant, [])
    if flags not in occurrences:
        occurrences.append(flags)


def scan_state_activity(function_node: ast.AST) -> StateActivity:
    """String constants a method writes or returns per field for its own recordset, and the methods it calls on it.

    Also keeps, per write, the context flags guarding it and, per call, the flags the receiver sets."""
    self_names = self_recordset_names(function_node)
    guards = context_guards_by_node(function_node)
    call_flags: Dict[str, Set[str]] = {}
    activity = StateActivity({}, [], {}, [], {}, {})
    for child in ast.walk(function_node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            if not is_self_recordset(child.func.value, self_names):
                continue
            if child.func.attr == "write":
                for argument in child.args:
                    for field_name, constant in constants_in_write_dict(argument).items():
                        add_constant(activity.written, field_name, constant)
                        add_guarded_constant(activity.written_guards, field_name, constant, guards.get(id(child), []))
                    if isinstance(argument, ast.Call) and isinstance(argument.func, ast.Attribute):
                        if is_self_recordset(argument.func.value, self_names) and argument.func.attr not in activity.write_arguments:
                            activity.write_arguments.append(argument.func.attr)
            elif child.func.attr not in SELF_RECORDSET_METHODS:
                if child.func.attr not in activity.called:
                    activity.called.append(child.func.attr)
                call_flags.setdefault(child.func.attr, set()).update(receiver_context_flags(child.func.value))
        elif isinstance(child, ast.Assign):
            value = child.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                for target in child.targets:
                    if isinstance(target, ast.Attribute) and is_self_recordset(target.value, self_names):
                        add_constant(activity.written, target.attr, value.value)
                        add_guarded_constant(activity.written_guards, target.attr, value.value, guards.get(id(child), []))
        elif isinstance(child, ast.Return) and child.value is not None:
            for field_name, constant in constants_in_write_dict(child.value).items():
                add_constant(activity.returned, field_name, constant)
    activity.call_context_flags.update({callee: sorted(flags) for callee, flags in call_flags.items() if flags})
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
        method_decl.written_values = activity.written
        method_decl.called_self_methods = activity.called
        method_decl.returned_values = activity.returned
        method_decl.write_argument_methods = activity.write_arguments
        method_decl.written_guards = activity.written_guards
        method_decl.call_context_flags = activity.call_context_flags
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
