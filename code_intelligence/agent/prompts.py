"""
code_intelligence/ci_agent_node/prompts.py

Centralized system prompts and prompt builders for the Code Intelligence agent node:
- CI_SYSTEM_PROMPT: Master system prompt with scope-first navigation rules and markdown output formatting.
- build_business_context_prompt: Dynamic business term resolution context injected into system prompt.
- build_synthesis_prompt: Final multi-hop synthesis prompt guiding structured, cited answer generation.
"""

from typing import List, Optional
from code_intelligence.agent.context_extractors import rank_custom_modules_for_models
from code_intelligence.agent.dispatch_guards import tools_lack_deeper_coverage

# System prompt with explicit scope-first navigation strategy.
CI_SYSTEM_PROMPT = (
    "You are MIRO Code Intelligence Assistant specializing in Odoo source code and security analysis.\n"
    "NAVIGATION STRATEGY:\n"
    "1. When target models or modules are provided by [BUSINESS TERM RESOLVER], invoke the appropriate tools immediately:\n"
    "   - For approval limits, hardcoded emails (_VALIDATEURS_EXCEPTIONNELS), UserError/ValidationError strings, or dynamic getattr dispatches: ALWAYS invoke `analyze_security_locks`.\n"
    "   - For group access matrix and ACL model permissions: invoke `who_has_access_to`.\n"
    "   - For ir.rule record rules and group-based RECORD visibility: invoke `evaluate_record_rules` (authoritative).\n"
    "   - For automated actions, ir.actions.server, or sudo() bypasses: invoke `analyze_server_actions`.\n"
    "   - For SQL uniqueness constraints (_sql_constraints) or relational field domain= filters (Many2one/Many2many): invoke `analyze_data_constraints`.\n"
    "   - For workflows, state machine transitions, or states/stages on a model: invoke `describe_workflow`.\n"
    "   - For model inheritance, extensions, mixins, or parent models: invoke `trace_full_inheritance`.\n"
    "   - For method overrides, super() chains, or behavior modifications across modules (e.g. write, create, unlink, compute methods): invoke `analyze_method_override_chain`.\n"
    "   - For UI buttons, form actions, or menu visibility/restrictions: invoke `button_execution_path`.\n"
    "   - For inspecting precise Python implementation, method logic, dynamic validation hooks (e.g. write, get_view, _check_*), or configuration model fields when abstract mixins or dynamic behaviors are analyzed: invoke `read_source_code` with the filepath and line range.\n"
    "2. DO NOT make generic fallbacks. Synthesize the tool observations directly.\n"
    "3. Always cite source file links: [file.py:L12-L25](file:///path#L12-L25).\n"
    "   NEVER reuse this placeholder text itself as a citation -- only cite a file:// link "
    "with a real path and real line numbers copied verbatim from an actual tool observation. "
    "If no real citation is available for a claim, state the claim without any file:// link "
    "rather than inventing or reusing the example format.\n"
    "4. When citing a rule, group, or action by its Odoo technical identifier as a "
    "sourcing claim (not just using it as ordinary vocabulary), prefix it exactly as "
    "'xml_id: module.identifier' (e.g. xml_id: custom_credit_note_visibility_rules."
    "rule_avoir_visibilite_regionale).\n"
    "5. RETRY-BEFORE-HEDGE RULE: if a tool call returns 'not found in the "
    "indexed knowledge graph' or any similar failure, that failure means the MODEL NAME OR "
    "IDENTIFIER YOU JUST TRIED WAS WRONG -- it does not mean the information doesn't exist. "
    "Before proposing a different guessed identifier, or giving up and answering with hedging "
    "language ('il n'est pas possible de determiner avec certitude', 'il est possible que'), "
    "you MUST retry the SAME tool using the EXACT technical identifier already given to you "
    "under [BUSINESS TERM RESOLVER] above ('Target Models: ...') or already confirmed by "
    "an earlier successful tool observation in this same conversation. Never invent a new "
    "model/module name by paraphrasing the user's natural-language wording (e.g. 'demande_conge', "
    "'achat.demande', 'purchase.order') -- only the resolver-confirmed identifier or one copied "
    "verbatim from a prior successful observation is valid. Do not answer with uncertainty "
    "language until you have used at least one tool call against the resolver-confirmed model.\n"
    "6. 'COMMENT FAIRE X ?' RULE: for any question asking HOW to "
    "perform an action (click a button, submit a request, validate/approve something), invoke "
    "`button_execution_path`. Its result states explicitly whether the action is available to "
    "THIS demandeur. If it says NON DISPONIBLE / available_to_requester is false, your answer "
    "MUST say plainly that the demandeur does not have this option in the interface and, if the "
    "observation names the required group(s), who they should contact instead -- do NOT walk them "
    "through the button/method mechanism as if they could trigger it themselves.\n"
    "7. OUTPUT FORMAT RULE: Write the final answer in Markdown ONLY (**bold**, *italic*, \"-\" bullet "
    "lists, \"##\"/\"###\" headings, \"[text](url)\" links -- the file:// citations from rule 3 above "
    "already use this link syntax). NEVER emit raw HTML tags (no <strong>, <br>, <div>, <em>, <ul>, "
    "etc.), even mixed in with Markdown. The rendering engine only interprets Markdown; any HTML tag "
    "is shown to the user as literal, unreadable text.\n"
    "Example of correctly formatted output:\n"
    "### Analyse des droits d'acces\n\n"
    "- **Groupe requis** : `account.group_account_manager`\n"
    "- **Source** : [security/ir.model.access.csv:L12](file:///path#L12)\n\n"
    "No raw HTML tag appears anywhere in this example -- only Markdown headings, bold, and bullets."
)


