# 전체 코드 흐름 개요

## 이 문서의 목적

각 파일의 코드를 한 줄씩 읽기 **전에**, 사용자 요청이 들어오면 어떤 파일의 어떤 함수가 **어떤 순서로** 호출되는지 전체 흐름을 먼저 파악하기 위한 문서. 흐름을 모르고 파일만 읽으면 각 코드가 왜 존재하는지 이해하기 어렵다.

---

## 흐름 종류 3가지

| # | 흐름 | 실행 시점 |
|---|------|----------|
| 1 | **서버 시작 시** | `uvicorn` 실행 시 한 번 |
| 2 | **인덱싱 스크립트 실행 시** | `python -m scripts.index_docs` 실행 시 한 번 (사전 작업) |
| 3 | **사용자가 메시지 보낼 때** | 매 요청마다 |

---

## 1. 서버 시작 흐름 (서버 켤 때 한 번)

```bash
source .venv/bin/activate
uvicorn app.main:app --port 8080 --reload
```

### 1-1. `app/main.py` 로딩

uvicorn이 `app.main` 모듈을 import하면서 `main.py`가 실행된다. 이때 아래 한 줄 때문에 연쇄 import가 일어남:

```python
from app.routers.chat import router as chat_router
```

### 1-2. 연쇄 import 트리

```
main.py
  └─ routers/chat.py
       ├─ rag.py
       │    └─ config.py ← 여기서 진짜 일이 시작됨
       └─ llm.py
            └─ config.py (이미 로드됨, 건너뜀)
```

### 1-3. `app/config.py` 실행 (가장 먼저 끝까지 실행됨)

```python
load_dotenv()                                    # .env 파일 읽어서 환경변수 설정
embedder = Embedder(EMBEDDING_MODEL)             # PydanticAI 임베더 객체 생성 (싱글톤)
chroma_client = chromadb.HttpClient(...)         # ChromaDB 서버에 접속
chroma_collection = chroma_client.get_or_create_collection(...)  # 컬렉션 가져옴
```

→ 이 시점에 **`embedder`와 `chroma_collection`이라는 전역 객체**가 메모리에 만들어진다. 이 둘은 서버가 살아있는 동안 계속 재사용된다.

### 1-4. `app/llm.py` 실행

```python
agent = Agent(
    GEMINI_MODEL,
    instructions=SYSTEM_PROMPT,
    history_processors=[keep_recent],
)
_sessions = TTLCache(maxsize=100, ttl=1800)
```

→ **`agent` 싱글톤**과 **빈 세션 캐시**가 만들어진다.

### 1-5. `app/main.py` 마지막 부분

```python
app = FastAPI(...)
app.include_router(chat_router, prefix="/api")           # /api/chat 등록
app.mount("/static", StaticFiles(directory="front"), name="static")

@app.get("/")
async def root():
    return FileResponse("front/index.html")
```

→ FastAPI 앱 객체가 만들어지고 라우트가 등록됨. 이제 8080 포트로 들어오는 요청을 받을 준비 완료.

### 서버 시작 후 메모리에 살아있는 것들

- `embedder` (PydanticAI Embedder)
- `chroma_collection` (ChromaDB 컬렉션 핸들)
- `agent` (PydanticAI Agent)
- `_sessions` (빈 TTLCache)
- `app` (FastAPI 앱)

---

## 2. 인덱싱 스크립트 흐름 (사전 작업)

```bash
python -m scripts.index_docs
```

이건 **챗봇이 답변하기 전에 한 번만 돌리는 작업**이다. 가이드 문서를 ChromaDB에 집어넣는 과정.

### 2-1. `scripts/index_docs.py` 시작

`if __name__ == "__main__"` → `run_indexing()` 호출

### 2-2. `run_indexing()` 내부 5단계 순차 실행

**[1단계] 문서 읽기**
```python
docs_dir = Path("docs")
documents = read_documents(docs_dir)  # docs/ 폴더의 .md/.txt 파일 전부 읽음
```
- `docs/jarana_guide.txt` 같은 파일을 텍스트로 메모리에 로드

