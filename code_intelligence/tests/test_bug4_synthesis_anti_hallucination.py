from code_intelligence.agent.prompts import build_synthesis_prompt


def test_synthesis_uses_observations_and_rejects_invented_implementation():
    prompt = build_synthesis_prompt('How does approval work?', ['Observed workflow state: pending'])
    assert 'data above' in prompt
    assert 'NEVER write out a Python code block' in prompt
    assert 'If the observations do not contain the actual implementation' in prompt
