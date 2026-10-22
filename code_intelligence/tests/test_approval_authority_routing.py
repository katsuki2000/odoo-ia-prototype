from code_intelligence.agent.prompts import CI_SYSTEM_PROMPT, build_synthesis_prompt


def test_approval_answers_use_business_terms_and_hide_technical_identifiers():
    prompt = build_synthesis_prompt(
        "Qui est censé approuver les ventes et les achats ?",
        [
            "Role: [All Users] on the Confirm button.",
            "Approval button group: purchase.group_purchase_manager.",
            "The manager group is one path; one-step validation or two-step validation below the configured threshold also allows confirmation.",
        ],
    )

    assert "ERP consultant" in CI_SYSTEM_PROMPT
    assert "verify behavior against its source code or available internal documentation" in CI_SYSTEM_PROMPT
    assert "source identifiers in the evidence record, not in user-facing prose" in CI_SYSTEM_PROMPT
    assert "prefix it exactly as 'xml_id:" not in CI_SYSTEM_PROMPT
    assert "Do NOT translate exact technical identifiers" not in prompt
    assert "Do NOT include technical model names, XML-IDs, Python method names" in prompt
    assert "no group restriction was extracted from that button's interface declaration" in prompt
    assert "does NOT prove every user can perform the operation" in prompt
    assert "Never say an action is unrestricted or needs no approval solely" in prompt
    assert "do not present it as the sole path" in prompt
    assert "do not omit a bypass path" in prompt