**[2단계] 단락 분할**
```python
for filename, text in documents:
    chunks = split_into_chunks(filename, text)  # \n\n 기준으로 단락 자름
```
- 가이드 문서 → 20개 단락(청크)으로 분할
- 각 청크에 ID, 원본 텍스트, 출처 파일명 부여

**[3단계] 요약 생성 — Gemini LLM 호출 (청크 개수만큼 반복)**
```python
for chunk in all_chunks:
    summary = summarize_chunk(chunk["raw_text"])
    # 내부에서 summary_agent.run_sync(...) 호출 → Gemini API
    time.sleep(13)  # rate limit 회피
```
- 20개 청크 각각을 Gemini에 보내서 1~2문장 요약 + 키워드 추출
- 13초 간격으로 호출 → 약 4분 30초 소요

**[4단계] 임베딩 생성 — Gemini Embedding 호출 (배치 1회)**
```python
embeddings = asyncio.run(embed_summaries(summaries))
# 내부에서 embedder.embed_documents(summaries) 호출 → Gemini API
```
- 20개 요약문을 한 번에 임베딩 API에 보내서 벡터로 변환
- 결과: 20개 벡터

**[5단계] ChromaDB 저장**
```python
chroma_client.delete_collection("jarana_faq")  # 기존 컬렉션 삭제
collection = chroma_client.get_or_create_collection(...)  # 새로 생성
collection.add(
    ids=[...],                # 청크 ID 20개
    embeddings=embeddings,    # 벡터 20개 ← 검색에 쓰는 것
    documents=summaries,      # 요약문 20개 ← 텍스트 백업
    metadatas=[{"raw_text": 원본, "source": 파일명}, ...]  # 원본 본문 ← 답변에 쓰는 것
)
```

### 핵심 포인트

**Summary-based Retrieval**:
- 검색은 **요약문 벡터**로 하고
- 실제 답변 생성에는 **메타데이터의 원본 본문**을 쓴다

이 작업이 끝나면 ChromaDB에 20개 항목이 저장된 상태로 남아있음. 챗봇 서버는 이걸 검색해서 사용한다.

---

## 3. 사용자가 메시지 보낼 때 흐름 (매 요청마다)

이게 핵심이다. 사용자가 채팅창에 "발음 점수는 어떻게 매겨지나요?" 입력하고 Enter 누른 순간부터 추적.

### 3-1. 프론트엔드에서 출발

**`front/app.js`의 `sendMessage()` 함수 호출**

```javascript
async function sendMessage() {
    const message = inputEl.value.trim();   // 입력창에서 메시지 가져옴

    appendMessage(message, "user");          // 화면에 내 메시지 표시
    showTyping();                            // "..." 타이핑 인디케이터 표시

    const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            session_id: getSessionId(),      // sessionStorage에서 ID 꺼냄 (없으면 null)
            message: message
        })
    });
}
```

→ HTTP POST 요청이 `/api/chat`으로 발사됨

### 3-2. FastAPI가 요청 수신 → 라우터로 전달

**`app/main.py`** 에서 `app.include_router(chat_router, prefix="/api")`로 등록한 덕에 `/api/chat` 경로가 `chat.py`로 라우팅됨.

### 3-3. `app/routers/chat.py`의 `chat()` 함수 진입

```python
@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
```

- `request: ChatRequest` ← FastAPI가 JSON 본문을 자동으로 `ChatRequest` 객체로 변환
- 이때 **`models.py`의 `ChatRequest` 클래스가 사용됨**
- 검증 자동 수행 (`message`가 없으면 422 에러)

### 3-4. 1단계 — RAG 검색 호출

```python
try:
    context_chunks = await search_relevant_context(request.message)
except Exception:
    logger.exception("RAG 검색 실패")
    context_chunks = []
```

→ **`app/rag.py`의 `search_relevant_context()` 함수**로 점프

### 3-5. `app/rag.py`의 `search_relevant_context()` 실행

