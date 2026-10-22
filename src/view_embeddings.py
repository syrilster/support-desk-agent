import chromadb

client = chromadb.PersistentClient(path="/tmp/copilot_chroma")

print("Collections:")
for collection in client.list_collections():
    print("-", collection.name)

collection = client.get_collection("kb_docs")

data = collection.get(
    include=["embeddings", "documents", "metadatas"]
)

for i, embedding in enumerate(data["embeddings"]):
    print("=" * 80)
    print("ID:", data["ids"][i])
    print("Document:", data["documents"][i])
    print("Metadata:", data["metadatas"][i])
    print("Embedding dimensions:", len(embedding))
    print("Embedding:", embedding)