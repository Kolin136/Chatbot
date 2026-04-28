# Jarana Chatbot - V1 구현 계획 (완료, 테스트 검증용)

> 이 계획은 google-genai SDK 직접 호출 방식으로 구현 완료된 상태.
> PydanticAI 전환 전 테스트 검증 참고용으로 보존.
>
> **⚠️ Spring 연동은 이후 제거되었습니다.** 본 문서에 등장하는 `post_reporter.py`, `[POST_REPORT]` 마커, `SpringPostPayload`, `SPRING_API_URL`, `report_submitted` 필드는 모두 현재 코드베이스에 존재하지 않습니다. 현재 구조는 `project-docs/architecture/ARCHITECTURE.md` 참고.

---

## Context

영어 발음 연습 서비스의 CS 전용 AI 챗봇을 새로 구축한다. FAQ 답변(RAG)과 버그/문의 접수 두 가지 기���을 제공하며, FastAPI + Gemini 3 Flash + ChromaDB로 구성된 단순 직통 구조(에이전트 루프 없음)를 따른다. Spring 서버는 이미 별도 Docker 컨테이너로 운영 중이고, 가이드 문서(docs/)는 아직 미준비 상태라 인덱싱 스크립트 구조만 먼저 만든다.

---

## 구��� 순서 (6단계)

### Phase 1: 기반 파일

**생성 파일**: `requirements.txt`, `.env`, `.gitignore`

- `requirements.txt`: fastapi, uvicorn[standard], google-genai, chromadb, httpx, python-dotenv
- `.env`: `GOOGLE_API_KEY`, `SPRING_API_URL`, `CHROMA_HOST`, `CHROMA_PORT` (Docker 네트워크 서비스명 기반)
- `.gitignore`: `.env`, `__pycache__/`, `*.pyc`, `.venv/`

---

### Phase 2: 설정 + 모델

**생성 파일**: `app/__init__.py`, `app/config.py`, `app/models.py`

#### `app/config.py`
- python-dotenv로 `.env` 로드
- `google.genai.Client(api_key=...)` 싱글톤 생성 → LLM + Embedding 공용
- `chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)` 싱글톤 생성 → ChromaDB 서버 컨테이너에 접속
- ChromaDB 컬렉션: `get_or_create_collection(name="jarana_faq", embedding_function=None)`
  - **`embedding_function=None` 필수**: 기본 임베더(MiniLM) 비활성화. Gemini 임베딩 벡터를 직접 공급

#### `app/models.py`
- `ChatRequest`: session_id (str|None), message (str)
- `ChatResponse`: session_id (str), message (str), report_submitted (bool)
- `PostReport`: postsCategory (str), postsTitle (str), postsContent (str)
- `SpringPostPayload`: 고정값 + PostReport 동적값 병합. `from_report()` 팩토리 메서드

---

### Phase 3: 핵심 로직 모듈

**생성 파일**: `app/rag.py`, `app/llm.py`, `app/post_reporter.py`

#### `app/rag.py` — RAG 검색
- `search_relevant_context(query: str, n_results: int = 3) -> list[str]`
- Gemini Embedding으로 쿼리 임베딩 (`task_type="RETRIEVAL_QUERY"`)
- ChromaDB에 `query_embeddings=`로 검색 (기본 임베더 안 씀)
- 결과의 `metadatas["raw_text"]`에서 원본 텍스트 추출 후 반환
- 동기 함수 (ChromaDB HttpClient가 동기). FastAPI가 자��으로 스레드풀에서 실행

#### `app/llm.py` — Gemini 3 대화
- 인메모리 세션 관리: `dict[str, Chat]` (session_id → Chat 객체)
- `get_or_create_session(session_id)`: 없으면 UUID 생성 + `client.aio.chats.create()` 호출
- `generate_response(session_id, context_chunks, user_message)` → (session_id, 응답텍스트)
  - 컨텍스트 청크를 `[참고 문서]` 블록으로 조합
  - `await chat.send_message(...)` 비동기 호출
- **시스템 프롬프트** 포��� 내용:
  - CS 에이전트 역할 정의
  - 제공된 컨텍스트 기반으로만 답변 지시
  - `[POST_REPORT]` 마커 규칙: 버그→technical, 콘텐츠→contents
  - 사용자 언어에 맞춰 응답

#### `app/post_reporter.py` — 문의/버그 접수 (기존 bug_detector.py → 이름 변경)
- `process_response(llm_response: str) -> tuple[str, bool]`
- 정규식 `r'\[POST_REPORT\]\s*(\{.*?\})\s*\[/POST_REPORT\]'` (re.DOTALL)
- 마커 발견 시:
  - Pydantic `PostReport.model_validate_json()`으로 파싱
  - `SpringPostPayload.from_report()`로 전체 바디 구성
  - `httpx.AsyncClient`로 Spring API POST 비동기 호출
  - 마커 제거한 깔끔한 텍스트 반환
- 마커 없으면: 원문 그대로 반환
- Spring API 호출 실패해도 사용자 응답은 정상 반환 (try/except)

---

### Phase 4: API 레이어

**생성 파일**: `app/routers/__init__.py`, `app/routers/chat.py`, `app/main.py`

#### `app/routers/chat.py`
- `POST /chat` 엔드포인트, 처리 순서:
  1. `search_relevant_context(request.message)` — 항상 실행 (동기, 스레드풀)
  2. `await generate_response(request.session_id, chunks, request.message)` — 비동기
  3. `await process_response(raw_response)` — 마커 파싱 + Spring 호출
  4. `ChatResponse` 반환

