import logging

from fastapi import APIRouter

from app.llm import generate_response
from app.models import ChatRequest, ChatResponse
from app.rag import search_relevant_context

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    try:
        context_chunks = await search_relevant_context(request.message)
    except Exception:
        logger.exception("RAG 검색 실패 — 빈 컨텍스트로 진행")
        context_chunks = []

    try:
        session_id, raw_response = await generate_response(
            request.session_id, context_chunks, request.message
        )
    except Exception:
        logger.exception("LLM 호출 실패")
        return ChatResponse(
            session_id=request.session_id or "",
            message="죄송합니다. 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
        )

    return ChatResponse(
        session_id=session_id,
        message=raw_response.strip(),
    )
