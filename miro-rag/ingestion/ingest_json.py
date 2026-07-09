"""
ingest_json.py
"""
import os
import sys
import json
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vectorstore.chroma_manager import ChromaManager

FAKE_DATA_DIR = Path(__file__).resolve().parent.parent / "fake_data"

def run():
    chroma = ChromaManager()
    
    # Sales
    with open(FAKE_DATA_DIR / "sales.json", "r", encoding="utf-8") as f:
        sales = json.load(f)
        docs = []
        metas = []
        for s in sales:
            doc = f"Sale #{s['id']}: Client {s['client']}, Produit: {s['produit']}, Montant: {s['montant']} {s['devise']}, Date: {s['date']}, Statut: {s['statut']}"
            meta = {"source": "fake_data/sales.json", "type": "sale", "sale_id": str(s['id']), "client": s['client'], "title": f"Vente {s['client']} - {s['produit']}"}
            docs.append(doc)
            metas.append(meta)
        chroma.add_chunks(texts=docs, metadatas=metas)
            
    # Tickets
    with open(FAKE_DATA_DIR / "tickets.json", "r", encoding="utf-8") as f:
        tickets = json.load(f)
        docs = []
        metas = []
        for t in tickets:
            doc = f"Ticket #{t['id']}: Client {t['client']}, Titre: {t['titre']}, Date: {t['date']}, Statut: {t['statut']}\nDescription: {t['description']}\nSolution: {t.get('solution', '')}"
            meta = {"source": "fake_data/tickets.json", "type": "ticket", "ticket_id": str(t['id']), "client": t['client'], "title": f"Ticket #{t['id']} - {t['titre']}"}
            docs.append(doc)
            metas.append(meta)
        chroma.add_chunks(texts=docs, metadatas=metas)
            
    print("JSON data ingested successfully.")

if __name__ == "__main__":
    run()
