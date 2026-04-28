# `app/routers/chat.py` 코드 해석

## 파일 역할

챗봇의 **유일한 HTTP 엔드포인트**를 정의하는 파일. 여기서 `POST /chat` 한 개가 열린다.

파이프라인으로 설명하면 이렇게 된다:

```
사용자 요청 (ChatRequest)
        │
        ▼
   [chat.py]  ← 이 파일 (오케스트레이터)
    │  │
    │  └─▶ llm.py    (Gemini 호출 + 세션 히스토리)
    └────▶ rag.py    (ChromaDB 검색)
        │
        ▼
사용자 응답 (ChatResponse)
```

이 파일 자체는 **로직이 거의 없다**. 대신 `rag.py` → `llm.py` 두 단계를 순서대로 호출하면서 중간에 예외를 잡아 우아한 에러 처리를 책임진다.

달리 말하면 이 파일의 역할은 **"요청을 받아 두 모듈을 순서대로 부르고 결과를 `ChatResponse`로 포장해서 돌려주는 지휘자"** 다. 다른 모듈이 직접 서로를 부르지 않고 여기서만 조립되므로, 의존성 그래프가 한 점으로 모이는 허브 역할도 한다.

### 핵심 개념: FastAPI의 APIRouter와 핸들러

FastAPI 애플리케이션은 `main.py`에 `FastAPI()` 인스턴스 하나(`app`)가 있고, 실제 엔드포인트는 이 `app`에 직접 붙이거나 **`APIRouter`** 라는 서브 라우터에 모았다가 `app.include_router(...)`로 붙이는 방식을 쓴다.

- `APIRouter`를 쓰는 이유: 엔드포인트를 기능별로 파일 분리할 수 있어서 프로젝트가 커져도 라우팅이 깔끔하게 유지된다
- 이 파일은 `router`라는 이름으로 라우터 객체를 만들고, `main.py`가 `app.include_router(router, prefix="/api")` 형태로 연결한다
- 그러면 이 파일의 `@router.post("/chat")`은 최종적으로 `POST /api/chat`이 된다

한 파일에 하나의 `APIRouter`를 두고 관련 엔드포인트만 모으는 게 FastAPI의 일반적인 관례다.

---

## Line 1: 임포트 — logging

```python
import logging
```

파이썬 표준 로깅 라이브러리. 이 파일에서 `logger = logging.getLogger(__name__)`로 모듈 전용 로거를 만들고, 아래 `except` 블록 안에서 `logger.exception(...)`으로 예외 스택 트레이스를 로그에 남기는 데 쓴다.

`print` 대신 `logging`을 쓰는 이유:
- 레벨별 구분 가능 (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `EXCEPTION`)
- 타임스탬프, 스레드 ID 등 메타데이터 자동 포함
- 운영 환경에서 파일이나 수집 시스템으로 연결 가능

---

## Line 3: 임포트 — FastAPI

```python
from fastapi import APIRouter
```

FastAPI에서 **`APIRouter` 하나만** 가져온다. `FastAPI`, `HTTPException`, `Depends` 같은 다른 심볼은 이 파일에서 쓰지 않으므로 임포트하지 않는다.

### `APIRouter`가 하는 일

`FastAPI()` 인스턴스와 거의 똑같은 인터페이스를 가지지만, **최상위 앱이 아니라 라우팅만 모으는 작은 조각**이다. 핸들러 등록 방식은 앱과 동일하다:

```python
router = APIRouter()

@router.get("/health")
async def health(): ...

@router.post("/chat")
async def chat(...): ...
```

나중에 `main.py`에서 `app.include_router(router, prefix="/api")`로 이 조각을 앱에 붙이면 경로가 합쳐진다. `prefix="/api"`가 붙어 있다면 `/chat`은 `/api/chat`이 된다.

---

## Line 5-7: 임포트 — 프로젝트 내부 모듈

```python
from app.llm import generate_response
from app.models import ChatRequest, ChatResponse
from app.rag import search_relevant_context
```

이 라우터가 의존하는 **내부 모듈 3종**이다.

