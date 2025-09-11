import io
import os
import pickle
import hashlib
from pathlib import Path
from typing import List
import chromadb
from pypdf import PdfReader
from docx import Document as Docx
from config import CHROMA_DIR, CHROMA_COLLECTION, RESUMES_STORE_DIR, BM25_CORPUS_PATH, BM25_META_PATH, EMBED_MODEL, \
    CHUNK_SIZE, CHUNK_OVERLAP, BM25_DOCIDS_PATH
from utils_text import clean_text, tokenize, simple_metadata, extract_email, extract_phone, guess_name
from langsmith import Client

# Embedding function (you may need to adjust this based on your specific method, e.g., Ollama)
def embed_chunks(chunks: List[str]) -> List[List[float]]:
    from langchain_community.embeddings import OllamaEmbeddings
    embedder = OllamaEmbeddings(model=EMBED_MODEL)
    return embedder.embed_documents(chunks)

def chunk_text(text: str, size: int, overlap: int) -> List[str]:
    """Simple character-level chunker with overlap. No external deps."""
    text = text or ""
    n = len(text)
    if n == 0:
        return []
    size = max(1, int(size))
    overlap = max(0, int(overlap))
    if overlap >= size:
        overlap = size // 4  # guard
    chunks = []
    start = 0
    while start < n:
        end = min(n, start + size)
        chunks.append(text[start:end])
        if end == n:
            break
        start = max(0, end - overlap)
    return chunks

def save_bytes_to_store(data: bytes, filename: str):
    """Save a canonical copy to RESUMES_STORE_DIR."""
    import hashlib
    h = hashlib.sha256()
    h.update(data)
    sha256_full = h.hexdigest()
    short12 = sha256_full[:12]
    ext = Path(filename).suffix.lower()
    stem = Path(filename).stem
    stored_name = f"{stem}.{short12}{ext}"
    stored_path = os.path.join(RESUMES_STORE_DIR, stored_name)
    if not os.path.exists(stored_path):
        with open(stored_path, "wb") as f:
            f.write(data)
    return stored_path, sha256_full, short12

def read_text_from_bytes(data: bytes, filename: str) -> str:
    """Reads text from PDF, DOCX, TXT, or RTF files."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        return "".join(page.extract_text() or "" for page in reader.pages)
    elif suffix == ".docx":
        doc = Docx(io.BytesIO(data))
        return "".join(p.text for p in doc.paragraphs)
    elif suffix in {".txt", ".rtf"}:
        txt = data.decode(errors="ignore")
        if suffix == ".rtf":
            import re
            return re.sub(r"{\rtf1.*?}", "", txt, flags=re.DOTALL)
        return txt
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

def get_chroma():
    """Initialize Chroma client for persistent storage."""
    try:
        if hasattr(chromadb, "PersistentClient"):
            client = chromadb.PersistentClient(path=CHROMA_DIR)
        else:
            from chromadb.config import Settings
            client = chromadb.Client(Settings(chroma_db_impl="duckdb+parquet", persist_directory=CHROMA_DIR))
    except Exception:
        print("Failed to initialize Chroma client.")
        raise
    coll = client.get_or_create_collection(name=CHROMA_COLLECTION)
    return client, coll


def add_document_to_chroma(text: str, metadata: dict, coll, base_id: str, corpus_tokens: List[List[str]],
                           bm25_doc_ids: List[str]):
    """Add document chunks to Chroma and BM25."""
    # Break the text into smaller chunks
    chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)

    if not chunks:
        raise ValueError("No text chunks produced from document")

    # Embed the chunks
    vecs = embed_chunks(chunks)

    # Prepare metadata and document IDs
    metas = []
    ids = []

    for i, ch in enumerate(chunks):
        cid = f"{base_id}::c{i:04d}"  # Unique ID for each chunk
        m = dict(metadata or {})  # Ensure metadata is not None
        m.update({
            "parent_id": base_id,
            "chunk_index": i,
            "chunk_total": len(chunks),
            "text_len": len(ch),
        })
        metas.append(m)
        ids.append(cid)
        corpus_tokens.append(tokenize(ch))  # Tokenize chunk for BM25 indexing
        bm25_doc_ids.append(cid)  # Add chunk ID to BM25 doc IDs

    # Add the chunks, metadata, and embeddings to the Chroma collection
    coll.add(documents=chunks, metadatas=metas, ids=ids, embeddings=vecs)

def save_bm25(corpus_tokens, meta_by_id, doc_ids):
    """Save BM25 corpus, metadata, and document IDs to persistent storage."""
    with open(BM25_CORPUS_PATH, "wb") as f:
        pickle.dump(corpus_tokens, f)
    with open(BM25_META_PATH, "wb") as f:
        pickle.dump(meta_by_id, f)
    with open(BM25_DOCIDS_PATH, "wb") as f:
        pickle.dump(doc_ids, f)

def simple_metadata(text: str, default_name: str) -> dict:
    # Extract the email, phone, and name from the resume text
    email = extract_email(text)
    phone = extract_phone(text)
    name = guess_name(text, default_name)

    # Ensure that we don't have None values, replace them with empty strings
    return {
        "candidate_name": name if name else "",  # Use empty string if name is None
        "email": email if email else "",          # Use empty string if email is None
        "phone": phone if phone else "",          # Use empty string if phone is None
    }

def main(directory: str):
    """CLI to ingest resumes from the directory."""
    client, coll = get_chroma()
    corpus_tokens = []
    bm25_doc_ids = []
    meta_by_id = {}  # Collect metadata

    for root, dirs, files in os.walk(directory):
        for file in files:
            try:
                file_path = os.path.join(root, file)
                with open(file_path, "rb") as f:
                    data = f.read()

                stored_path, sha256_full, short12 = save_bytes_to_store(data, file)
                text = read_text_from_bytes(data, file)
                cleaned_text = clean_text(text)
                if not cleaned_text.strip():
                    print(f"Skipped {file}, no extractable text.")
                    continue

                metadata = simple_metadata(cleaned_text, Path(file).stem)
                base_id = f"{Path(file).stem}-{short12}"

                # Add document to Chroma and BM25
                add_document_to_chroma(cleaned_text, metadata, coll, base_id, corpus_tokens, bm25_doc_ids)

                # Store metadata
                meta_by_id[base_id] = metadata

                print(f"Added {file} to Chroma and BM25.")
            except Exception as e:
                print(f"Failed to process {file}: {e}")

    # Save BM25 artifacts
    save_bm25(corpus_tokens, meta_by_id, bm25_doc_ids)

if __name__ == "__main__":
    folder = input("Enter the folder path containing resumes: ")
    if not os.path.isdir(folder):
        print("Invalid directory path.")
    else:
        main(folder)
