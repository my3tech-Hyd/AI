from typing import Dict, List
import math

def _dcg(rel: List[float]) -> float:
    return sum((r / math.log2(i + 2)) for i, r in enumerate(rel))

def _ndcg_at_k(pred: List[str], gold: List[str], k: int) -> float:
    pred = pred[:k]
    rel = [1.0 if pid in gold else 0.0 for pid in pred]
    ideal = sorted(rel, reverse=True)
    return 0.0 if sum(ideal) == 0 else _dcg(rel) / _dcg(ideal)

def _recall_at_k(pred: List[str], gold: List[str], k: int) -> float:
    if not gold: return 0.0
    return len(set(pred[:k]) & set(gold)) / float(len(set(gold)))

def _mrr_at_k(pred: List[str], gold: List[str], k: int) -> float:
    gold_set = set(gold)
    for i, pid in enumerate(pred[:k], 1):
        if pid in gold_set:
            return 1.0 / i
    return 0.0

# LangSmith custom evaluator: a simple function that returns metrics dict
# (You can also return EvaluationResult objects or multiple scores.)
def match_quality(outputs: Dict, example: Dict):
    pred = outputs.get("pred_doc_ids") or []
    gold = example["outputs"]["gold_doc_ids"] or []
    top1_hit = 1.0 if (pred[:1] and pred[0] in set(gold)) else 0.0

    return {
        "score": _ndcg_at_k(pred, gold, k=5),     # primary score shown in UI
        "hit_at_1": top1_hit,
        "recall_at_3": _recall_at_k(pred, gold, 3),
        "recall_at_5": _recall_at_k(pred, gold, 5),
        "mrr_at_5": _mrr_at_k(pred, gold, 5),
        "ndcg_at_5": _ndcg_at_k(pred, gold, 5),
    }
