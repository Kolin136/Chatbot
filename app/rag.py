import asyncio

from app.config import chroma_collection, embedder


async def search_relevant_context(query: str, n_results: int = 3) -> list[str]:
    result = await embedder.embed_query(query)
    query_embedding = result.embeddings[0]

    results = await asyncio.to_thread(
        chroma_collection.query,
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["metadatas"],
    )

    raw_texts = []
    if results and results["metadatas"]:
        for metadata in results["metadatas"][0]:
            raw_text = metadata.get("raw_text", "")
            if raw_text:
                raw_texts.append(raw_text)

    return raw_texts
