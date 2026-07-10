import json
import os
import sys
import logging
from tqdm import tqdm
from dotenv import load_dotenv

load_dotenv("env")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rag.graph import query_graph
from tools.odoo_tools import (
    obtenir_total_ventes,
    obtenir_total_factures,
    obtenir_tickets_recents
)

logging.basicConfig(level=logging.ERROR)

def run_erp_evaluation():
    with open("tests/benchmark_questions.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    questions = [q for q in data["questions"] if q["category"] == "erp_chiffre"]
    total = len(questions)
    
    print(f"Starting ERP Evaluation on {total} questions...\n")
    
    results = []
    
    for q in tqdm(questions, desc="Evaluating ERP"):
        response = query_graph(q["question"])
        results.append({
            "id": q["id"],
            "question": q["question"],
            "agent_answer": response.answer
        })

    report_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures", "erp_accuracy_report.md")
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# ERP Accuracy Report\n\n")
        for r in results:
            f.write(f"### [{r['id']}] {r['question']}\n")
            f.write(f"**Agent Answer:** {r['agent_answer']}\n\n")
            f.write("---\n")
            
    print(f"\nReport written to {report_path}")

if __name__ == "__main__":
    run_erp_evaluation()
