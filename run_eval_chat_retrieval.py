from langsmith import Client
from chat_retrieval_target import target
from match_metrics import match_at_k, ndcg5, recall5

client = Client()
client.evaluate(
    target,                                  # positional (not target=target)
    data="resume_chat_retrieval_v1",
    evaluators=[match_at_k, ndcg5, recall5], # now these exist & have correct signature
    experiment_prefix="chat_retrieval_v1",
    metadata={"component": "chat", "phase": "retrieval"},
    blocking=True,
)
print("Done. Check LangSmith → Experiments.")
