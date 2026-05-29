import asyncio
import time
from pathlib import Path

from pydantic_ai import Agent

from app.config import chat_model, chroma_client, embedder

summary_agent = Agent(
    chat_model,
    instructions="주어진 텍스트를 요약하고 키워드를 추출하는 도우미입니다.",
)

SUMMARY_PROMPT = """\
아래 텍스트를 1~2문장으로 요약하고, 검색에 유용한 핵심 키워드 3~5개를 추출하세요.

형식:
요약: <요약문>
키워드: <쉼표로 구분된 키워드>

텍스트:
{text}
"""

MIN_CHUNK_LENGTH = 50
MAX_RAW_TEXT_LENGTH = 5000
ADD_BATCH_SIZE = 200
SUMMARIZE_MAX_RETRIES = 3


def read_documents(docs_dir: Path) -> list[tuple[str, str]]:
    documents = []
    for file_path in sorted(docs_dir.glob("*")):
        if file_path.suffix in (".md", ".txt"):
            text = file_path.read_text(encoding="utf-8")
            documents.append((file_path.name, text))
            print(f"  읽기 완료: {file_path.name} ({len(text)}자)")
    return documents


def split_into_chunks(filename: str, text: str) -> list[dict]:
    paragraphs = text.split("\n\n")
    chunks = []
    chunk_idx = 0
    for para in paragraphs:
        para = para.strip()
        if len(para) < MIN_CHUNK_LENGTH:
            continue
        chunks.append(
            {
                "id": f"{filename}_chunk_{chunk_idx}",
                "raw_text": para[:MAX_RAW_TEXT_LENGTH],
                "source": filename,
            }
        )
        chunk_idx += 1
    return chunks


def summarize_chunk(raw_text: str) -> str | None:
    for attempt in range(SUMMARIZE_MAX_RETRIES):
        try:
            result = summary_agent.run_sync(SUMMARY_PROMPT.format(text=raw_text))
            if result.output:
                return result.output
            print(f"    요약 결과가 비어있음, 재시도 {attempt + 1}/{SUMMARIZE_MAX_RETRIES}")
        except Exception as e:
            print(f"    요약 실패: {e}, 재시도 {attempt + 1}/{SUMMARIZE_MAX_RETRIES}")
        time.sleep(1)
    return None


async def embed_summaries(summaries: list[str]) -> list[list[float]]:
    result = await embedder.embed_documents(summaries)
    return [emb for emb in result.embeddings]


def run_indexing():
    docs_dir = Path("docs")
    if not docs_dir.exists():
        print("docs/ 폴더가 없습니다.")
        return

    print("[1/5] 문서 읽기")
    documents = read_documents(docs_dir)
    if not documents:
        print("docs/ 폴더에 .md 또는 .txt 파일이 없습니다.")
        return

    print("[2/5] 단락 분할")
    all_chunks = []
    for filename, text in documents:
        chunks = split_into_chunks(filename, text)
        all_chunks.extend(chunks)
        print(f"  {filename}: {len(chunks)}개 청크")
    print(f"  총 {len(all_chunks)}개 청크")

    print("[3/5] 요약 생성 (PydanticAI Agent)")
    valid_chunks = []
    summaries = []
    for i, chunk in enumerate(all_chunks):
        summary = summarize_chunk(chunk["raw_text"])
        if summary is None:
            print(f"  청크 {chunk['id']} 요약 실패 — 건너뜀")
            continue
        chunk["summary"] = summary
        valid_chunks.append(chunk)
        summaries.append(summary)
        if (i + 1) % 5 == 0:
            print(f"  {i + 1}/{len(all_chunks)} 처리")
        time.sleep(13)
    print(f"  요약 완료: {len(summaries)}개 (건너뜀: {len(all_chunks) - len(valid_chunks)}개)")

    if not valid_chunks:
        print("유효한 청크가 없습니다. 종료합니다.")
        return

    print("[4/5] 임베딩 생성 (PydanticAI Embedder)")
    embeddings = asyncio.run(embed_summaries(summaries))
    print(f"  임베딩 완료: {len(embeddings)}개")

    print("[5/5] ChromaDB 저장")
    chroma_client.delete_collection("jarana_faq")
    collection = chroma_client.get_or_create_collection(
        name="jarana_faq",
        embedding_function=None,
    )
    for i in range(0, len(valid_chunks), ADD_BATCH_SIZE):
        batch_chunks = valid_chunks[i : i + ADD_BATCH_SIZE]
        batch_embeddings = embeddings[i : i + ADD_BATCH_SIZE]
        batch_summaries = summaries[i : i + ADD_BATCH_SIZE]
        collection.add(
            ids=[c["id"] for c in batch_chunks],
            embeddings=batch_embeddings,
            documents=batch_summaries,
            metadatas=[
                {"raw_text": c["raw_text"], "source": c["source"]}
                for c in batch_chunks
            ],
        )
    print(f"  저장 완료: {collection.count()}개 항목")
    print("인덱싱 완료!")


if __name__ == "__main__":
    run_indexing()
