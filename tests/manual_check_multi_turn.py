import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.graph.graph import query_graph
from langchain_core.messages import HumanMessage, AIMessage

logging.basicConfig(level=logging.ERROR)

def run_multi_turn_test():
    scenarios = [
        [
            "Combien de ventes la Société Dupont a-t-elle réalisées ?",
            "Et pour cette année ?",
            "Quel est leur plus gros achat ?"
        ],
        [
            "Combien de tickets de support sont résolus ?",
            "Et combien sont en cours ?",
            "Quel est le plus récent ?"
        ]
    ]
    
    print("Starting Multi-Turn Evaluation...\n")
    
    for i, scenario in enumerate(scenarios, 1):
        print(f"\n--- Scenario {i} ---")
        chat_history = []
        for q in scenario:
            print(f"\nUser: {q}")
            response = query_graph(q, chat_history=chat_history)
            print(f"Agent: {response.answer}")
            
            chat_history.append(HumanMessage(content=q))
            chat_history.append(AIMessage(content=response.answer))
            
if __name__ == "__main__":
    run_multi_turn_test()
