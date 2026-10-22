"""Embedding-based search with chroma. Separate from keyword search."""
import os
from functools import lru_cache

import chromadb
from sentence_transformers import SentenceTransformer

from support_desk.kb import load_kb
from support_desk.kb import get_doc

CHROMA_DIR = os.getenv("CHROMA_DIR", "/tmp/copilot_chroma")
MODEL_NAME = "all-MiniLM-L6-v2"  # Small, fast, free. ~80M params.


def _chunk_doc(doc_id: str, text: str, chunk_size: int = 300, overlap: int = 50) -> list[dict]:
    """Split text into overlapping chunks with metadata."""
    chunks = []
    start = 0
    text_len = len(text)
    chunk_id = 0

    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk_text = text[start:end]
        chunks.append({
            "id": f"{doc_id}_chunk_{chunk_id}",
            "doc_id": doc_id,
            "text": chunk_text
        })
        chunk_id += 1
        start += chunk_size - overlap

    return chunks if chunks else [{"id": f"{doc_id}_chunk_0", "doc_id": doc_id, "text": text}]


@lru_cache(maxsize=1)
def _get_collection():
    """Load or create the chroma collection. Cached so we don't recreate it."""
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_or_create_collection(
        name="kb_docs",
        metadata={"hnsw:space": "cosine"}
    )

    # If collection is empty, populate it
    if collection.count() == 0:
        model = SentenceTransformer(MODEL_NAME)
        docs = load_kb()

        for doc in docs.values():
            chunks = _chunk_doc(doc.id, doc.body)
            texts = [c["text"] for c in chunks]
            ids = [c["id"] for c in chunks]
            metadatas = [{"doc_id": c["doc_id"]} for c in chunks]

            # Embed and add to collection
            embeddings = model.encode(texts, convert_to_tensor=False)
            collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )
        print(f"Indexed {len(docs)} docs into chroma at {CHROMA_DIR}")
    return collection


"""
User query
    │
    │ "How long does a bank transfer refund take?"
    ▼
Sentence Transformer
    │
    ▼
Query embedding
    │
    │ [0.12, -0.43, 0.87, ...]
    ▼
Chroma
    │
    │ Find nearest chunks
    ▼
Top chunks
    │
    ├── chunk-17 → doc-A → distance 0.05
    ├── chunk-21 → doc-A → distance 0.12
    ├── chunk-42 → doc-B → distance 0.18
    ├── chunk-55 → doc-C → distance 0.25
    └── chunk-61 → doc-B → distance 0.30
    │
    ▼
Convert distance → similarity
    │
    ├── doc-A → 0.95
    ├── doc-A → 0.88
    ├── doc-B → 0.82
    ├── doc-C → 0.75
    └── doc-B → 0.70
    │
    ▼
Deduplicate by doc_id
    │
    ├── doc-A → 0.95  ← keep best
    ├── doc-B → 0.82  ← keep best
    └── doc-C → 0.75
    │
    ▼
Sort highest → lowest
    │
    ▼
Return top `limit` documents
"""


def embed_search(query: str, limit: int = 5) -> list[tuple[str, float]]:
    """
    Search the knowledge base using semantic similarity.

    Converts the query into an embedding, retrieves matching chunks from
    Chroma, deduplicates results by document, and returns the best-scoring
    documents.
   """
    collection = _get_collection()
    model = SentenceTransformer(MODEL_NAME)

    # Convert the query into a vector embedding.
    # [0] gets the embedding because we are encoding a single query.
    query_embedding = model.encode([query], convert_to_tensor=False)[0]

    # Retrieve more chunks than needed because multiple chunks can belong
    # to the same document. We deduplicate them below.
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=limit * 2,  # Get more chunks, deduplicate to docs
        include=["documents", "distances", "metadatas"]
    )

    # Return an empty list if Chroma found no matching chunks.
    if not results["ids"] or not results["ids"][0]:
        return []

    # Store the best similarity score for each document.
    seen_docs = {}

    # Process each matching chunk along with its distance and metadata.
    for chunk_id, distance, metadata in zip(
            results["ids"][0],
            results["distances"][0],
            results["metadatas"][0]
    ):
        # A document can have multiple chunks, so use the document ID
        # from the chunk metadata to group them together.
        doc_id = metadata["doc_id"]

        # Cosine distance: lower distance means higher similarity.
        # Convert it to a similarity score where higher is better.
        score = 1 - distance

        # Keep only the best-matching chunk for each document.
        if doc_id not in seen_docs or score > seen_docs[doc_id]:
            seen_docs[doc_id] = score

    # Sort documents by similarity (highest first) and return the top results.
    return sorted(seen_docs.items(), key=lambda x: x[1], reverse=True)[:limit]


def embed_search_with_snippets(query: str, limit: int = 5) -> dict:
    """Search and return results with snippets."""
    results = embed_search(query, limit=limit)
    if not results:
        return {"error": f"No documents matched '{query}'"}

    output = {"results": []}
    for doc_id, score in results:
        doc = get_doc(doc_id)
        if doc:
            snippet = doc.body[:150] + "..." if len(doc.body) > 150 else doc.body
            output["results"].append({
                "id": doc_id,
                "title": doc.title,
                "score": round(score, 3),
                "snippet": snippet,
            })
    return output
