from enum import Enum

class BehavioralTag(str, Enum):
    """What a piece of Odoo logic does, from a business-visible standpoint."""

    VISIBILITY_RULE = "visibility_rule"
    BLOCKING_RULE = "blocking_rule"
    CALCULATION_RULE = "calculation_rule"
    WORKFLOW_RULE = "workflow_rule"
    APPROVAL_RULE = "approval_rule"
    NOTIFICATION_RULE = "notification_rule"


class TechnicalTag(str, Enum):
    """Which concrete Odoo mechanism implements the behavior."""

    RECORD_RULE = "record_rule"
    ACL = "acl"
    CONSTRAINT = "constraint"
    COMPUTED_FIELD = "computed_field"
    SERVER_ACTION = "server_action"
    CRON = "cron"
