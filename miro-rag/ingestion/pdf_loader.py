"""
ingestion/pdf_loader.py

Loads, chunks, and prepares all knowledge sources for the RAG vectorstore:
1. Wiki and policy TXT documents from fake_data/documents/
2. PDF manuals from fake_data/documents/
3. Support tickets from fake_data/tickets.json
4. Sales data from fake_data/sales.json
"""

import os
import sys
import json
import hashlib
from langchain_text_splitters import RecursiveCharacterTextSplitter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAKE_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fake_data")


def get_text_splitter(chunk_size=600, chunk_overlap=50):
    """Return an optimal recursive character text splitter."""
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""]
    )


def make_id(source, index):
    """Generate a deterministic unique ID for a document chunk using MD5 hash."""
    raw = f"{source}_{index}"
    return hashlib.md5(raw.encode()).hexdigest()


def load_txt_documents():
    """Load all text documents from the documents directory and split them into chunks."""
    docs_dir = os.path.join(FAKE_DATA_DIR, "documents")
    documents = []
    metadatas = []
    ids = []

    splitter = get_text_splitter()
    txt_files = [f for f in os.listdir(docs_dir) if f.endswith('.txt')]

    for filename in sorted(txt_files):
        filepath = os.path.join(docs_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        lines = content.strip().split('\n')
        title = lines[0].strip() if lines else filename

        chunks = splitter.split_text(content)

        for i, chunk in enumerate(chunks):
            documents.append(chunk)
            metadatas.append({
                "source": filename,
                "type": "wiki",
                "title": title,
                "chunk_index": i,
                "total_chunks": len(chunks),
            })
            ids.append(make_id(f"wiki_{filename}", i))

        print(f"Loaded '{filename}': {len(chunks)} chunks")

    return documents, metadatas, ids


def load_pdf_documents():
    """Load PDF documents from the documents directory and split them into chunks."""
    docs_dir = os.path.join(FAKE_DATA_DIR, "documents")
    documents = []
    metadatas = []
    ids = []

    splitter = get_text_splitter()
    pdf_files = [f for f in os.listdir(docs_dir) if f.endswith('.pdf')]

    for filename in sorted(pdf_files):
        filepath = os.path.join(docs_dir, filename)
        try:
            from pypdf import PdfReader
            reader = PdfReader(filepath)
            content = ""
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    content += extracted + "\n"
        except ImportError:
            print(f"Warning: pypdf not available, skipping {filename}")
            continue

        if not content.strip():
            print(f"Warning: No text extracted from {filename}")
            continue

        chunks = splitter.split_text(content)

        for i, chunk in enumerate(chunks):
            documents.append(chunk)
            metadatas.append({
                "source": filename,
                "type": "manual",
                "title": f"Manual: {filename}",
                "chunk_index": i,
                "total_chunks": len(chunks),
            })
            ids.append(make_id(f"pdf_{filename}", i))

        print(f"Loaded '{filename}': {len(chunks)} chunks")

    return documents, metadatas, ids


def load_tickets():
    """Load support tickets from tickets.json and format them as documents."""
    tickets_file = os.path.join(FAKE_DATA_DIR, "tickets.json")
    documents = []
    metadatas = []
    ids = []

    with open(tickets_file, 'r', encoding='utf-8') as f:
        tickets = json.load(f)

    for ticket in tickets:
        doc = (
            f"SUPPORT TICKET #{ticket['id']:03d}\n"
            f"Title: {ticket['titre']}\n"
            f"Client: {ticket['client']}\n"
            f"Date: {ticket['date']}\n"
            f"Status: {ticket['statut']}\n\n"
            f"PROBLEM:\n{ticket['description']}\n\n"
            f"SOLUTION:\n{ticket['solution']}"
        )
        documents.append(doc)
        metadatas.append({
            "source": "tickets.json",
            "type": "ticket",
            "ticket_id": ticket['id'],
            "client": ticket['client'],
            "statut": ticket['statut'],
            "date": ticket['date'],
            "title": f"TICKET #{ticket['id']:03d} - {ticket['titre']}",
        })
        ids.append(make_id("ticket", ticket['id']))

    print(f"Loaded {len(tickets)} support tickets")
    return documents, metadatas, ids


def load_sales():
    """Load sales data from sales.json and format them as documents."""
    sales_file = os.path.join(FAKE_DATA_DIR, "sales.json")
    documents = []
    metadatas = []
    ids = []

    with open(sales_file, 'r', encoding='utf-8') as f:
        sales = json.load(f)

    for sale in sales:
        doc = (
            f"SALE #{sale['id']:03d}\n"
            f"Client: {sale['client']}\n"
            f"Product/Service: {sale['produit']}\n"
            f"Amount: {sale['montant']:,} {sale['devise']}\n"
            f"Date: {sale['date']}\n"
            f"Status: {sale['statut']}"
        )
        documents.append(doc)
        metadatas.append({
            "source": "sales.json",
            "type": "sale",
            "sale_id": sale['id'],
            "client": sale['client'],
            "produit": sale['produit'],
            "montant": sale['montant'],
            "statut": sale['statut'],
            "date": sale['date'],
            "title": f"SALE #{sale['id']:03d} - {sale['client']} ({sale['produit']})",
        })
        ids.append(make_id("sale", sale['id']))

    print(f"Loaded {len(sales)} sales records")
    return documents, metadatas, ids


def load_all():
    """Load all data sources and return combined documents, metadatas, and ids."""
    all_docs = []
    all_meta = []
    all_ids = []

    print("\nLoading all knowledge sources...")

    for loader_func in [load_txt_documents, load_pdf_documents, load_tickets, load_sales]:
        docs, meta, doc_ids = loader_func()
        all_docs.extend(docs)
        all_meta.extend(meta)
        all_ids.extend(doc_ids)

    print(f"\nTotal: {len(all_docs)} document chunks ready for vectorization")
    return all_docs, all_meta, all_ids


if __name__ == "__main__":
    docs, meta, ids = load_all()
    print(f"\nLoaded {len(docs)} chunks from {len(set(m['source'] for m in meta))} sources")
    type_counts = {}
    for m in meta:
        t = m['type']
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, c in sorted(type_counts.items()):
        print(f"  - {t}: {c} chunks")