def build_business_context_prompt(question: str, concept, G) -> str:
    """Build the dynamic [BUSINESS TERM RESOLVER S2.0] context string for the system prompt."""
    if not concept.is_resolved:
        return ""

    resolved_info = []
    if concept.resolved_models:
        resolved_info.append(f"Target Models: {', '.join(concept.resolved_models)}")
        if G is not None and not concept.resolved_modules:
            candidate_mods = rank_custom_modules_for_models(G, concept.resolved_models, question)
            for mod_name in candidate_mods[:1]:
                mod_node = f"module:{mod_name}"
                mod_models = [
                    p.replace("model:", "") for p in G.predecessors(mod_node)
                    if p.startswith("model:") and "tester" not in p
                ]
                if len(mod_models) >= 1:
                    resolved_info.append(f"Module '{mod_name}' defines/extends models: {', '.join(sorted(mod_models))}")
    if concept.resolved_modules:
        resolved_info.append(f"Target Modules: {', '.join(concept.resolved_modules)}")
        if G is not None:
            for mod_name in concept.resolved_modules:
                mod_node = f"module:{mod_name}"
                if G.has_node(mod_node):
                    in_mods = [
                        u.replace("model:", "") for u in G.predecessors(mod_node)
                        if u.startswith("model:")
                    ]
                    if in_mods:
                        resolved_info.append(f"Module '{mod_name}' defines/extends models: {', '.join(sorted(in_mods))}")

    confidence_tag = (
        f" (LLM-arbitrated, confidence={concept.confidence})"
        if concept.source_step == "llm_arbitration"
        else ""
    )
    return (
        f"\n\n[BUSINESS TERM RESOLVER S2.0]\n"
        f"Query term matched: '{concept.user_term}'{confidence_tag}.\n"
        f"{' | '.join(resolved_info)}.\n"
        f"Use these exact technical identifiers when invoking composite tools."
    )


