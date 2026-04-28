# Jarana Chatbot - 아키텍처 및 파일 구조

## 디렉토리 구조

```
jarana-chatbot/
├── .dockerignore            # Docker 빌드 시 제외 파일 (.env, .venv 등)
├── .env                     # 환경변수 (API 키, 서버 주소) — git 미포함
├── .gitignore               # git 제외 대상
├── Dockerfile               # FastAPI 앱 컨테이너 이미지 (python:3.12-slim)
├── docker-compose.yml       # chatbot + chromadb 2개 컨테이너 구성
├── requirements.txt         # Python 의존성
├── PROJECT_PLAN.md          # 프로젝트 기획/요구사항 계획서
├── ARCHITECTURE.md          # 이 파일 — 구조 및 모듈 설명
├── PLAN_V1_COMPLETED.md     # V1(google-genai 직접 호출) 계획 보존본
│
├── app/                     # FastAPI 애플리케이션
│   ├── __init__.py
│   ├── config.py            # 설정 및 PydanticAI 클라이언트 초기화
│   ├── models.py            # Pydantic 데이터 모델
│   ├── rag.py               # RAG 검색 로직 (PydanticAI Embedder)
│   ├── llm.py               # PydanticAI Agent 대화 관리 + 세션 TTL
│   ├── main.py              # FastAPI 앱 엔트리포인트
│   └── routers/
│       ├── __init__.py
│       └── chat.py          # /api/chat 엔드포인트
│
├── scripts/                 # 유틸리티 스크립트
│   ├── __init__.py
│   └── index_docs.py        # RAG 인덱싱 스크립트 (1회성)
│
└── docs/                    # 가이드 문서 (RAG 소스, .md/.txt)
```

---

## 기술 스택

| 역할 | 기술 | 비고 |
|------|------|------|
| Web Framework | FastAPI | 비동기 웹서버 |
| LLM 호출 | **PydanticAI Agent** | Gemini 3 Flash 경유 |
| 임베딩 | **PydanticAI Embedder** | Gemini Embedding 경유 |
| Vector DB | ChromaDB (HttpClient) | 별도 컨테이너, 서버 모드 |
| 세션 관리 | **cachetools TTLCache** | 30분 만료, 최대 100세션 |
| HTTP Client | httpx | 비동기 HTTP (현재 직접 사용처 없음) |
| 타입 검증 | Pydantic (FastAPI 내장) | 요청/응답 모델 |

> google-genai SDK는 직접 사용하지 않음. PydanticAI가 내부적으로 호출.

---

## 모듈별 상세 설명

### `app/config.py`

애플리케이션 전체에서 사용하는 설정값과 클라이언트 싱글톤.

- **환경변수 로드**: `GOOGLE_API_KEY`, `CHROMA_HOST`, `CHROMA_PORT`, `GEMINI_MODEL`, `EMBEDDING_MODEL`
- **PydanticAI Embedder**: `Embedder(EMBEDDING_MODEL)` — 임베딩 전용 싱글톤
- **ChromaDB 클라이언트**: `chromadb.HttpClient(host, port)` — 별도 컨테이너의 ChromaDB 서버 접속
- **ChromaDB 컬렉션**: `embedding_function=None`으로 생성 (PydanticAI Embedder로 직접 공급)

**참조하는 곳**: `rag.py`, `llm.py`, `scripts/index_docs.py`

---

### `app/models.py`

Pydantic 모델 정의. 외부 의존성 없음.

| 모델 | 용도 | 필드 |
|------|------|------|
| `ChatRequest` | `/api/chat` 요청 | `session_id` (str\|None), `message` (str) |
| `ChatResponse` | `/api/chat` 응답 | `session_id` (str), `message` (str) |

---

### `app/rag.py`

ChromaDB에서 사용자 질문과 유사한 문서를 검색하여 원본 텍스트를 반환.

- **함수**: `async search_relevant_context(query, n_results=3) -> list[str]`
- **동작**:
  1. PydanticAI `Embedder.embed_query()`로 쿼리 벡터 생성
  2. ChromaDB에 `query_embeddings`로 유사도 검색
  3. 결과의 `metadatas["raw_text"]`에서 원본 텍스트 추출
- **비동기 함수** — PydanticAI Embedder가 async

**의존**: `config.py` (embedder, chroma_collection)

---

### `app/llm.py`

PydanticAI Agent로 Gemini 3 Flash와 대화하고, 세션 히스토리를 관리.

- **PydanticAI Agent**: `Agent(GEMINI_MODEL, instructions=SYSTEM_PROMPT, history_processors=[keep_recent])`
- **세션 관리**: `TTLCache(maxsize=100, ttl=1800)` — `list[ModelMessage]` 저장
  - 30분 미활동 시 자동 만료
  - 최대 100개 동시 세션
  - 서버 재시작 시 전체 소멸 (Stateless 설계 의도)
