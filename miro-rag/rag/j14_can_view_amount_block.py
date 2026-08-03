                if tool_name in tool_map:
                    try:
                        observation = tool_map[tool_name].invoke(tool_args)
                        tool_observations.append(str(observation))
                        hop_count += 1

                        # J14 fix (Q6.1 regression, rerun of 2026-08-XX):
                        # evaluer_regles_enregistrement's summary_text lists
                        # applicable group rules but never computes the actual
                        # OR-union against a specific amount -- it leaves the
                        # synthesis LLM to guess, and the LLM picked the most
                        # restrictive rule instead of the union. can_view_amount()
                        # already implements the correct AND-global/OR-group
                        # logic; call it directly here on the SAME tool_args the
                        # LLM already supplied (including user_groups_json --
                        # never re-derive group membership by hand), and inject
                        # an unambiguous deterministic fact the synthesis LLM
                        # must not recompute or contradict.
                        if tool_name == "evaluer_regles_enregistrement":
                            amount = _extract_amount(question)
                            if amount is not None:
                                try:
                                    from code_intelligence.deterministic_tools import (
                                        evaluer_regles_enregistrement as _eval_rules_impl,
                                    )
                                    from code_intelligence.ci_agent_tools import _resolve_model_param

                                    model_name = _resolve_model_param(tool_args.get("model_name", ""))
                                    droit = tool_args.get("droit", "read")
                                    try:
                                        user_groups = _json.loads(tool_args.get("user_groups_json", "[]"))
                                    except Exception:
                                        user_groups = []

                                    rule_result = _eval_rules_impl(
                                        G, model_name, droit=droit, user_groups=user_groups
                                    )
                                    can_view = rule_result.can_view_amount(amount)
                                    tool_observations.append(
                                        f"[FAIT DÉTERMINISTIQUE] Pour un montant de {amount:.0f}€, "
                                        f"can_view_amount() = {can_view} -> l'utilisateur "
                                        f"{'PEUT' if can_view else 'NE PEUT PAS'} voir cet "
                                        f"enregistrement. Ce résultat est calculé directement par "
                                        f"le moteur de règles (evaluer_regles_enregistrement."
                                        f"can_view_amount) et ne doit JAMAIS être recalculé ou "
                                        f"contredit par la synthèse -- reprendre ce verdict tel quel."
                                    )
                                    logger.info(
                                        "Node [code_intelligence_agent]: Injected deterministic "
                                        "can_view_amount fact for '%s' (amount=%.0f, result=%s).",
                                        model_name, amount, can_view,
                                    )
                                except Exception as ve:
                                    logger.error(
                                        "Deterministic can_view_amount injection failed: %s", ve
                                    )
                    except Exception as te:
                        logger.error("Tool execution failed (%s): %s", tool_name, te)
                        tool_observations.append(f"Error executing {tool_name}: {str(te)}")