| 임포트 | 역할 | 관련 문서 |
|--------|------|----------|
| `generate_response` | Gemini에게 답변 생성 요청 | `06-.md` |
| `ChatRequest` | 요청 바디 스키마 | `01-models.md` |
| `ChatResponse` | 응답 바디 스키마 | `01-models.md` |
| `search_relevant_context` | RAG 검색 (ChromaDB 조회) | `05-rag.md` |

임포트 순서가 **알파벳 순**(llm → models → rag)으로 정렬된 건 우연이 아니라 isort 같은 포매터의 기본 정책이다. 일관된 정렬은 코드 리뷰 시 diff를 줄이고, 중복 임포트를 발견하기 쉽게 만든다.

### 왜 각 모듈에서 **딱 필요한 심볼만** 가져오나

예를 들어 `from app.llm import generate_response`는 `llm.py` 안의 `agent`, `_sessions`, `SYSTEM_PROMPT`, `keep_recent` 같은 내부 객체는 가져오지 않는다. 이유:

- `llm.py`가 공개하려는 API는 `generate_response` 하나뿐. 나머지는 **내부 구현 디테일**
- 다른 파일이 `agent`를 직접 건드리기 시작하면 캡슐화가 깨짐
- 모듈 간 의존이 **"공개 함수 하나"** 로만 연결되어야 나중에 내부를 바꿔도 파급이 적음

→ `chat.py`는 다른 모듈의 내부를 전혀 모른다. 오직 **"함수 하나만 호출할 줄 안다"**.

---

## Line 9: 모듈 로거 생성

```python
logger = logging.getLogger(__name__)
```

파이썬 로깅의 표준 관용구. `__name__`은 현재 모듈의 정식 이름이 자동으로 들어가는 특수 변수로, 이 파일에서는 `"app.routers.chat"`이 된다.

- 모듈마다 서로 다른 로거를 가지게 됨
- 로그 메시지 앞에 `[app.routers.chat]` 같은 식으로 출처가 찍혀 어느 파일의 로그인지 바로 보임

---

## Line 10: 라우터 인스턴스 생성

```python
router = APIRouter()
```

모듈 레벨에서 `APIRouter` 인스턴스를 **딱 하나** 만든다. 이 객체는 이 파일에서 정의하는 모든 엔드포인트를 담는 **빈 컨테이너** 역할.

### 왜 모듈 레벨 전역 변수인가

`llm.py`의 `agent`, `config.py`의 `embedder`와 같은 이유. 서버 시작 시 한 번만 만들어지고, 이후 이 파일 안에서 `@router.post(...)` 데코레이터가 이 객체에 핸들러를 **등록**한다.

### 인자 없이 생성하는 이유

`APIRouter`는 생성자에서 여러 옵션을 받을 수 있다:

```python
router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[...])
```

이 프로젝트는 **옵션을 전부 생략**하고 기본값으로만 생성한다. 이유:

- `prefix`는 `main.py`의 `include_router()` 쪽에서 `/api`로 한 번에 걸어둔다 — 여기서 또 `/chat`을 걸면 이중 경로가 된다
- `tags`, `dependencies`는 엔드포인트가 한 개뿐이라 굳이 필요 없음
- **"필요할 때만 설정, 아니면 기본값"** 이라는 전형적 YAGNI

---

## Line 13: 엔드포인트 데코레이터

```python
@router.post("/chat", response_model=ChatResponse)
```

이 한 줄이 **"함수를 HTTP 핸들러로 승격"** 시키는 부분이다. 파이썬의 데코레이터 문법.

### `@router.post("/chat")`

아래 정의된 함수를 `POST /chat` 엔드포인트로 등록한다.

| 요소 | 의미 |
|------|------|
| `@router.post` | HTTP 메서드가 `POST`라는 뜻. `@router.get`, `@router.put` 등도 있음 |
| `"/chat"` | 경로(path). 최종 URL은 `main.py`의 `include_router` 시 지정한 prefix(`/api`)와 합쳐져 `/api/chat`이 됨 |

POST를 쓰는 이유: 사용자가 입력한 메시지는 **요청 본문(body)** 에 담겨야 하고, GET에는 본문이 없는 게 관례다. 또 챗봇 요청은 서버 상태(세션 히스토리)를 바꾸는 동작이라 semantic 상 POST가 맞다.

### `response_model=ChatResponse`

