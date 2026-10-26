from code_intelligence.agent import tools
from code_intelligence.agent.tools import ALL_CI_TOOLS, read_source_fragment, search_system


EXPECTED_POC_TOOL_NAMES = {
    "search_system",
    "read_source_fragment",
    "who_has_access_to",
    "evaluate_record_rules",
    "analyze_server_actions",
    "analyze_security_locks",
    "analyze_method_override_chain",
    "analyze_data_constraints",
    "button_execution_path",
    "describe_workflow",
    "describe_navigation_path",
}


def test_agent_exposes_only_tools_needed_for_the_poc_scope():
    exposed = [search_system, read_source_fragment, *ALL_CI_TOOLS]
    names = [tool.name for tool in exposed]

    assert len(names) == len(set(names))
    assert set(names) == EXPECTED_POC_TOOL_NAMES


def test_package_exports_only_tools_needed_for_the_poc():
    # ALL_CI_TOOLS is the registry list, not a tool.
    assert set(tools.__all__) - {"ALL_CI_TOOLS"} == EXPECTED_POC_TOOL_NAMES