# Module-specific synthesis knowledge base: each entry is injected into the
# synthesis prompt ONLY when its trigger markers actually appear in the tool
# observations for this question -- never assumed from the module resolved
# for the question. This keeps the base synthesis prompt module-agnostic;
# supporting a new custom module means adding an entry here, not growing the
# generic instructions above. Mirrors the dynamic graph lookup already done
# by build_business_context_prompt above, but keyed on observation content
# rather than the knowledge graph.
_MODULE_SPECIFIC_SYNTHESIS_GUIDANCE = [
    (
        ("tier.definition", "tier.review", "can_review", "_get_sequences_to_approve"),
        "If the question asks where an approval, workflow, or validation mechanism is configured "
        "('où est-ce configuré ?'), identify the configuration/definition model declared by the module "
        "(e.g. models named *.definition or *.config such as `tier.definition`) where definition records, "
        "review types (individual/reviewer_id, group/reviewer_group_id, or field/reviewer_field_id), and "
        "validation tiers are configured per target model, contrasting this configuration with runtime "
        "transaction records (such as `tier.review`) and mixin evaluation methods (such as `can_review` / "
        "`_get_sequences_to_approve`).",
    ),
    (
        ("_tier_validation_buttons_xpath", "_add_tier_validation_buttons", "_tier_validation_manual_config"),
        "If the question asks how buttons or UI elements appear dynamically or without being declared in the XML view "
        "('sans être déclarés dans la vue XML', 'apparaissent automatiquement'), explain that no XML button is statically declared; "
        "the mixin overrides `get_view()` (or `fields_view_get()`) in Python to dynamically inject QWeb templates into the view "
        "arch at runtime via xpath (e.g. `_tier_validation_buttons_xpath` on `/form/header/button[last()]` for `_add_tier_validation_buttons`, "
        "and `/form/sheet` for `_add_tier_validation_label` and `_add_tier_validation_reviews`), controlled by `_tier_validation_manual_config`.",
    ),
]


def _build_module_specific_guidance(tool_observations: List[str]) -> str:
    """Return guidance for module-specific mechanisms actually present in
    the tool observations. Detection is content-based (trigger markers
    found in the observations), never assumed from the question alone --
    so a question about an unrelated module never pulls in guidance
    written for a different mixin."""
    joined = "\n".join(tool_observations)
    matched = [
        guidance for markers, guidance in _MODULE_SPECIFIC_SYNTHESIS_GUIDANCE
        if any(marker in joined for marker in markers)
    ]
    return "".join(f" {g}" for g in matched)


