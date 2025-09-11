import ast, json, pandas as pd
from langsmith import Client

# 1) Load your CSV
df = pd.read_csv("resumefinder_rag_eval_ids.csv")  # adjust path if needed

# 2) Normalize gold_doc_ids → list[str]
def parse_ids(x):
    if isinstance(x, list):
        return x
    if pd.isna(x):
        return []
    s = str(x).strip()
    # try JSON list, then Python literal, then comma-split
    for parser in (json.loads, ast.literal_eval):
        try:
            v = parser(s)
            return list(v) if isinstance(v, (list, tuple)) else [str(v)]
        except Exception:
            pass
    return [p.strip() for p in s.split(",") if p.strip()]

df["gold_doc_ids"] = df["gold_doc_ids"].apply(parse_ids)

# 3) Build the frame LangSmith expects:
#    inputs={} must contain your query, outputs={} your gold labels
upload_df = pd.DataFrame({
    "input": df["input"],                    # JD text
    "gold_doc_ids": df["gold_doc_ids"],     # expected parent IDs (ranked)
    "reference": df.get("reference", ""),   # optional, saved for later chat QA evals
    "notes": df.get("notes", ""),           # optional
})

client = Client()
dataset = client.upload_dataframe(
    df=upload_df,
    name="resume_chat_retrieval_v1",
    input_keys=["input"],         # what your target reads
    output_keys=["gold_doc_ids", "reference", "notes"],  # gold labels
    description="JD → expected resume parent IDs for ResumeFinder chat retrieval",
)
print("Uploaded dataset:", dataset.id)
