import json, sys, time, logging
logging.disable(logging.CRITICAL)
from document_rag.vectorstore.search import get_retriever
from document_rag.vectorstore.search_hybrid import vector_search
from document_rag.vectorstore.bm25_index import bm25_search
from config.settings import VECTOR_SIMILARITY_FLOOR
q = sys.argv[1]
t = time.time()
chroma, bm25 = get_retriever()
print("retriever ready", round(time.time()-t,1), "s; bm25 built:", bm25.is_built)
t = time.time()
vec = vector_search(chroma, q, top_k=12)
print("vector search", round(time.time()-t,1), "s")
print("VECTOR top 12 (cosine similarity):")
for i, r in enumerate(vec, 1):
    m = r["metadata"]; print(f"  {i:2d} sim={r['score']:.3f}  {m.get('title')} [chunk {m.get('chunk_index')}]")
print("BM25 top 12:")
for i, r in enumerate(bm25_search(bm25, q, top_k=12), 1):
    m = r["metadata"]; print(f"  {i:2d} score={r.get('score', 0):.3f}  {m.get('title')} [chunk {m.get('chunk_index')}]")
