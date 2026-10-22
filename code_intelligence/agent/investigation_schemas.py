"""Intent labels retained by the frozen evaluation cases."""

from enum import Enum


class QuestionIntent(str, Enum):
    GOVERNANCE_SECURITY = "governance_security"
    WORKFLOW_STATE = "workflow_state"
    CALCULATION_LOGIC = "calculation_logic"
    INHERITANCE_STRUCTURE = "inheritance_structure"
    AUTOMATION_ACTION = "automation_action"
    ERP_DATA_QUERY = "erp_data_query"
    DOCUMENTARY_POLICY = "documentary_policy"
    GENERAL_CODE_INQUIRY = "general_code_inquiry"
    NAVIGATION_HOWTO = "navigation_howto"
