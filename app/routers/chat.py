import logging

from fastapi import APIRouter

from app.llm import generate_response
from app.models import ChatRequest, ChatResponse, ChatSource
from app.rag import RetrievedChunk, search_relevant_context
from app.retrieval import FINAL_TOP_N

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    mode = "hybrid" if request.hybrid else "dense"
    logger.info(
        "chat: collection=%s mode=%s session=%s top_n=%d",
        request.collection, mode, request.session_id or "new", FINAL_TOP_N,
    )
    retrieved: list[RetrievedChunk] = []
    if request.collection:
        try:
            retrieved = await search_relevant_context(
                request.message, request.collection,
                n_results=FINAL_TOP_N, hybrid=request.hybrid,
            )
        except Exception:
            logger.exception("RAG 검색 실패 — 빈 컨텍스트로 진행")

    context_texts = [c.text for c in retrieved]

    try:
        session_id, raw_response = await generate_response(
            request.session_id, context_texts, request.message
        )
    except Exception:
        logger.exception("LLM 호출 실패")
        return ChatResponse(
            session_id=request.session_id or "",
            answer="죄송합니다. 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
            sources=[],
        )

    sources: list[ChatSource] = [c.to_source() for c in retrieved]
    return ChatResponse(
        session_id=session_id,
        answer=raw_response.strip(),
        sources=sources,
    )