- **대화 히스토리**:
  - 첫 요청 (`message_history=[]`): Agent가 시스템 프롬프트 포함하여 새 대화 시작
  - 이후 요청 (`message_history=[기존...]`): 이전 대화 이어감, 시스템 프롬프트 재생성 안 함
  - `result.all_messages()`로 전체 히스토리를 TTLCache에 저장
- **history_processors**: `keep_recent` — 대화가 10턴 초과 시 최근 10턴만 유지 (컨텍스트 윈도우 초과 방지)
- **함수**: `async generate_response(session_id, context_chunks, user_message) -> (session_id, text)`
- **시스템 프롬프트**: CS 에이전트 역할, 컨텍스트 기반 답변 지시, 마크다운 금지

**의존**: `config.py` (GEMINI_MODEL)

---

### `app/routers/chat.py`

`/api/chat` POST 엔드포인트. 전체 흐름을 순서대로 오케스트레이션.

```
요청 수신 → ① RAG 검색 → ② LLM 답변 생성 → 응답 반환
```

1. `await search_relevant_context(message)` — PydanticAI Embedder로 비동기 검색
2. `await generate_response(session_id, chunks, message)` — PydanticAI Agent로 비동기 호출

**의존**: `rag.py`, `llm.py`, `models.py`

---

### `app/main.py`

FastAPI 앱 인스턴스 생성 및 설정.

- CORS 미들웨어 (`allow_origins=["*"]`)
- chat 라우터를 `/api` prefix로 마운트
- lifespan 컨텍스트 (현재 최소한)

---

### `scripts/index_docs.py`

RAG용 문서를 ChromaDB에 인덱싱하는 1회성 스크립트. `python -m scripts.index_docs`로 실행.

**처리 순서**:
1. `docs/` 폴더의 .md/.txt 파일 읽기
2. `\n\n` 기준 단락 분할 (50자 미만 필터링, 5000자 초과 잘림)
3. PydanticAI `Agent.run_sync()`로 각 청크 요약 + 키워드 추출 (실패 시 3회 재시도, 불가 시 스킵)
4. PydanticAI `Embedder.embed_documents()`로 요약본 벡터화
5. ChromaDB에 저장 (200개 배치): 요약본=벡터, 원본=메타데이터

**의존**: `config.py` (GEMINI_MODEL, embedder, chroma_client)

---

## 모듈 의존 관계

```
.env
 └── config.py (Embedder, ChromaDB, 환경변수)
      ├── rag.py (embedder, chroma_collection)
      ├── llm.py (GEMINI_MODEL → Agent 생성)
      └── scripts/index_docs.py (GEMINI_MODEL, embedder, chroma_client)

rag.py ────┐
llm.py ────┤
models.py ─┘
 └── routers/chat.py
      └── main.py
```

---

## Docker 구성

| 컨테이너 | 이미지 | 포트 | 역할 |
|----------|--------|------|------|
| `chatbot` | Dockerfile (python:3.12-slim) | 8080 | FastAPI 앱 |
| `chromadb` | chromadb/chroma:latest | 8001→8000 | 벡터 DB 서버 |

- `chatbot`은 `chromadb` 서비스명으로 접속 (docker-compose 내부 네트워크)
- `.env`의 `CHROMA_HOST=localhost`는 로컬 개발용, Docker에서는 `environment`로 오버라이드
- ChromaDB 헬스체크 후 chatbot 시작 (`depends_on: condition: service_healthy`)

---

## 환경변수 (.env)

| 변수 | 용도 | 기본값 |
|------|------|--------|
| `GOOGLE_API_KEY` | Gemini LLM + Embedding API 키 (필수) | 없음 |
| `CHROMA_HOST` | ChromaDB 서버 호스트 | `localhost` |
| `CHROMA_PORT` | ChromaDB 서버 포트 | `8001` |
| `GEMINI_MODEL` | LLM 모델명 (PydanticAI 형식) | `google-gla:gemini-2.5-flash` |
| `EMBEDDING_MODEL` | 임베딩 모델명 (PydanticAI 형식) | `google-gla:gemini-embedding-001` |

---

## 세션 관리 상세

### 흐름

```
1번 사용자 첫 요청 (session_id=null)
  → UUID 생성 → Agent.run(message_history=[]) → 새 대화
  → TTLCache에 all_messages() 저장
  → session_id 반환

1번 사용자 이후 요청 (session_id="aaa-111")
  → TTLCache에서 히스토리 조회 → Agent.run(message_history=기존) → 대화 이어감
  → TTLCache 업데이트

30분 미활동 → TTLCache가 자동 삭제 → 다음 요청 시 새 대화
```

### 제한

| 항목 | 값 | 설명 |
|------|-----|------|
| 최대 동시 세션 | 100 | 초과 시 LRU(가장 오래 미사용) 세션 제거 |
| 세션 만료 시간 | 30분 | 마지막 활동 후 30분 경과 시 자동 삭제 |
| 대화 길이 제한 | 10턴 | history_processors가 최근 10턴만 유지 |
| 서버 재시작 | 전체 소멸 | 인메모리 저장, Stateless 설계 의도 |
