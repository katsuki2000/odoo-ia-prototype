"""
code_intelligence/ci_agent_node/predispatch_chain.py

Runs every deterministic pre-dispatch block in the exact order the former
ci_agent_node.py monolith used to run them inline. Extracted as part of
the refactor (see todo/contexte.txt) -- each block is now its own module
under code_intelligence/ci_agent_node/predispatch_*.py; this function is
the single call site that sequences them. Behavior unchanged.
"""

from code_intelligence.ci_agent_node.context.dispatch_context import DispatchContext
from .predispatch_security_locks import dispatch_security_locks
from .predispatch_server_actions import dispatch_server_actions
from .predispatch_override_chain import dispatch_override_chain
from .predispatch_access import dispatch_who_has_access_to
from .predispatch_record_rules import dispatch_evaluate_record_rules
from .predispatch_workflow import dispatch_describe_workflow
from .predispatch_inheritance import dispatch_inheritance
from .predispatch_module_ui import dispatch_module_level_ui_inquiry
from .predispatch_button import dispatch_button_execution_path
from .predispatch_constraints import dispatch_analyze_data_constraints


def run_predispatch_chain(ctx: DispatchContext) -> None:
    dispatch_security_locks(ctx)
    dispatch_server_actions(ctx)
    dispatch_override_chain(ctx)
    dispatch_who_has_access_to(ctx)
    dispatch_evaluate_record_rules(ctx)
    dispatch_describe_workflow(ctx)
    dispatch_inheritance(ctx)
    dispatch_module_level_ui_inquiry(ctx)
    dispatch_button_execution_path(ctx)
    dispatch_analyze_data_constraints(ctx)
