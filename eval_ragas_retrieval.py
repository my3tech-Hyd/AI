# eval_ragas_retrieval.py
# pip install ragas datasets langchain-openai
import os
os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")  # prevents the ImportError
# Optional: if Git is installed but not on PATH, point to it:
if os.name == "nt":
    default_git = r"C:\Program Files\Git\bin\git.exe"
    if os.path.exists(default_git):
        os.environ.setdefault("GIT_PYTHON_GIT_EXECUTABLE", default_git)

from ragas import evaluate, EvaluationDataset
import json
from ragas import evaluate, EvaluationDataset
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import LLMContextRecall   # needs reference
from langchain_openai import ChatOpenAI


def load_rows(jsonl_path):
    rows = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return rows

if __name__ == "__main__":
    rows = load_rows("eval_retrieval_small.jsonl")
    dataset = EvaluationDataset.from_list(rows)

    # judge model (cheap + fast is fine for dev)
    judge = LangchainLLMWrapper(ChatOpenAI(model="gpt-4o-mini"))  # swap if you prefer

    # retrieval metrics:
    metrics = [LLMContextRecall(llm=judge)]   # add context precision variant below

    # Try to prefer reference-free precision first; fallback to “with reference” if you provide gold contexts.
    try:
        from ragas.metrics import LLMContextPrecisionWithoutReference
        metrics.append(LLMContextPrecisionWithoutReference(llm=judge))
    except Exception:
        try:
            from ragas.metrics import NonLLMContextPrecisionWithReference
            metrics.append(NonLLMContextPrecisionWithReference())
        except Exception:
            pass
    metrics = [LLMContextRecall(llm=judge)]
    result = evaluate(dataset=dataset, metrics=metrics, llm=judge)
    print(result)