```python
async def search_relevant_context(query: str, n_results: int = 3) -> list[str]:
    # ① 사용자 질문을 벡터로 변환
    result = await embedder.embed_query(query)
    query_embedding = result.embeddings[0]

    # ② ChromaDB에서 유사한 항목 검색
    results = await asyncio.to_thread(
        chroma_collection.query,
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["metadatas"],
    )

    # ③ 검색 결과의 메타데이터에서 원본 텍스트 추출
    raw_texts = []
    if results and results["metadatas"]:
        for metadata in results["metadatas"][0]:
            raw_text = metadata.get("raw_text", "")
            if raw_text:
                raw_texts.append(raw_text)

    return raw_texts
```

여기서 일어나는 일:
- **①** "발음 점수는 어떻게 매겨지나요?"를 PydanticAI Embedder로 보내 → Gemini Embedding API 호출 → 벡터(숫자 배열) 받음
- **②** 그 벡터를 ChromaDB에 보내서 "이것과 가장 비슷한 벡터 3개 찾아줘" 요청 → 인덱싱 때 저장한 20개 중 가장 유사한 3개 반환
- **③** 그 3개의 메타데이터에 저장돼 있던 **원본 텍스트**(요약 아님!)를 꺼내서 리스트로 반환

**중요 포인트**: 검색은 **요약문 벡터**로 했지만, 반환하는 건 **원본 본문**이다. 이게 Summary-based Retrieval의 핵심.

→ 결과로 `["발음 점수는 100점 만점으로...", ...]` 같은 텍스트 리스트가 `chat()` 함수로 돌아옴

### 3-6. 2단계 — LLM 응답 생성 호출

`chat.py`로 돌아와서:

```python
try:
    session_id, raw_response = await generate_response(
        request.session_id, context_chunks, request.message
    )
except Exception:
    logger.exception("LLM 호출 실패")
    return ChatResponse(...)  # 친절한 에러 메시지 반환
```

→ **`app/llm.py`의 `generate_response()` 함수**로 점프

### 3-7. `app/llm.py`의 `generate_response()` 실행

```python
async def generate_response(session_id, context_chunks, user_message):
    # ① 세션 ID 결정
    sid = session_id or str(uuid.uuid4())

    # ② 이 세션의 이전 대화 히스토리 가져옴 (복사본)
    stored_messages = list(_sessions.get(sid, []))

    # ③ LLM에 보낼 프롬프트 구성
    if context_chunks:
        context_block = "\n\n---\n\n".join(context_chunks)
        content = f"[참고 문서]\n{context_block}\n\n[사용자 질문]\n{user_message}"
    else:
        content = f"[참고 문서]\n(관련 문서 없음)\n\n[사용자 질문]\n{user_message}"

    # ④ PydanticAI Agent로 LLM 호출
    result = await agent.run(content, message_history=stored_messages)

    # ⑤ 새 히스토리 저장
    _sessions[sid] = result.all_messages()

    return sid, result.output
```

여기서 일어나는 일:
- **①** session_id가 None이면 새 UUID 생성
- **②** TTLCache에서 이 세션의 이전 대화 가져옴 (`list()`로 복사 → 캐시 원본 보호)
- **③** 프롬프트 조립:
  ```
  [참고 문서]
  발음 점수는 100점 만점으로... (RAG가 찾아온 원본)
  ---
  발음 피드백 화면에서는...
  ---
  ...

  [사용자 질문]
  발음 점수는 어떻게 매겨지나요?
  ```
- **④** PydanticAI Agent가 시스템 프롬프트 + 이전 히스토리 + 위 프롬프트를 Gemini 3에 보냄 → 답변 받음
  - 이때 시스템 프롬프트("CS 에이전트, 컨텍스트 기반 답변, 마크다운 금지 등")가 자동 적용됨
  - `history_processors=[keep_recent]`가 **내부적으로 실행**되어 10개 초과 시 잘라냄
- **⑤** 새 대화까지 포함한 전체 히스토리를 다시 캐시에 저장 (다음 요청에서 사용)

→ `chat.py`로 `(session_id, raw_response_text)` 반환

### 3-8. `chat.py`에서 응답 객체 생성 후 반환

```python
return ChatResponse(
    session_id=session_id,
    message=raw_response.strip(),
)
```

