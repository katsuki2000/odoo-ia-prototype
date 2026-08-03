"""
code_intelligence/verify_sourcing.py

Bloc 4 (J14): Mechanical, non-visual verification that every source
reference produced by the Blocs 1-3 mechanisms points to something real --
never a plausible-looking but unverified string.

Two verifiers, matching the two kinds of source the plan allows:

  - verify_xml_id(...)      : Blocs 1 & 2 (RuleDetail.rule_xml_id,
                              ServerActionCodeAnalysis.action_xml_id) --
                              resolves the xml_id via ir.model.data on the
                              LIVE Odoo instance and confirms the referenced
                              record actually exists and belongs to the
                              expected model. Catches hallucinated xml_ids
                              and stale ir.model.data entries (deleted
                              records) alike.

  - verify_semgrep_match(...) : Bloc 3 (SemgrepMatch) -- re-runs Semgrep on
                              the exact target file and confirms the match
                              is still reported at the same location with
                              the same check_id. Stronger than a plain
                              "does this line exist" check: it also catches
                              drift when the file was edited after the
                              match was produced/cached.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from code_intelligence.odoo_rpc_client import OdooRpcClient, OdooRpcError
from code_intelligence.semgrep_runner import SemgrepMatch, run_semgrep_analysis


@dataclass
class SourcingVerificationResult:
    reference: str
    kind: str  # "xml_id" or "semgrep_match"
    verified: bool
    reason: str = ""


def verify_xml_id(
    rpc: OdooRpcClient,
    admin_uid: int,
    xml_id: str,
    expected_model: str,
) -> SourcingVerificationResult:
    """
    Resolve xml_id ('module.name') via ir.model.data on the live instance
    and confirm the referenced record exists and matches expected_model.
    """
    if "." not in xml_id:
        return SourcingVerificationResult(
            reference=xml_id, kind="xml_id", verified=False,
            reason=f"Malformed xml_id (no module prefix): '{xml_id}'",
        )
    module, name = xml_id.split(".", 1)

    try:
        records = rpc.execute_kw(
            admin_uid,
            "ir.model.data",
            "search_read",
            [[["module", "=", module], ["name", "=", name]]],
            {"fields": ["model", "res_id"], "limit": 1},
        )
    except OdooRpcError as e:
        return SourcingVerificationResult(
            reference=xml_id, kind="xml_id", verified=False,
            reason=f"RPC error resolving xml_id: {e}",
        )

    if not records:
        return SourcingVerificationResult(
            reference=xml_id, kind="xml_id", verified=False,
            reason=(
                f"xml_id '{xml_id}' not found in ir.model.data -- "
                f"hallucinated or stale reference."
            ),
        )

    record = records[0]
    actual_model = record.get("model")
    res_id = record.get("res_id")

    if actual_model != expected_model:
        return SourcingVerificationResult(
            reference=xml_id, kind="xml_id", verified=False,
            reason=(
                f"xml_id '{xml_id}' resolves to model '{actual_model}', "
                f"not the expected '{expected_model}'."
            ),
        )

    try:
        count = rpc.execute_kw(
            admin_uid, actual_model, "search_count", [[["id", "=", res_id]]],
        )
    except OdooRpcError as e:
        return SourcingVerificationResult(
            reference=xml_id, kind="xml_id", verified=False,
            reason=f"RPC error confirming record existence: {e}",
        )

    if not count:
        return SourcingVerificationResult(
            reference=xml_id, kind="xml_id", verified=False,
            reason=(
                f"xml_id '{xml_id}' points to res_id={res_id} on "
                f"'{actual_model}', but no such record exists (deleted "
                f"record or ir.model.data out of sync)."
            ),
        )

    return SourcingVerificationResult(
        reference=xml_id, kind="xml_id", verified=True,
        reason=f"Resolved to existing '{actual_model}' record (res_id={res_id}).",
    )


def verify_semgrep_match(
    match: SemgrepMatch,
    config_path: Path,
) -> SourcingVerificationResult:
    """
    Re-run Semgrep on match.filepath and confirm the match is still found
    at the same location with the same check_id -- not just "the line
    exists on disk", but "Semgrep still agrees this is a real match right
    now".
    """
    reference = f"{match.filepath}:{match.start_line}-{match.end_line} ({match.check_id})"
    target_path = Path(match.filepath)

    if not target_path.exists():
        return SourcingVerificationResult(
            reference=reference, kind="semgrep_match", verified=False,
            reason=f"File does not exist on disk: {match.filepath}",
        )

    current_matches = run_semgrep_analysis(target_path, config_path)

    for current in current_matches:
        if (
            current.check_id == match.check_id
            and current.filepath == match.filepath
            and current.start_line == match.start_line
            and current.end_line == match.end_line
        ):
            return SourcingVerificationResult(
                reference=reference, kind="semgrep_match", verified=True,
                reason="Re-run confirms an identical match at the same location.",
            )

    return SourcingVerificationResult(
        reference=reference, kind="semgrep_match", verified=False,
        reason=(
            "Re-run of Semgrep no longer reports this match at this "
            "location -- the file changed since extraction, or the "
            "original match was stale/incorrect."
        ),
    )


def verify_batch(
    rpc: OdooRpcClient,
    admin_uid: int,
    xml_id_refs: List[Tuple[str, str]],  # (xml_id, expected_model)
    semgrep_matches: List[SemgrepMatch],
    semgrep_config_path: Path,
) -> List[SourcingVerificationResult]:
    """
    Run both verifiers over a batch of references collected from a single
    benchmark run and return one result per reference, in input order.
    """
    results = [
        verify_xml_id(rpc, admin_uid, xml_id, expected_model)
        for xml_id, expected_model in xml_id_refs
    ]
    results += [
        verify_semgrep_match(m, semgrep_config_path) for m in semgrep_matches
    ]
    return results
