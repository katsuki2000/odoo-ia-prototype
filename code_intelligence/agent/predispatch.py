"""Execute the semantic investigation plan, without keyword reclassification."""

from .capability_dispatch import run_planned_investigation


def run_predispatch_chain(ctx):
    run_planned_investigation(ctx)