- `models.py`의 `ChatResponse` 클래스로 응답 객체 생성
- FastAPI가 자동으로 JSON으로 직렬화해서 HTTP 응답 본문에 담음

### 3-9. 프론트엔드가 응답 수신

`front/app.js`의 `sendMessage()` 안에서:

```javascript
const data = await response.json();
setSessionId(data.session_id);              // sessionStorage에 ID 저장
hideTyping();                                // 타이핑 인디케이터 숨김
appendMessage(data.message, "bot");          // 응답 메시지 화면에 추가
```

- `data.session_id` → sessionStorage에 저장 (다음 요청에 같이 보냄)
- `data.message` → 채팅 버블로 화면에 표시

**여기서 끝.**

---

## 전체 흐름 한눈 요약

```
[프론트] front/app.js sendMessage()
   ↓ POST /api/chat
[FastAPI] app/main.py 라우팅
   ↓
[라우터] app/routers/chat.py chat()
   │
   ├─ ① RAG 검색
   │   └─ app/rag.py search_relevant_context()
   │      ├─ embedder.embed_query() → Gemini Embedding API
   │      └─ chroma_collection.query() → ChromaDB 서버
   │      → 원본 텍스트 리스트 반환
   │
   ├─ ② LLM 답변 생성
   │   └─ app/llm.py generate_response()
   │      ├─ _sessions에서 이전 히스토리 꺼냄
   │      ├─ [참고 문서] + [사용자 질문] 프롬프트 조립
   │      ├─ agent.run() → Gemini 3 API
   │      │  └─ (내부) history_processors=[keep_recent] 실행 → 10개 초과 시 자름
   │      └─ 새 히스토리 _sessions에 저장
   │      → (session_id, 응답 텍스트) 반환
   │
   └─ ChatResponse 객체 생성 → JSON 직렬화 → HTTP 응답
   ↓
[프론트] front/app.js
   └─ 응답 받아서 화면에 메시지 추가
```

---

## 파일별 역할 요약

| 파일 | 역할 | 언제 실행되나 |
|------|------|-------------|
| `models.py` | 데이터의 모양만 정의 | 다른 파일들이 import해서 사용 |
| `config.py` | 서버 시작 시 한 번 실행되는 셋업, 싱글톤 객체 생성 | 모듈 import 시점 |
| `rag.py` | RAG 검색 1단계 (질문 → 원본 텍스트) | 매 요청마다 |
| `llm.py` | LLM 답변 생성 2단계 (원본 + 질문 → LLM 답변) | 매 요청마다 |
| `routers/chat.py` | RAG와 LLM 두 단계를 순서대로 조립하는 오케스트레이터 | 매 요청마다 |
| `main.py` | FastAPI 앱과 라우터를 묶어주는 진입점 | 서버 시작 시 한 번 |
| `scripts/index_docs.py` | 챗봇과 별개로 돌리는 사전 작업 (가이드 문서 → ChromaDB) | 수동 실행 |
| `front/index.html` + `style.css` + `app.js` | 채팅 UI (HTML/CSS/JS) | 브라우저에서 실행 |

---

## 이 흐름을 머릿속에 잡은 후 각 파일 읽기 순서

흐름이 잡혔으면 각 파일을 개별적으로 읽을 때 "아 이 함수가 그때 호출되는 그거구나" 하고 자연스럽게 이해된다. 권장 순서:

1. `models.py` — 데이터 형태
2. `config.py` — 어떤 라이브러리/클라이언트 쓰는지
3. `scripts/index_docs.py` — RAG 데이터 만드는 과정 (오프라인)
4. `rag.py` — 만들어진 데이터 검색
5. **`llm.py`** — 챗봇 두뇌 (가장 중요)
6. **`routers/chat.py`** — 전체 조립
7. `main.py` — 서버 진입점
8. `front/index.html` + `app.js` + `style.css` — UI
9. `Dockerfile` + `docker-compose.yml` — 인프라

**가장 시간 들여서 읽어야 할 파일 3개**: `llm.py`, `routers/chat.py`, `scripts/index_docs.py`.