FastAPI에게 **"이 엔드포인트의 응답은 `ChatResponse` 스키마를 따른다"** 고 알려주는 파라미터. 이것이 주는 이점 3가지:

1. **응답 검증**: 핸들러가 반환하는 객체가 `ChatResponse`에 맞지 않으면 FastAPI가 500 에러를 띄운다. 응답 스키마 오염 방지.
2. **응답 필터링**: 반환 객체에 `ChatResponse`에 없는 필드가 있으면 **자동으로 제거**해서 클라이언트에 내보낸다. 내부 필드가 실수로 노출되는 걸 막음.
3. **OpenAPI 문서 자동 생성**: Swagger UI(`/docs`)에 응답 스키마가 자동으로 표시된다. 프론트 개발자가 코드를 안 봐도 API 구조를 알 수 있음.

`ChatResponse`는 `01-models.md`에서 설명한 대로 `session_id`, `message` 두 필드를 가진 Pydantic 모델이다.

---

## Line 14: 핸들러 함수 시그니처

```python
async def chat(request: ChatRequest) -> ChatResponse:
```

엔드포인트의 본체. 한 조각씩 보자.

### `async def`

이 함수가 **코루틴(coroutine)** 이라는 뜻. FastAPI는 async와 sync 핸들러를 모두 지원하지만 이 프로젝트는 async를 쓴다.

이유는 아래 단계에서 전부 `await`가 필요하기 때문이다:
- `await search_relevant_context(...)` — Gemini Embedding + ChromaDB HTTP
- `await generate_response(...)` — Gemini LLM HTTP

이 두 단계는 전부 **네트워크 대기**가 있는 I/O 작업이다. async로 만들면 한 요청이 네트워크를 기다리는 동안 이벤트 루프가 **다른 요청을 받을 수 있다**. 동시 접속 처리량(throughput)이 비약적으로 올라간다.

만약 이 함수를 `def chat(...)`처럼 동기로 정의하면 FastAPI가 **별도 스레드 풀에서 돌린다**. 그래도 동작은 하지만, 내부에서 `await`를 쓸 수 없으므로 `search_relevant_context`를 호출할 수 없다. async 함수를 동기 컨텍스트에서 부르려면 `asyncio.run(...)` 같은 추가 장치가 필요해서 복잡해진다. → async로 통일하는 게 깔끔하다.

### `request: ChatRequest`

함수 파라미터. 여기서 FastAPI의 **마법** 같은 부분이 하나 나온다.

일반 파이썬이었다면 `request`는 함수 호출 시 직접 넘겨주는 인자다. 그런데 핸들러는 FastAPI가 내부에서 자동으로 호출한다. 그러면 이 파라미터는 어떻게 채워질까?

**FastAPI의 의존성 주입**: 파라미터의 타입 힌트가 Pydantic `BaseModel`(`ChatRequest`) 이면, FastAPI는 자동으로:
1. HTTP 요청 본문을 JSON으로 파싱
2. 파싱된 dict를 `ChatRequest(**data)`로 Pydantic 객체로 변환
3. 변환 과정에서 타입 검증 실패하면 422 Unprocessable Entity 자동 반환
4. 성공하면 그 객체를 `request` 파라미터에 주입

→ 개발자는 **"요청 본문 → 파이썬 객체 변환" 코드를 한 줄도 쓸 필요가 없다**. Pydantic 모델 하나로 자동 파싱 + 검증 + 문서화까지 된다.

실제로 들어오는 JSON 예시:

```json
{ "session_id": "abc-123-def", "message": "발음 점수는 어떻게 매겨지나요?" }
```

이 JSON이 파싱되어 `request.session_id`, `request.message`로 접근 가능해진다. 첫 요청이면 `session_id`가 없어서 `None`이 들어온다.

### `-> ChatResponse`

반환 타입 힌트. `response_model=ChatResponse`와 짝을 이뤄 "이 함수는 `ChatResponse`를 돌려준다"는 명시.

- 타입 체커(mypy 등)가 코드 정적 분석 시 참고
- FastAPI 내부에서도 이 힌트를 참고할 수 있음
- 런타임에는 강제하지 않음 (Python의 타입 힌트는 정보 전달용)

실제 "응답 형태 검증"은 `response_model` 쪽이 담당한다. 타입 힌트는 어디까지나 **문서화**.

