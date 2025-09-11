# scripts/targets/chat_retrieval_target.py
import os
from typing import Dict
from streamlit_chat import hybrid_retrieve, get_chroma, load_bm25_index
from config import TOP_K_VECTOR, HYBRID_ALPHA  # <-- no TOP_K_FINAL import here

os.environ.setdefault("LANGSMITH_TRACING", "true")
os.environ.setdefault("LANGSMITH_TRACING_V2", "true")
os.environ.setdefault("LANGSMITH_PROJECT", "ResumeFinder")

TOP_K_FINAL = int(os.getenv("TOP_K_FINAL_CHAT", "5"))  # <-- define here

(_, COLL) = get_chroma()
BM25, DOC_IDS, ID2POS = load_bm25_index()

def target(inputs: Dict) -> Dict:
    jd = inputs["input"]
    results, _ = hybrid_retrieve(
        jd, COLL, BM25, DOC_IDS, ID2POS,
        top_k_vec=TOP_K_VECTOR,
        top_k_final=TOP_K_FINAL,             # <-- use the env/default 5
        alpha_weight=HYBRID_ALPHA,
    )
    pred_ids   = [r["document_id"] for r in results]
    pred_names = [r.get("candidate_name") for r in results]
    return {"pred_doc_ids": pred_ids, "pred_names": pred_names, "raw": results}