#### `app/main.py`
- FastAPI 앱 생성, CORS 미들웨어 추가
- chat 라우터 `prefix="/api"` 로 마운트
- lifespan 컨텍스트 (현재는 최소한)

---

### Phase 5: 인덱싱 스크립트

**생성 파일**: `scripts/__init__.py`, `scripts/index_docs.py`, `docs/` 디렉토리

#### `scripts/index_docs.py`
- `docs/` 폴더의 .md/.txt 파일 읽기
- `\n\n` 기준 단락 분할 → Raw Chunk (50자 미만 필터링)
- 각 청크를 Gemini 3에 전달 → 요약 + 키워드 추출
- Gemini Embedding으로 요약본 임베딩 (`task_type="RETRIEVAL_DOCUMENT"`)
  - 배치 처리 (100개 단위)
- ChromaDB에 저장:
  - `embeddings`: 요약본 벡터
  - `documents`: 요약본 텍스트
  - `metadatas`: `{"raw_text": 원본, "source": 파일명}`
- 실행 전 기존 컬렉션 삭제 후 재생성 (멱등성)
- 가이드 문서 아직 미준비 → 스크립트 구조만 완성, 나중에 docs/ 추가 후 실행

---

### Phase 6: Docker

**생성 파일**: `Dockerfile`, `docker-compose.yml`

#### `Dockerfile`
- `python:3.12-slim` 기반
- 포트 8080 (Spring 8000과 충돌 방지)

#### `docker-compose.yml` — 컨테이너 2개 구성
- **chatbot 컨테이너**: FastAPI 앱 (빌드: Dockerfile)
  - 볼륨: `docs/`
  - 포트: 8080
- **chromadb 컨테이너**: `chromadb/chroma` 공식 이미지
  - 볼륨: `chroma_data/` → 컨테이너 내 `/chroma/chroma` (데이터 영속)
  - 포트: 8001 (내부 통신용, 외부 노출은 선택)
- `.env` 로드
- **Docker 네트워크**: Spring 컨테이너가 별도 Docker에서 실행 중이므로 외부 네트워크 연결 필요
  - Spring Docker 네트워크 이름을 확인 후 `networks.external`로 연결
  - `.env`의 `SPRING_API_URL`은 Spring 컨테이너 서비스명 기반 (예: `http://spring-service:8000`)
  - `.env`의 `CHROMA_HOST`는 docker-compose 서비스명 (예: `chromadb`)

---

## 품질 검증 프로세스

각 Phase 구현 완료 후 **Codex 검토**를 실행하여 코드 품질, 누락, 잠재적 버그를 점검한다.

```
Phase 완료 → Codex adversarial review → 지적사항 수정 → 다음 Phase
```

- Phase 2 완료 후: config.py, models.py 검토
- Phase 3 완료 후: rag.py, llm.py, post_reporter.py 검토
- Phase 4 완료 후: chat.py, main.py 검토 + 전체 흐름 검증
- Phase 5 완료 후: index_docs.py 검토
- Phase 6 완료 후: Dockerfile, docker-compose.yml 검토

---

## 파일 생성 순��� (의존성 기반)

```
1. requirements.txt, .env, .gitignore
2. app/__init__.py, app/config.py, app/models.py
3. app/rag.py, app/llm.py, app/post_reporter.py  (서로 독립, 병렬 가능)
4. app/routers/__init__.py, app/routers/chat.py
5. app/main.py
6. scripts/__init__.py, scripts/index_docs.py
7. Dockerfile, docker-compose.yml
```

---

## 핵심 주의사항

| 항목 | 내용 |
|------|------|
| ChromaDB 임베딩 | `embedding_function=None` 필수. 안 하면 기본 MiniLM(384차원)과 Gemini(768차원) 불일치 |
| 임베딩 task_type | 인덱싱: `RETRIEVAL_DOCUMENT`, 검색: `RETRIEVAL_QUERY` — 반드시 짝 맞출 것 |
| 세션 메모리 | 인메모리 dict → 서버 재시작 시 소멸. Stateless 설계 의도에 부합 |
| sync/async 경계 | rag.py는 동기(ChromaDB HttpClient가 동기), llm.py와 post_reporter.py는 비동기 |
| Docker 구성 | 컨테이너 2개: chatbot(FastAPI) + chromadb(서버). Spring과는 외부 네트워크로 연결 |

---

## ���증 방법

1. **Phase 2 완료 후**: `python -c "from app.config import genai_client, chroma_collection; print('OK')"` — 설정 로드 확인
2. **Phase 4 완료 후**: `uvicorn app.main:app --port 8080` → POST `/api/chat` 에 `{"message": "안녕"}` 전송 → 응답 확인 (ChromaDB 비어있어도 Gemini 직접 응답)
3. **Phase 5 완료 후**: `docs/`에 샘플 문서 추가 → `python -m scripts.index_docs` 실행 → ChromaDB에 데이터 저장 확인 → `/api/chat`으로 FAQ 질문 테스트
4. **Phase 6 완료 후**: `docker compose up --build` → 컨테이너 내에서 동일 테스트
5. **문의 접수 테스트**: "앱이 자꾸 꺼져요" 메시지 → `report_submitted: true` 확인 + Spring API 호출 로그 확인
