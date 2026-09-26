"""
code_intelligence/tests/test_section943_stage_recurrence_workflow.py

todo/contexte.txt section 939 / section 943 (Point S): deterministic AST-based
extraction of stage-driven recurrence conditions (repeat_type == 'forever' or
schedule_date <= repeat_until) and actions from write(), enrichment of
describe_workflow -> write() observations, prompt guidance, and postprocessing
correction for MNT-Q2.
"""

from types import SimpleNamespace
import pytest

from code_intelligence.rules.workflow import (
    inspect_stage_workflow_actions,
    format_stage_workflow_note,
    _backfill_stage_recurrence_conditions,
)
from code_intelligence.agent.context import DispatchContext
from code_intelligence.agent.predispatch_structure import dispatch_describe_workflow
from code_intelligence.agent.tool_helpers import set_graph_ref
from code_intelligence.agent.tools import ALL_CI_TOOLS


_MAINTENANCE_REQUEST_WRITE = '''
    def write(self, vals):
        if vals and 'kanban_state' not in vals and 'stage_id' in vals:
            vals['kanban_state'] = 'normal'
        now = fields.Datetime.now()
        if 'stage_id' in vals and self.env['maintenance.stage'].browse(vals['stage_id']).done:
            for request in self:
                if request.maintenance_type != 'preventive' or not request.recurring_maintenance:
                    continue
                schedule_date = request.schedule_date or now
                schedule_date += relativedelta(**{f"{request.repeat_unit}s": request.repeat_interval})
                if request.repeat_type == 'forever' or schedule_date.date() <= request.repeat_until:
                    request.copy({'schedule_date': schedule_date, 'stage_id': request._default_stage().id})
        res = super(MaintenanceRequest, self).write(vals)
        if vals.get('owner_user_id') or vals.get('user_id'):
            self._add_followers()
        if 'stage_id' in vals:
            self.filtered(lambda m: m.stage_id.done).write({'close_date': fields.Date.today()})
            self.filtered(lambda m: not m.stage_id.done).write({'close_date': False})
            self.activity_feedback(['maintenance.mail_act_maintenance_request'])
            self.activity_update()
        return res
'''


def test_inspect_stage_workflow_actions_maintenance_write():
    actions = inspect_stage_workflow_actions(_MAINTENANCE_REQUEST_WRITE)
    assert actions["has_recurrence_copy"] is True
    assert len(actions["copy_conditions"]) >= 2
    assert any("repeat_until" in c for c in actions["copy_conditions"])
    assert any("stage_id" in c for c in actions["copy_conditions"])
    assert actions["has_close_date"] is True
    assert actions["has_kanban_reset"] is True
    assert actions["has_activity_update"] is True
    assert actions["followers_condition"] is not None
    assert any("owner_user_id" in c for c in actions["followers_condition"])


def test_format_stage_workflow_note():
    actions = {
        "has_recurrence_copy": True,
        "has_close_date": True,
        "has_kanban_reset": True,
        "has_activity_update": True,
    }
    note = format_stage_workflow_note("maintenance.request", actions)
    assert "[FAIT DÉTERMINISTIQUE -- WORKFLOW D'ÉTAPE ET RÉCURRENCE (write())]" in note
    assert "maintenance.request" in note
    assert "repeat_type == 'forever'" in note
    assert "repeat_until" in note
    assert "close_date = today" in note
    assert "kanban_state à 'normal'" in note
    assert "aucun follower" in note.lower()


