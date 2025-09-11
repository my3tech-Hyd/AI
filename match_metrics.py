# scripts/evaluators/match_metrics.py
from typing import Dict, List, Any
import math, json, ast

def _parse_listish(x: Any) -> List[str]:
    if x is None: return []
    if isinstance(x, (list, tuple)): return [str(t) for t in x]
    s = str(x).strip()
    # Try JSON or Python-literal (handles "['id']")
    for parser in (json.loads, ast.literal_eval):
        try:
            v = parser(s)
            if isinstance(v, (list, tuple)):
                return [str(t) for t in v]
        except Exception:
            pass
    # Fallback: comma split
    return [t.strip() for t in s.split(",") if t.strip()]

def _dcg(rel: List[float]) -> float:
    return sum((r / math.log2(i + 2)) for i, r in enumerate(rel))

def _ndcg_at_k(pred: List[str], gold: List[str], k: int) -> float:
    pred = pred[:k]
    gset = set(gold)
    rel = [1.0 if pid in gset else 0.0 for pid in pred]
    ideal = sorted(rel, reverse=True)
    return 0.0 if sum(ideal) == 0 else _dcg(rel) / _dcg(ideal)

def _recall_at_k(pred: List[str], gold: List[str], k: int) -> float:
    if not gold: return 0.0
    return len(set(pred[:k]) & set(gold)) / float(len(set(gold)))

def _extract(outputs: Dict, example: Any):
    pred = _parse_listish(outputs.get("pred_doc_ids"))
    outs = getattr(example, "outputs", {}) if hasattr(example, "outputs") else (example.get("outputs", {}) if isinstance(example, dict) else {})
    gold = _parse_listish(outs.get("gold_doc_ids"))
    return pred, gold

def match_at_k(outputs: Dict, example: Any, **kwargs):
    pred, gold = _extract(outputs, example)
    return {"key": "hit_at_1", "score": 1.0 if (pred[:1] and pred[0] in set(gold)) else 0.0}

def ndcg5(outputs: Dict, example: Any, **kwargs):
    pred, gold = _extract(outputs, example)
    return {"key": "ndcg_at_5", "score": _ndcg_at_k(pred, gold, 5)}

def recall5(outputs: Dict, example: Any, **kwargs):
    pred, gold = _extract(outputs, example)
    return {"key": "recall_at_5", "score": _recall_at_k(pred, gold, 5)}
