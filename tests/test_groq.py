from dotenv import load_dotenv
from langchain_groq import ChatGroq
import pytest

from config.settings import GROQ_API_KEY, GROQ_MODEL

load_dotenv()


@pytest.mark.integration
def test_groq_chat_model_connectivity():
    """Verify Groq connectivity when GROQ_API_KEY is configured."""
    if not GROQ_API_KEY:
        pytest.skip("GROQ_API_KEY is not configured")

    llm = ChatGroq(
        api_key=GROQ_API_KEY,
        model=GROQ_MODEL,
    )
    answer = llm.invoke("In one sentence: what is Odoo?")

    assert answer.content
