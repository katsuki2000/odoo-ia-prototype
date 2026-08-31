#!/usr/bin/env python3
"""
scripts/diagnose_intent_llm_tool_call.py

Diagnostic script (todo/contexte.txt section 396/397) -- reproduces
classify_question_intent_llm()'s systematic Groq tool-call failure
(observed 5/5 in the section 396 rejeu) in isolation, BEFORE any
production code is touched.

Run from repo root:
    python3 scripts/diagnose_intent_llm_tool_call.py

What it does, in order:
  1. Prints the tool name convert_to_openai_tool() derives from
     IntentClassificationLLMResponse -- this is the name Groq's
     tool_choice is forced to (per langchain_groq's with_structured_output
     "function_calling" method, method default).
  2. Calls with_structured_output(..., method="function_calling",
     include_raw=True) directly (bypassing invoke_with_rate_limit's
     retry/recovery so nothing is masked) on the exact question from the
     section 396 transcript, and prints the raw exception if it fails.
  3. Repeats with method="json_schema" -- langchain-groq's dedicated
     Groq Structured Output API path, documented as explicitly supported
     for openai/gpt-oss-20b/120b (with optional strict mode) since
     langchain-groq 0.3.8. This is the working hypothesis for a root-cause
     fix: forced tool-calling ("function_calling", the current default)
     may simply be unreliable for this model family on Groq, and a
     purpose-built alternative already exists in the installed library.

Never modifies any file. Prints results for the user to paste back into
the session so the next step (production fix, if warranted) is decided
on evidence rather than the hypothesis alone.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from core.llm_client import get_chat_llm
from code_intelligence.investigation_plan import (
    IntentClassificationLLMResponse,
    _INTENT_CLASSIFICATION_SYSTEM_PROMPT,
)

QUESTION = "comment créer une demande de facture ?"  # one of the 3 section-396 failing cases


def main():
    print("=" * 70)
    print("1. Tool name convert_to_openai_tool() derives from the schema")
    print("=" * 70)
    formatted_tool = convert_to_openai_tool(IntentClassificationLLMResponse)
    print("Requested tool name (forced via tool_choice):", formatted_tool["function"]["name"])
    print("Full tool schema:", formatted_tool)
    print()

    messages = [
        SystemMessage(content=_INTENT_CLASSIFICATION_SYSTEM_PROMPT),
        HumanMessage(content=f'Question utilisateur : "{QUESTION}"'),
    ]

    print("=" * 70)
    print("2. method='function_calling' (current default, forced tool_choice)")
    print("=" * 70)
    try:
        llm = get_chat_llm(temperature=0.0, max_retries=0)
        structured_llm = llm.with_structured_output(
            IntentClassificationLLMResponse, method="function_calling", include_raw=True
        )
        result = structured_llm.invoke(messages)
        print("SUCCESS:", result)
    except Exception as e:
        print("EXCEPTION TYPE:", type(e).__name__)
        print("EXCEPTION STR:", str(e))
    print()

    print("=" * 70)
    print("3. method='json_schema' (Groq dedicated Structured Output API,")
    print("   documented as supported for openai/gpt-oss-20b/120b)")
    print("=" * 70)
    try:
        llm2 = get_chat_llm(temperature=0.0, max_retries=0)
        structured_llm2 = llm2.with_structured_output(
            IntentClassificationLLMResponse, method="json_schema", include_raw=True
        )
        result2 = structured_llm2.invoke(messages)
        print("SUCCESS:", result2)
    except Exception as e:
        print("EXCEPTION TYPE:", type(e).__name__)
        print("EXCEPTION STR:", str(e))


if __name__ == "__main__":
    main()
