from chat_retrieval_target import target
out = target({"input":"Java Full Stack, 8+ yrs, Spring Boot, React, AWS, Bangalore"})
print(out.keys(), out["pred_doc_ids"][:5], out.get("pred_names", [])[:5])