def test_backfill_stage_recurrence_conditions_adds_missing_boundary():
    raw_obs = (
        "[FAIT DÉTERMINISTIQUE -- WORKFLOW D'ÉTAPE ET RÉCURRENCE (write())]\n"
        "Pour le modèle 'maintenance.request'..."
    )
    q = "Que se passe-t-il automatiquement quand une demande de maintenance preventive et recurrente atteint 'done' ?"
    answer = (
        "### Ce qui se produit automatiquement\n\n"
        "- **Création d’une nouvelle demande**\n"
        "  Dès que la demande passe à l’étape « done », Odoo génère une nouvelle demande.\n"
        "  - La date de planification est calculée.\n"
        "  - La nouvelle demande est placée dans l’étape par défaut.\n\n"
        "- **Mise à jour de la demande actuelle**\n"
        "  - La date de clôture est fixée à aujourd'hui."
    )
    fixed = _backfill_stage_recurrence_conditions(answer, raw_obs, question=q)
    assert "repeat_until" in fixed
    assert "repeat_type" in fixed
    assert "Condition d’arrêt de la récurrence" in fixed


def test_backfill_stage_recurrence_conditions_strips_false_followers():
    raw_obs = (
        "[FAIT DÉTERMINISTIQUE -- WORKFLOW D'ÉTAPE ET RÉCURRENCE (write())]\n"
        "Pour le modèle 'maintenance.request'..."
    )
    q = "Que se passe-t-il automatiquement quand une demande de maintenance preventive et recurrente atteint 'done' ?"
    answer = (
        "### Ce qui se produit automatiquement\n\n"
        "- **Création d’une nouvelle demande**\n"
        "  Dès que la demande passe à l’étape « done », elle est dupliquée si repeat_type=='forever' ou date <= repeat_until.\n\n"
        "- **Gestion des notifications**\n"
        "  - Les followers de la demande sont conservés et des notifications sont envoyées."
    )
    cleaned = _backfill_stage_recurrence_conditions(answer, raw_obs, question=q)
    assert "Gestion des notifications" not in cleaned
    assert "followers de la demande sont conservés" not in cleaned


def test_backfill_stage_recurrence_conditions_skips_when_already_explained():
    raw_obs = (
        "[FAIT DÉTERMINISTIQUE -- WORKFLOW D'ÉTAPE ET RÉCURRENCE (write())]\n"
        "Pour le modèle 'maintenance.request'..."
    )
    q = "demande de maintenance preventive et recurrente"
    already_complete = (
        "### Ce qui se produit\n\n"
        "- Duplication automatique si repeat_type == 'forever' ou date <= repeat_until."
    )
    res = _backfill_stage_recurrence_conditions(already_complete, raw_obs, question=q)
    assert res == already_complete


@pytest.fixture(scope="module")
def real_graph():
    from code_intelligence.graph.loader import get_code_intelligence_graph
    return get_code_intelligence_graph()


def test_dispatch_workflow_write_enriches_observation_and_prompt(real_graph):
    class FakeTraceLogger:
        def log_hop(self, *args, **kwargs):
            pass

    set_graph_ref(real_graph)
    ctx = DispatchContext(
        G=real_graph,
        concept=SimpleNamespace(
            is_resolved=True, resolved_models=["maintenance.request"], resolved_modules=["maintenance"],
        ),
        question="Que se passe-t-il automatiquement quand une demande de maintenance preventive et recurrente atteint 'done' ?",
        tool_map={t.name: t for t in ALL_CI_TOOLS},
        resolved_user_group_xmlids=[],
        trace_logger=FakeTraceLogger(),
        trace_id="test",
        hop_cap=20,
    )
    dispatch_describe_workflow(ctx)

    write_obs = next((o for o in ctx.tool_observations if "def write" in o), None)
    assert write_obs is not None
    assert "[FAIT DÉTERMINISTIQUE -- WORKFLOW D'ÉTAPE ET RÉCURRENCE (write())]" in write_obs
    assert "repeat_until" in write_obs
    assert "repeat_type == 'forever'" in write_obs
    assert "STAGE-BASED MODEL(S)" in ctx.system_prompt_suffix
    assert "FAIT DÉTERMINISTIQUE -- WORKFLOW D'ÉTAPE ET RÉCURRENCE" in ctx.system_prompt_suffix