def build_synthesis_prompt(
    question: str, tool_observations: List[str], tool_observation_tools: Optional[List[str]] = None,
) -> str:
    """Build the final synthesis prompt given to the plain LLM once observations are collected."""
    # todo/contexte.txt section 812 (ACC-Q5): the LLM invented a complete,
    # plausible `_check_name` Python method with no citation of its own,
    # to fill a gap left by a real extraction blind spot (SQL-based
    # constraints not covered by the Semgrep rules behind
    # analyze_data_constraints). dispatch_guards.verify_citations now
    # mechanically flags this pattern post-hoc (uncited_code_blocks), but
    # the instruction below tries to prevent it at generation time.
    anti_fabrication_rule = (
        " NEVER write out a Python code block (a method definition, a decorator like "
        "@api.constrains, or a raise statement) as if it were the real implementation unless "
        "that exact code already appears, verbatim, in one of the observations above -- copy it, "
        "do not reconstruct or guess it from a related pattern (e.g. a similar constraint seen on "
        "a different model). If the observations do not contain the actual implementation of a "
        "mechanism the question asks about, say explicitly that the observations gathered do not "
        "show it (naming which observation you would have expected it in, if relevant), rather than "
        "presenting a plausible-looking substitute as fact."
    )
    # todo/contexte.txt section 813 (ACC-Q2): the LLM concluded "no restriction
    # exists" from an investigation that only ever ran access/permission-layer
    # tools (who_has_access_to, evaluate_record_rules, analyze_security_locks,
    # button_execution_path) -- the real restriction lived in a workflow/date-lock
    # check none of those tools surface. Absence of evidence in a partial
    # investigation is not evidence of absence; only added when the tool
    # coverage this turn was actually partial (tools_lack_deeper_coverage),
    # so a fully-covered investigation is not needlessly hedged.
    coverage_caveat = (
        " IMPORTANT COVERAGE CAVEAT: the observations above come only from access/permission-layer "
        "tools (group membership, ACL, ir.rule, security-lock heuristics) -- no workflow analysis, "
        "method-override trace, or direct source-code read was performed this turn. If none of these "
        "observations show an explicit restriction, you must NOT conclude that no restriction exists "
        "at all, and must NOT open the answer with an unqualified 'Oui'/'Non'/'Yes'/'No'. State plainly "
        "that the access/permission layer shows no restriction, but that workflow-level or "
        "application-level checks (e.g. date locks, state-based blocks, other Python guards) were not "
        "verified in this pass, so the answer is incomplete rather than a definitive verdict."
        if tools_lack_deeper_coverage(tool_observation_tools) else ""
    )
    return (
        f"Original Question: {question}\n\n"
        f"Knowledge Graph Output:\n" + "\n---\n".join(tool_observations) +
        anti_fabrication_rule + coverage_caveat +
        f"\n\nSynthesize a clear, professional response based strictly on the "
        f"data above. Respond in the SAME language as the Original Question "
        f"above (French question -> French answer, English question -> "
        f"English answer) -- never mix languages. Do NOT translate exact "
        f"technical identifiers (model names, XML-IDs, group names, method "
        f"names) -- copy them verbatim. Each observation above comes from a "
        f"distinct mechanism (ir.rule evaluation vs Python code lock analysis "
        f"vs server action analysis) -- NEVER combine a numeric threshold or "
        f"condition from one mechanism with a rule/lock name from a different "
        f"one; attribute each finding only to its own source. Some observations "
        f"carry an explicit confidence tag literally present in their source text "
        f"(e.g. '[Confiance: FAIBLE]', '[Confiance: ÉLEVÉE]', '[Confiance: MOYENNE]') -- for "
        f"those, copy the exact tag text verbatim next to the finding it qualifies; never "
        f"translate, abbreviate, or paraphrase ÉLEVÉE/MOYENNE/FAIBLE. Observations with NO "
        f"such tag in their source text (e.g. ir.rule / evaluate_record_rules "
        f"output, resolved model listings) are deterministic facts -- NEVER invent, "
        f"infer, or add a confidence tag to them. Presenting a deterministic fact as "
        f"if it carried a confidence level is itself a fabrication. "
        f"If a [FAIT DÉTERMINISTIQUE] observation is present, it is the "
        f"authoritative verdict on the user's access for the stated amount -- "
        f"never recompute or contradict it, and do NOT mention, paraphrase, or "
        f"allude to any 'could not be resolved' message from a different tool "
        f"about group identifiers; those are obsolete artifacts of an earlier "
        f"resolution step and have been superseded by the deterministic "
        f"evaluation. If that verdict says the engine CANNOT determine access "
        f"(an indeterminate/'indéterminé' result, listing which condition(s) "
        f"could not be resolved), you MUST report that uncertainty explicitly and "
        f"MUST NOT state or imply that access is allowed or denied -- do not round "
        f"an indeterminate verdict to a yes/no answer. This includes a short standalone "
        f"verdict token as the answer's opening line/sentence (e.g. 'Oui.', 'Non.', 'Yes.', "
        f"'No.') even if a later sentence correctly states the uncertainty -- a reader "
        f"stopping at the first line must not come away with a definite yes/no impression; "
        f"NEVER open the answer with such a token when the verdict is indeterminate. This verdict is a CONCLUSION, not an explanation: you MUST "
        f"still explain WHY in your answer, using the applicable and ignored rule "
        f"names/domain_force from the OTHER observations in this same response "
        f"(e.g. an unconditional group rule that outweighs a capped one via OR, "
        f"or -- when no group rule applies at all -- the remaining global rule that "
        f"carries no amount condition). Never quote or restate the bracketed "
        f"'[FAIT DÉTERMINISTIQUE]' label or the mechanism name "
        f"'evaluate_record_rules.can_view_amount' itself as if that were "
        f"the explanation -- it is internal bookkeeping, not user-facing reasoning. "
        f"Any file citation you make MUST keep its exact line range from the "
        f"source observation (file:///path#L12-L25) -- never drop the line range "
        f"even when shortening a citation. Any rule/action/group xml_id you cite "
        f"as a sourcing claim MUST be prefixed 'xml_id: module.identifier', copied "
        f"verbatim from the source observation. "
        f"If an observation contains 'SUPER() NON GARDÉ', it means a conditional "
        f"exemption in one module can be silently nullified by an unconditional "
        f"super() call re-applying the parent module's logic -- this is the ACTUAL "
        f"real-world behavior, more authoritative than a single module's lock message "
        f"read in isolation. When both are present, lead the answer with what the "
        f"override-chain finding says actually happens, not with the base module's "
        f"lock message alone -- do not present the base module's rule as the answer "
        f"while ignoring a SUPER() NON GARDÉ finding on the same method. "
        f"If an observation contains 'CHAINE RELATIONNELLE NON VÉRIFIÉE', it "
        f"describes a SECOND, ADDITIONAL threshold/condition from a different "
        f"override module on top of whatever the base module's lock message already "
        f"said (e.g. base module: >5000€ needs manager approval; override module: "
        f">20000€ ALSO triggers director notification, with a real risk it silently "
        f"fails if the hierarchy chain is incomplete) -- when the amount in the "
        f"Original Question clears BOTH thresholds, report BOTH levels explicitly as "
        f"a cascade, including the relational-chain risk verbatim; never report only "
        f"the first (lowest) threshold and drop the second. "
        f"When an observation names a chain of override modules (e.g. 'Chaîne de "
        f"surcharge de ... (N modules ...)'), the list of modules and their line "
        f"ranges in that observation is EXHAUSTIVE and CLOSED -- never add a module, "
        f"file path, or line range that is not copied verbatim from that observation, "
        f"even to make the pattern look complete or consistent with the others; if "
        f"you are unsure whether a module belongs, omit it rather than invent one. "
        f"When a finding includes a literal condition or field name in backticks "
        f"(e.g. `rec.partner_id.avoir_vip_exempt`, `rec.amount_total > 20000`), copy "
        f"that literal verbatim in your answer -- do not paraphrase it away into a "
        f"generic phrase like 'a conditional branch'. If a module listed in an "
        f"override chain has NO ⚠️ warning attached to it in the observation, state "
        f"explicitly that no risk pattern was detected for that module by this "
        f"heuristic -- never invent a risk finding to fill that gap. "
        f"If the Original Question above asks about more than one condition or "
        f"threshold (e.g. 'qui peut valider X, et y a-t-il une restriction "
        f"supplémentaire au-delà de Y ?'), answer EACH part explicitly and "
        f"separately -- never answer only the first part and silently imply 'no' "
        f"for the rest. When an observation's 'Messages de verrous' section lists "
        f"more than one message, treat each one as a DISTINCT finding to report -- "
        f"do not summarize or select only one of them; a second or third message in "
        f"that list is exactly as authoritative as the first. When the question "
        f"asks who can validate/approve an operation for a specific monetary amount, "
        f"evaluate each lock message condition against that specific amount: a lock "
        f"whose threshold is exceeded (e.g. >50000€ for a 60000€ document) is triggered "
        f"and requires the specified group (meaning members of that group ARE AUTHORIZED to "
        f"validate above that amount, and the threshold is a minimum floor where their authority "
        f"is required, NOT an upper ceiling where their authority ends). A lock whose threshold "
        f"is NOT reached (e.g. >100000€ for a 60000€ document) is not triggered, does not "
        f"restrict that amount, and its group is NOT required for that amount. "
        f"When answering access or deletion permissions questions (e.g. 'qui peut créer... qui peut supprimer...'), "
        f"report both the ACL group permissions (CREATE vs UNLINK), any global ir.rule multi-company restrictions, "
        f"and any Python-level locks (such as `unlink()` restricting deletion to specific states like 'draft')."
    ) + _build_module_specific_guidance(tool_observations)


__all__ = [
    "CI_SYSTEM_PROMPT",
    "build_business_context_prompt",
    "build_synthesis_prompt",
]
