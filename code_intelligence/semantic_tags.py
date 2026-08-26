"""
code_intelligence/semantic_tags.py

Two independent, non-overlapping vocabularies, matching architecture.md
exactly (not invented here):

- BehavioralTag: what a piece of Odoo logic DOES from a business-visible
  standpoint (restricts visibility, blocks an action, computes a value,
  drives a workflow transition, gates an approval, sends a notification).
  Several behavioral tags can apply to the same underlying artefact -- an
  ir.rule with a domain_force referencing 'state' can be both a
  visibility_rule and a workflow_rule.

- TechnicalTag: which concrete Odoo mechanism implements the behavior
  (ir.rule, ir.model.access, an ORM constrains()/@api.constrains, a
  compute= field, an ir.actions.server, an ir.cron). Exactly one technical
  tag applies per concrete artefact (a given ir.rule record is a
  record_rule, never also an acl) -- this vocabulary mirrors the existing
  node_type values already used as literal strings in graph_builder.py
  (Rule, AccessEntry, ServerAction, ...), not a new classification scheme.

Kept as two separate (str, Enum) classes rather than one flat list so a
caller can never accidentally pass a technical tag where a behavioral one
is expected or vice versa -- the same isinstance-checkable safety
QueryRoute already gives routing.py, deliberately not just a frozenset of
strings.
"""

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
