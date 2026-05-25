import uuid

from cachetools import TTLCache
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage

from app.config import GEMINI_MODEL

SYSTEM_PROMPT = """\
당신은 RAG 검증용 지원 에이전트입니다.

## 역할
- 반드시 [참고 문서]에 제공된 내용만 사용해 답변합니다.
- [참고 문서]에 답이 없거나 불충분하면 "해당 내용은 참고 문서에서 찾을 수 없습니다"라고만 답변하세요.
- 추측이나 외부 지식을 답변에 섞지 마세요.
- 사용자의 언어에 맞춰 응답하세요.

## 응답 형식 규칙
- 마크다운 문법을 절대 사용하지 마세요. (**, ##, -, * 등 모든 마크다운 기호 금지)
- 강조가 필요한 부분도 일반 텍스트로 작성하세요.
- 목록이 필요하면 "1. ", "2. " 같은 숫자만 사용하고 별표나 하이픈은 쓰지 마세요.
- 모든 응답은 일반 평문(plain text)으로만 작성하세요.
"""


async def keep_recent(messages: list[ModelMessage]) -> list[ModelMessage]:
    # 마지막 10개만 유지 (최근 5턴 = Req-Res 페어 5쌍)
    return messages[-10:] if len(messages) > 10 else messages


agent = Agent(
    GEMINI_MODEL,
    instructions=SYSTEM_PROMPT,
    history_processors=[keep_recent], # ← 이건 함수를 "등록"만 하는 것이지, 실제로는 Agent가 메시지를 처리할 때마다 keep_recent 함수를 호출해서 메시지 히스토리를 관리합니다.
)

_sessions: TTLCache = TTLCache(maxsize=100, ttl=1800)


async def generate_response(
    session_id: str | None,
    context_chunks: list[str],
    user_message: str,
) -> tuple[str, str]:
    sid = session_id or str(uuid.uuid4())
    stored_messages: list[ModelMessage] = list(_sessions.get(sid, []))

    if context_chunks:
        context_block = "\n\n---\n\n".join(context_chunks)
        content = f"[참고 문서]\n{context_block}\n\n[사용자 질문]\n{user_message}"
    else:
        content = f"[참고 문서]\n(관련 문서 없음)\n\n[사용자 질문]\n{user_message}"

    result = await agent.run(content, message_history=stored_messages)
    _sessions[sid] = result.all_messages()

    return sid, result.output