---

## Line 15-19: 1단계 — RAG 검색

```python
    try:
        context_chunks = await search_relevant_context(request.message)
    except Exception:
        logger.exception("RAG 검색 실패 — 빈 컨텍스트로 진행")
        context_chunks = []
```

파이프라인의 첫 단계. 사용자 질문으로 관련 문서를 검색한다.

### `await search_relevant_context(request.message)`

`rag.py`의 유일한 공개 함수를 호출한다. 내부적으로:

1. Gemini Embedding API에 `request.message`를 보내 벡터로 변환
2. `asyncio.to_thread`로 ChromaDB에 벡터 검색 요청
3. 상위 3개 결과의 `metadatas["raw_text"]`를 리스트로 반환

자세한 동작은 `05-rag.md` 참고. 여기서는 **"사용자 질문 문자열을 주면 관련 문서 텍스트 리스트를 돌려받는다"** 정도만 알면 된다.

반환값 `context_chunks`는 `list[str]` 타입. 정상이면 길이 3짜리 리스트, 검색 결과가 없으면 빈 리스트.

### `try/except`로 감싸는 이유 — Graceful Degradation

이 부분이 이 파일에서 가장 중요한 설계 결정 중 하나다.

**문제 상황**: RAG 검색은 외부 의존성이 많다:
- Gemini Embedding API가 느려질 수 있음
- ChromaDB 서버가 잠깐 죽을 수 있음
- 네트워크가 불안정할 수 있음

이때 RAG가 실패했다고 **챗봇 전체가 500 에러를 뱉으면** 사용자 경험이 망가진다. 대신:

1. 예외를 잡아서
2. 로그에 남기고 (`logger.exception`)
3. `context_chunks = []`로 **빈 리스트**를 만들어서 계속 진행

이러면 LLM이 "참고 문서 없음" 상태로 답변을 생성한다. `llm.py`에서 정의한 `SYSTEM_PROMPT`의 **"관련 정보가 없으면 '확인 후 안내드리겠습니다' 답하라"** 규칙이 발동된다.

→ **우아한 성능 저하(graceful degradation)**: 일부 기능이 망가져도 나머지는 계속 동작. 사용자는 RAG가 실패한 줄도 모른 채 정중한 답변을 받음.

### `except Exception`을 쓰는 이유

**"RAG는 어떤 이유로 실패해도 빈 리스트로 대체"** 하는 게 정책이다. Gemini API의 새로운 예외 타입, ChromaDB의 연결 실패, 메타데이터 파싱 에러... 전부 같은 취급. 너무 좁게 잡으면 새 예외 타입이 생겼을 때 놓친다.

→ "여기서 터지는 모든 걸 복구한다"는 정책이 명확할 때는 `except Exception`이 맞다. **단, `BaseException`은 잡지 않는다** — `KeyboardInterrupt`나 `SystemExit`까지 삼키면 서버 종료가 안 된다.

### `logger.exception("RAG 검색 실패 — 빈 컨텍스트로 진행")`

`logger.error`와 비슷하지만 **현재 발생한 예외의 스택 트레이스를 자동으로 로그에 포함**시킨다. `except` 블록 안에서만 쓸 수 있다.

운영자가 로그를 보면:
```
ERROR app.routers.chat: RAG 검색 실패 — 빈 컨텍스트로 진행
Traceback (most recent call last):
  File "app/rag.py", line 7, in search_relevant_context
    result = await embedder.embed_query(query)
  ...
httpx.ConnectTimeout: timed out
```

→ 원인 파악이 바로 된다.

---

## Line 21-31: 2단계 — LLM 호출 (+ 치명적 실패 복구)

```python
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
```

파이프라인의 두 번째 단계. Gemini에게 답변을 만들어달라고 요청한다.

### `await generate_response(...)`

`llm.py`의 핵심 함수 호출. 인자 3개를 순서대로 넘긴다:

| 인자 | 값 | 의미 |
|------|-----|------|
| 첫 번째 | `request.session_id` | 세션 ID (첫 요청이면 `None`) |
| 두 번째 | `context_chunks` | 1단계에서 받은 RAG 결과 (실패 시 빈 리스트) |
| 세 번째 | `request.message` | 사용자 질문 원문 |

