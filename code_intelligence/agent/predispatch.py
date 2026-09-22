"""
code_intelligence/ci_agent_node/predispatch_chain.py

Runs every deterministic pre-dispatch block in the exact order the former
ci_agent_node.py monolith used to run them inline. Extracted as part of
the refactor (see todo/contexte.txt) -- each block is now its own module
under code_intelligence/ci_agent_node/predispatch_*.py; this function is
the single call site that sequences them. Behavior unchanged.

The forced-dispatch predicate functions (security_locks_targets,
server_actions_targets, override_chain_targets, who_has_access_targets)
used to live inline in this file after the Option C merge, which broke
the deferred `from .forced_dispatch_predicates import ...` imports in
predispatch_access.py/predispatch_actions.py (that module had been
collapsed into this one). Restored as its own leaf module (Section 733)
to avoid a real import cycle: this file imports FROM predispatch_access.py
and predispatch_actions.py at module level, and those two import the
predicates back.
"""

from code_intelligence.agent.context import DispatchContext
from code_intelligence.agent.predispatch_access import dispatch_security_locks
from code_intelligence.agent.predispatch_actions import (
    dispatch_server_actions,
    dispatch_override_chain,
    dispatch_analyze_data_constraints,
)
from code_intelligence.agent.predispatch_access import (
    dispatch_who_has_access_to,
    dispatch_evaluate_record_rules,
    dispatch_evaluate_record_rules_for_personas,
    dispatch_security_distinction_guard,
)
from code_intelligence.agent.predispatch_structure import (
    dispatch_describe_workflow,
    dispatch_inheritance,
    dispatch_module_level_ui_inquiry,
    dispatch_button_execution_path,
)


def run_predispatch_chain(ctx: DispatchContext) -> None:
    dispatch_security_locks(ctx)
    dispatch_server_actions(ctx)
    dispatch_override_chain(ctx)
    dispatch_who_has_access_to(ctx)
    dispatch_evaluate_record_rules(ctx)
    dispatch_evaluate_record_rules_for_personas(ctx)
    dispatch_security_distinction_guard(ctx)
    dispatch_describe_workflow(ctx)
    dispatch_inheritance(ctx)
    dispatch_module_level_ui_inquiry(ctx)
    dispatch_button_execution_path(ctx)
    dispatch_analyze_data_constraints(ctx)
