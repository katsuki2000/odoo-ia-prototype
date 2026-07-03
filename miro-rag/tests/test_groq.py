# tests/test_groq.py
import sys
sys.path.append("..")

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from config.settings import GROQ_API_KEY, GROQ_MODEL

load_dotenv()

# LLM initialization
llm = ChatGroq(
    api_key=GROQ_API_KEY,
    model=GROQ_MODEL
)

# Ask a simple question to test the LLM
answer = llm.invoke("In one sentence : what is Odoo ?")
print(" Groq works !")
print("Answer :", answer.content)