`generate_response`가 내부에서 하는 일은 `06-.md`에 상세히 설명돼 있다. 요약하면:
1. 세션 ID 결정 (없으면 새 UUID 발급)
2. 이전 대화 히스토리 로드 (`TTLCache`에서)
3. 프롬프트 조립 (`[참고 문서]` + `[사용자 질문]`)
4. PydanticAI Agent로 Gemini 호출
5. 새 히스토리 저장
6. `(sid, output)` 튜플 반환

### 튜플 언패킹 `session_id, raw_response = ...`

파이썬의 **튜플 언패킹** 문법. 함수가 `(sid, output)` 2튜플을 반환하면, 이 한 줄로 두 변수에 각각 대입할 수 있다.

```python
# 이 두 줄은 같음
session_id, raw_response = await generate_response(...)
# vs
_tuple = await generate_response(...)
session_id = _tuple[0]
raw_response = _tuple[1]
```

언패킹 쪽이 훨씬 읽기 쉽고 실수도 줄어든다. 파이썬에서 여러 값을 반환할 때 자주 쓰는 관용구.

두 변수의 의미:
- **`session_id`** — 이번 요청에서 사용된 세션 ID. 첫 요청이면 새로 만든 UUID, 아니면 받은 그대로. 응답에 넣어 프론트에 돌려줘야 함.
- **`raw_response`** — LLM이 생성한 답변 텍스트. 그대로 `ChatResponse.message`로 전달된다.

### 왜 LLM 실패는 RAG 실패와 다르게 처리하나

여기서 이 파일의 설계가 흥미로워진다. RAG는 실패해도 빈 리스트로 계속 진행했는데, LLM은 실패하면 **거기서 바로 종료**하고 에러 메시지를 반환한다. 이유:

| 단계 | 실패 시 | 이유 |
|------|---------|------|
| RAG | 빈 컨텍스트로 진행 | LLM이 대체 답변 가능 ("확인 후 안내...") |
| LLM | 함수 종료, 에러 응답 | **답변을 만들 방법이 없음**. LLM 없이는 응답 생성 불가 |

→ RAG는 **보조 장치**, LLM은 **핵심 장치**. 보조 장치는 없어도 동작, 핵심 장치는 없으면 중단. 이 구분이 `try/except` 두 개의 차이로 드러난다.

### `return ChatResponse(...)` — 함수 중단

`try/except` 블록 안의 `return`이 실행되면 **함수가 여기서 끝난다**.

- `session_id=request.session_id or ""` — 세션 ID는 LLM이 생성해주는데, LLM이 실패했으므로 받은 `request.session_id`를 그대로 돌려주거나, 그것도 `None`이면 빈 문자열 `""`
  - `request.session_id`가 `None`일 수 있는데 `ChatResponse.session_id`는 `str`로 정의돼 있어서 `None`을 넣으면 Pydantic이 422 에러. 그래서 `or ""` 안전장치
- `message="죄송합니다. 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요."` — 사용자에게 보여줄 **친절한 에러 메시지**. "500 Internal Server Error" 같은 기술적 문구가 아님

### 왜 HTTPException을 던지지 않나

FastAPI에서 에러 응답을 낼 때는 흔히 `raise HTTPException(status_code=500, detail="...")`을 쓴다. 이 파일은 일부러 그렇게 하지 **않고** `ChatResponse`를 반환한다.

이유:
- HTTPException은 **HTTP 500** 응답이 된다. 프론트의 네트워크 계층이 "서버 에러"로 인식
- `ChatResponse`를 반환하면 **HTTP 200 + 에러 메시지가 담긴 정상 응답**. 프론트는 평소와 같은 형식으로 메시지를 받아서 그냥 채팅창에 표시만 하면 됨

→ 프론트 코드가 **에러 분기 처리를 따로 할 필요가 없다**. "챗봇의 한 메시지"로 에러도 표시됨. 사용자 경험이 더 자연스럽다.

단점도 있다: 모니터링 시스템이 "HTTP 500"을 기반으로 에러율을 측정하면 이 실패는 집계되지 않는다. 운영 관점에서는 로그(`logger.exception`)를 같이 보고 별도 메트릭(예: "에러 메시지 응답 비율")을 추적하는 방식으로 커버해야 한다.

---

## Line 33-36: 최종 응답 조립

```python
    return ChatResponse(
        session_id=session_id,
        message=raw_response.strip(),
    )
```

지금까지 모은 값을 `ChatResponse` 객체로 포장해서 반환.

### 각 필드의 출처

| 필드 | 출처 | 의미 |
|------|------|------|
| `session_id` | `generate_response` 반환값 | 세션 ID (첫 요청이면 새 UUID) |
| `message` | `generate_response` 반환값 (`.strip()` 적용) | LLM이 생성한 답변 텍스트 |

이 파일에서 새로 생성하거나 가공하는 것은 거의 없다 (`.strip()` 정도). 이게 이 파일이 "오케스트레이터"이자 "데이터 흐름의 지휘자"라는 증거다.

### Pydantic 모델 인스턴스 생성

`ChatResponse(...)`로 객체를 만들면 Pydantic이 자동으로:

1. 각 필드가 정의된 타입(`str`, `str`)에 맞는지 검증
2. 맞지 않으면 `ValidationError` 발생
3. 맞으면 인스턴스 생성

이 객체를 `return`하면 FastAPI가 받아서:
1. `response_model=ChatResponse`에 정의된 스키마에 한 번 더 검증 (위 검증과 중복이지만 이중 안전장치)
2. `model_dump()`로 dict로 변환
3. JSON으로 직렬화
4. `Content-Type: application/json` 헤더를 붙여 HTTP 응답 전송

개발자는 객체 하나만 돌려주면 끝. **"JSON 직렬화" 코드를 쓸 필요가 없다**. FastAPI + Pydantic 조합의 대표적 이점.

### 실제 응답 JSON 예시

```json
{
  "session_id": "abc-123-def",
  "message": "발음 점수는 정확도, 유창성, 억양 세 항목으로 평가됩니다..."
}
```

`01-models.md`의 `ChatResponse` 섹션에 나온 예시와 동일하다.

---

## 이 파일이 다른 파일에서 어떻게 쓰이나

`main.py`가 이 파일의 `router`를 FastAPI 앱에 연결한다. 대략 이런 모습:

```python
# app/main.py (대략)
from fastapi import FastAPI
from app.routers import chat

app = FastAPI(title="Jarana Chatbot")
app.include_router(chat.router, prefix="/api")
```

- `chat.router` — 이 파일에서 만든 `APIRouter` 인스턴스
- `prefix="/api"` — 이 라우터의 모든 경로 앞에 `/api`를 붙임
- 결과: 이 파일의 `@router.post("/chat")`은 최종적으로 `POST /api/chat`

→ 클라이언트가 `POST http://localhost:8080/api/chat`으로 요청을 보내면 `chat()` 함수가 실행된다.

### 반대 방향으로는 아무도 이 파일을 직접 import하지 않는다

`rag.py`, `llm.py`는 이 파일이 import해서 쓰는 쪽이지, 반대가 아니다. 유일하게 이 파일을 import하는 건 `main.py`의 `from app.routers import chat` 한 줄뿐이다.

→ 의존성 그래프가 일방향이다. **`chat.py`가 다른 모듈을 부르지만, 다른 모듈은 `chat.py`를 모른다**. 이게 깔끔한 계층 구조.

---

## 실행 순서 / 호출 시점

### 서버 시작 시 (한 번만)

1. `main.py`가 `from app.routers import chat` 실행
2. 파이썬이 `chat.py`를 최초 로드하면서 **모듈 레벨 코드를 순서대로 실행**:
   - Line 1-7: import (`rag.py`, `llm.py`, `models.py`도 여기서 체이닝 로드됨)
   - Line 9: `logger = logging.getLogger(__name__)` → 모듈 로거 생성
   - Line 10: `router = APIRouter()` → 빈 라우터 생성
   - Line 13-36: `@router.post("/chat")` 데코레이터가 `chat` 함수를 라우터에 **등록** (실행은 아직)
3. `main.py`가 `app.include_router(chat.router, prefix="/api")` 실행 → FastAPI 앱에 `/api/chat` 경로 등록 완료

이 시점부터 `POST /api/chat`이 활성화된다. 함수는 **정의만 된 상태**지 아직 한 번도 실행되지 않았다.

### 매 사용자 요청 시 (반복)

1. 클라이언트가 `POST /api/chat` 요청 전송 (JSON 바디 포함)
2. FastAPI가 JSON 파싱 → `ChatRequest(**data)` 객체 생성 → 타입 검증
3. 검증 성공 시 `chat(request=<ChatRequest 객체>)` 호출
4. **1단계 RAG**: `await search_relevant_context(request.message)`
   - `rag.py` 진입 → Gemini Embedding → ChromaDB 검색 → 결과 리스트 반환
   - 예외 시 `logger.exception` + `context_chunks = []`로 복구
5. **2단계 LLM**: `await generate_response(request.session_id, context_chunks, request.message)`
   - `llm.py` 진입 → 세션 ID 결정 → 히스토리 로드 → 프롬프트 조립 → Gemini 호출 → 히스토리 저장
   - 예외 시 `logger.exception` + 에러 메시지 `ChatResponse` 반환하고 **함수 종료**
6. **응답 조립**: `ChatResponse(session_id=..., message=...)` 생성 후 반환
7. FastAPI가 `response_model` 검증 → JSON 직렬화 → HTTP 200 응답 전송

**총 소요 시간**: 대략 1~3초. 대부분 Gemini LLM 호출이 차지한다. RAG는 150~400ms 정도.

### 에러 경로의 조기 종료

2단계(LLM)에서만 조기 종료가 있다. 아래 표로 정리:

| 단계 | 실패 시 동작 | 사용자가 받는 응답 |
|------|-------------|------------------|
| 1 (RAG) | `context_chunks = []`로 대체, 계속 진행 | 정상 답변 (LLM이 "확인 후 안내" 응답) |
| 2 (LLM) | **함수 종료**, 에러 메시지 반환 | "죄송합니다. 일시적인 오류가..." |

---

## 이 파일의 설계 의도 요약

| 개념 | 구현 방식 |
|------|---------|
| **오케스트레이션만 담당** | 로직 없음, 2개 모듈을 순서대로 호출하고 결과 조립만 |
| **의존성 주입** | `request: ChatRequest`만 쓰면 FastAPI가 자동으로 파싱 + 검증 + 주입 |
| **응답 스키마 고정** | `response_model=ChatResponse`로 응답 검증 + 문서 자동 생성 |
| **차등 에러 처리** | RAG는 빈 리스트로 복구, LLM은 에러 메시지로 조기 종료 |
| **Graceful Degradation** | RAG 실패해도 챗봇은 계속 동작 |
| **사용자 친화 에러** | `HTTPException` 대신 `ChatResponse`로 정상 응답처럼 에러 전달 |
| **공개 API만 의존** | 다른 모듈의 내부 객체는 건드리지 않음 (`generate_response` 같은 최소 심볼만 import) |

---

## 핵심 정리

`chat.py`는 **"챗봇 파이프라인의 지휘자"** 다. 이 파일이 하는 일은 2단계 조립이다:

```
1. RAG 검색  (rag.py.search_relevant_context)
2. LLM 호출  (llm.py.generate_response)
```

코드가 짧지만 다음 4가지 결정이 담겨 있다:

1. **차등 에러 처리** — RAG 실패는 복구, LLM 실패는 조기 종료. 보조 장치와 핵심 장치의 구분.

2. **에러도 정상 응답 형태로** — `HTTPException` 대신 `ChatResponse`를 돌려줘서 프론트가 에러 분기 없이 한 가지 방식으로 메시지를 표시.

3. **모듈 간 경계를 공개 함수로만 연결** — 다른 파일의 내부 객체(`agent`, `_sessions`, `SYSTEM_PROMPT`)는 건드리지 않고 `generate_response` 같은 공개 심볼만 import.

4. **FastAPI의 자동화 기능 최대 활용** — `request: ChatRequest` 한 줄로 파싱/검증/주입이 끝나고, `response_model=ChatResponse`로 응답 검증/문서화가 자동. 개발자가 쓸 코드가 거의 없다.

이 파일을 이해하면 챗봇의 **요청 한 건이 어느 모듈을 어떤 순서로 거쳐 응답이 되는지** 그림이 완성된다. `05-rag.md`, `06-.md` 두 문서를 이 파일이 하나의 흐름으로 엮어준다.
