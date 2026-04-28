# `app/rag.py` 코드 해석

## 파일 역할

챗봇의 **RAG 1단계 "검색" 담당 모듈**. 사용자가 던진 질문을 받아 ChromaDB에서 가장 관련 있는 가이드 문서 원본 텍스트 N개를 찾아서 리스트로 돌려주는 게 전부다.

이 파일에는 **함수가 딱 하나**(`search_relevant_context`)밖에 없다. 짧지만 프로젝트의 핵심 개념 3가지가 전부 압축되어 있다:
1. **임베딩 기반 검색** — 질문을 숫자 벡터로 바꿔서 유사도 검색
2. **비동기(async)와 동기(sync) 혼용** — ChromaDB의 동기 API를 `asyncio.to_thread`로 감싸서 이벤트 루프를 막지 않음
3. **Summary-based Retrieval** — 검색은 "요약 벡터"로 하고 반환은 "원본 본문"으로

라우터 `chat.py`가 매 요청마다 이 함수를 호출해서 받은 텍스트 리스트를 `llm.py`에 넘긴다. 이 파일 자체는 LLM을 호출하지 않는다. 오로지 "검색만" 한다.

### 핵심 개념: RAG란?

**RAG(Retrieval-Augmented Generation)** 는 LLM이 답변을 생성할 때 "미리 저장해둔 문서에서 관련 내용을 찾아서(Retrieval)" → "그걸 LLM 프롬프트에 끼워 넣어서 생성(Generation)" 하는 패턴이다.

왜 필요한가:
- LLM은 학습 시점의 지식만 갖고 있어서 **회사 내부 문서**나 **프로젝트 특화 정보**를 모른다
- 모든 문서를 매 요청마다 프롬프트에 통째로 넣으면 토큰 낭비 + 컨텍스트 초과
- → "질문과 관련 있는 부분만" 골라서 넣어주는 게 RAG

`rag.py`는 이 중에서 **"Retrieval" 단계만** 담당한다. "Generation"은 `llm.py`에서 한다.

---

## Line 1: 임포트 — asyncio

```python
import asyncio
```

파이썬 표준 라이브러리의 `asyncio` 모듈. 비동기 작업을 다룰 때 쓴다.

이 파일에서 `asyncio`를 쓰는 이유는 딱 하나, **`asyncio.to_thread`** 함수 때문이다. 아래 함수 본문에서 자세히 설명하겠지만, ChromaDB 클라이언트가 제공하는 `query()` 메서드는 **동기(sync) 함수**라서 그대로 `await` 할 수 없다. 이걸 별도 스레드에서 돌리고 결과만 비동기로 기다리게 해주는 게 `asyncio.to_thread`다.

---

## Line 3: 임포트 — config에서 싱글톤 가져오기

```python
from app.config import chroma_collection, embedder
```

`app/config.py`에서 **이미 만들어져 있는** 두 개의 전역 객체를 가져온다.

| 이름 | 타입 | 역할 |
|------|------|------|
| `chroma_collection` | ChromaDB Collection | 벡터 저장소 핸들, 여기에 `query()`를 날려서 검색 |
| `embedder` | PydanticAI Embedder | 텍스트를 벡터로 바꾸는 객체 |

둘 다 서버 시작 시 `config.py`에서 딱 한 번 생성된 **싱글톤**이다. 이 파일은 그걸 "빌려 쓰기"만 한다. `rag.py` 안에서 새로 만들지 않는 게 포인트. 매 요청마다 새로 만들면 초기화 비용이 낭비되니까.

> 관련: `02-config.md`의 "Embedder 싱글톤 생성" 섹션과 "ChromaDB 연결 + 컬렉션 생성" 섹션에서 이 두 객체가 어떻게 만들어지는지 자세히 설명했다.

---

## Line 6: 함수 선언부

```python
async def search_relevant_context(query: str, n_results: int = 3) -> list[str]:
```

이 파일의 유일한 공개 함수. 한 줄씩 뜯어보자.

### `async def`

함수 앞에 `async`가 붙었다는 건 이 함수가 **코루틴(coroutine)** 이라는 뜻이다. 호출하면 즉시 실행되지 않고 "아직 실행 안 된 작업 객체"를 반환한다. 실제로 돌리려면 `await`로 기다려야 한다.

```python
# 호출하는 쪽 (chat.py)
context_chunks = await search_relevant_context(request.message)
```

`async def`로 만든 이유:
- 내부에서 `await embedder.embed_query(query)`를 호출해야 함 (Gemini API 네트워크 요청)
- 내부에서 `await asyncio.to_thread(...)`를 호출해야 함
- → `await`를 쓰려면 함수 자체가 `async`여야 함

FastAPI 라우터는 `async` 함수를 그대로 지원하고, 하나의 요청이 네트워크 대기를 할 때 다른 요청을 처리할 수 있게 해준다. 이게 동시 접속 처리의 핵심.

### `query: str`

첫 번째 파라미터. 사용자의 질문 텍스트. 예: `"발음 점수는 어떻게 매겨지나요?"`

타입 힌트 `: str`이 붙어 있지만 파이썬은 런타임에 강제하지는 않는다. 타입 힌트는 **코드 읽는 사람과 IDE를 위한 문서** 역할.

### `n_results: int = 3`

두 번째 파라미터. ChromaDB에서 **몇 개**의 유사 문서를 가져올지 지정. 기본값 `3`.

- 호출 쪽에서 생략하면 자동으로 3개 반환
- 실제 `chat.py`에서는 값을 명시하지 않아서 항상 3개가 나옴
- 나중에 실험할 때 5개나 10개로 바꿀 수 있게 파라미터로 뺀 것

**왜 3인가**: 너무 많으면 LLM 프롬프트가 길어지고 관련 없는 문맥이 섞여서 답변 품질이 떨어짐(노이즈). 너무 적으면 정작 필요한 정보가 안 들어감. 3~5 사이가 실무에서 흔한 타협점.

### `-> list[str]`

반환 타입 힌트. **문자열들의 리스트**를 반환한다는 뜻. 각 원소는 가이드 문서의 원본 단락 하나.

예시 반환값:
```python
[
    "발음 점수는 정확도, 유창성, 억양 세 항목을 100점 만점으로 평가합니다...",
    "발음 피드백 화면에서는 단어별로 색상이 표시됩니다...",
    "점수가 낮게 나오면 '다시 녹음' 버튼을 눌러 재시도할 수 있습니다..."
]
```

`list[str]` 표기는 Python 3.9+ 에서 가능한 **소문자 제네릭**이다. 예전 스타일 `List[str]`(typing 모듈 import 필요)과 동일한 의미.

---

## Line 7-8: 질문을 벡터로 변환 (Query Embedding)

```python
    result = await embedder.embed_query(query)
    query_embedding = result.embeddings[0]
```

함수 본문의 첫 작업. 사용자 질문 텍스트를 **숫자 벡터**로 바꾸는 과정이다.

### 임베딩(Embedding)이란?

**임베딩** 은 텍스트를 고차원 숫자 배열(벡터)로 변환하는 작업이다. 의미가 비슷한 텍스트끼리는 벡터 공간에서도 가까운 위치에 오도록 학습된 모델을 사용한다.

예시 (실제로는 768차원이지만 개념만):
```
"발음 점수는?"        → [0.12, -0.45, 0.89, ..., 0.03]   (768개 숫자)
"발음 평가 기준은?"   → [0.10, -0.42, 0.91, ..., 0.05]   (벡터가 비슷함 → 의미도 비슷)
"오늘 날씨 어때?"     → [-0.78, 0.33, -0.11, ..., 0.66]  (전혀 다른 벡터)
```

ChromaDB는 이 **벡터 간 거리**를 계산해서 "가장 가까운(=가장 유사한) 문서"를 찾아준다.

### `embedder.embed_query(query)`

`embedder`는 config.py에서 만든 PydanticAI Embedder 객체. 이 객체의 `embed_query` 메서드는:
- 내부적으로 Gemini Embedding API로 HTTP 요청을 보냄
- 요청 본문: `{"content": "발음 점수는 어떻게 매겨지나요?"}`
- 응답으로 768차원 벡터를 받아옴
- 이게 네트워크 호출이므로 **비동기 함수**로 제공됨 → `await` 필수

### `embed_query` vs `embed_documents`의 차이

PydanticAI Embedder는 두 메서드를 따로 제공한다:

| 메서드 | 용도 | 이 프로젝트의 호출 위치 |
|--------|------|------------------------|
| `embed_query(text)` | 검색 쿼리 1건 | `rag.py` (사용자 질문) |
| `embed_documents(texts)` | 저장할 문서 N건 | `scripts/index_docs.py` (인덱싱 시) |

**왜 나뉘어 있나**: Gemini 같은 임베딩 모델은 내부적으로 "이 텍스트가 질문인가 문서인가"에 따라 약간 다르게 임베딩한다. 질문은 "찾고 있는 것", 문서는 "찾아질 대상"이라 비대칭. API 파라미터로 `task_type=RETRIEVAL_QUERY`, `task_type=RETRIEVAL_DOCUMENT`를 구분해서 넘기는데, PydanticAI가 이걸 두 메서드로 추상화해준 것.

→ 질문할 때 잘못해서 `embed_documents`를 쓰면 검색 품질이 떨어질 수 있다. 주의.

### `result.embeddings[0]`

`embed_query`의 반환값은 **단일 벡터가 아니라 결과 객체**다. 그 안에 `embeddings`라는 리스트가 들어 있고, 리스트의 첫 번째(`[0]`) 원소가 우리가 원하는 벡터다.

왜 리스트 안에 들어 있냐면, PydanticAI의 `embed_query` 인터페이스가 **여러 쿼리를 한 번에 처리할 수 있도록** 설계되어 있기 때문이다. 우리는 한 건만 보냈으니 `[0]`으로 꺼낸다.

`query_embedding`은 이제 길이 768짜리 `float` 리스트다. 이게 다음 단계의 ChromaDB 검색에 쓰인다.

---

## Line 10-15: ChromaDB 벡터 검색

```python
    results = await asyncio.to_thread(
        chroma_collection.query,
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["metadatas"],
    )
```

검색의 핵심 부분. 한 줄 한 줄 뜯어야 한다.

### `asyncio.to_thread`가 왜 필요한가

이게 이 파일에서 가장 비직관적인 부분이다.

**문제 상황**:
- ChromaDB의 `chroma_collection.query(...)`는 **동기(sync) 함수**다. `await`를 붙일 수 없다.
- 하지만 이 작업은 ChromaDB 서버에 HTTP 요청을 보내고 응답을 기다리는 **블로킹(blocking) I/O** 작업이다.
- `async def` 함수 안에서 동기 블로킹 코드를 그냥 호출하면 **이벤트 루프 전체가 멈춘다**.
- 이벤트 루프가 멈추면 다른 사용자의 요청도 처리 못하고 서버가 마비된다.

**해결책**: `asyncio.to_thread(func, *args, **kwargs)`
- 받은 동기 함수(`func`)를 **별도 스레드**에서 실행시킨다
- 메인 이벤트 루프는 그 스레드가 끝날 때까지 **다른 비동기 작업을 계속 처리**할 수 있다
- 스레드가 끝나면 결과를 가져와서 `await`의 반환값으로 돌려준다
- → 동기 함수를 비동기 컨텍스트에서 "안전하게" 호출하는 표준 패턴

### 호출 형태

```python
asyncio.to_thread(
    chroma_collection.query,      # ← 첫 인자: 실행할 함수 (괄호 없이!)
    query_embeddings=[...],       # ← 두 번째부터: 그 함수에 넘길 인자들
    n_results=n_results,
    include=["metadatas"],
)
```

**핵심**: 첫 인자에 함수를 넘길 때 `chroma_collection.query()`처럼 **호출하지 않고**(괄호 없이) **함수 자체**를 넘긴다. `to_thread`가 내부에서 호출해줄 거라서.

만약 실수로 `chroma_collection.query(...)` 이렇게 괄호 붙여서 넘기면 그 자리에서 즉시 실행되어 버리고 → 이벤트 루프가 블로킹 된다 → `to_thread`의 의미 자체가 사라진다. 주의할 패턴.

### `query_embeddings=[query_embedding]`

ChromaDB `query` 메서드의 검색 파라미터. **2차원 리스트**를 요구한다는 게 포인트.

- `query_embedding`은 1차원 벡터 (`[0.12, -0.45, ...]`, 길이 768)
- `[query_embedding]`으로 감싸면 2차원 (`[[0.12, -0.45, ...]]`, shape: 1×768)
- 이유: ChromaDB는 **여러 쿼리를 한꺼번에 검색**할 수 있게 설계돼 있음. 우리는 한 건만 쓰지만 API는 리스트를 요구.

### `n_results=n_results`

"상위 몇 개를 돌려줄지" 파라미터. 함수 파라미터로 받은 값을 그대로 전달.

내부적으로 ChromaDB는:
1. 저장된 모든 벡터(인덱싱한 20개)와 쿼리 벡터 사이의 **거리(cosine distance)** 를 계산
2. 거리가 가장 가까운 순으로 정렬
3. 상위 `n_results`개를 반환

### `include=["metadatas"]` — 왜 metadatas만?

ChromaDB `query`는 반환 항목을 선택적으로 제어할 수 있다. `include` 파라미터에 원하는 키들만 리스트로 넣으면 된다.

선택 가능한 항목:
- `"embeddings"` — 검색된 문서들의 벡터 (보통 불필요, 용량 큼)
- `"metadatas"` — 저장 시 같이 넣은 부가 정보 딕셔너리 ← **우리가 원하는 것**
- `"documents"` — 저장 시 `documents=` 파라미터로 넣은 텍스트 (우리는 요약문을 넣어뒀음)
- `"distances"` — 쿼리와의 거리 값 (디버깅에 유용하지만 지금은 안 씀)

**이 프로젝트 특유의 결정**: `documents`에는 "요약문"이 저장되어 있고, `metadatas`에는 "원본 본문"이 저장되어 있다. 우리는 LLM 프롬프트에 **원본 본문**을 넣고 싶으므로 `metadatas`만 가져온다. `documents`(요약)는 가져올 필요가 없다.

이걸 이해하려면 Summary-based Retrieval 구조를 알아야 한다. 아래 설명.

### Summary-based Retrieval 구조 복습

`scripts/index_docs.py`가 인덱싱할 때 ChromaDB에 이렇게 저장했다:

```python
collection.add(
    ids=["chunk_001", ...],
    embeddings=[[0.12, ...], ...],          # ← Gemini로 만든 요약문 벡터 (검색용)
    documents=["요약문1", "요약문2", ...],   # ← 짧은 요약문 (텍스트 백업)
    metadatas=[
        {"raw_text": "원본 본문 1...", "source": "jarana_guide.txt"},
        {"raw_text": "원본 본문 2...", "source": "jarana_guide.txt"},
        ...
    ]
)
```

- **검색 키**: 요약문 벡터 → 짧고 핵심만 담겨서 의미 기반 매칭이 잘 됨 (LLM이 생성한 파생 텍스트)
- **반환할 답변 재료**: 원본 본문 → 디테일이 풍부해서 LLM이 좋은 답변 생성 가능 (원본 소스)

이 두 개를 분리한 게 "Summary-based Retrieval". 검색은 요약 벡터로, 답변은 원본 텍스트로.

→ `rag.py`에서 `include=["metadatas"]`만 쓰는 건 **"검색 결과로 원본을 꺼내 쓸 거니까 요약은 필요 없다"** 는 의미.

### 반환값 `results`의 구조

`results`는 이런 모양의 딕셔너리다:

```python
{
    "ids": [["chunk_005", "chunk_002", "chunk_011"]],  # 찾은 3개의 ID
    "metadatas": [[
        {"raw_text": "발음 점수는 100점 만점...", "source": "jarana_guide.txt"},
        {"raw_text": "발음 피드백 화면에서는...", "source": "jarana_guide.txt"},
        {"raw_text": "점수가 낮게 나오면...", "source": "jarana_guide.txt"},
    ]],
    "distances": None,       # include에 안 넣었으므로 None
    "documents": None,       # include에 안 넣었으므로 None
    "embeddings": None,      # include에 안 넣었으므로 None
}
```

**주목할 점**: `metadatas`가 2차원 리스트다. 바깥 리스트는 "쿼리별", 안쪽 리스트는 "쿼리 1건당 찾은 결과 N개". 우리는 쿼리 1건만 넣었으므로 `results["metadatas"][0]`이 실제 3개 결과가 들어있는 리스트가 된다.

이게 다음 단계에서 `results["metadatas"][0]`으로 접근하는 이유다.

---

## Line 17-22: 원본 텍스트 추출

```python
    raw_texts = []
    if results and results["metadatas"]:
        for metadata in results["metadatas"][0]:
            raw_text = metadata.get("raw_text", "")
            if raw_text:
                raw_texts.append(raw_text)
```

검색 결과에서 **원본 텍스트만** 뽑아내는 후처리 루프.

### `raw_texts = []`

빈 리스트 생성. 여기에 원본 텍스트들을 모을 예정.

### `if results and results["metadatas"]:` — 방어 코드

검색 결과가 있는지 두 단계로 체크:
1. `results` 자체가 `None`이나 빈 딕셔너리가 아닌지
2. `results["metadatas"]`가 존재하고 비어있지 않은지

**왜 이렇게 방어적인가**:
- ChromaDB 컬렉션이 비어있으면(인덱싱 안 했으면) `metadatas`가 비어있을 수 있다
- 네트워크 문제 등으로 예상치 못한 형태가 올 수도 있음
- 바로 `results["metadatas"][0]`에 접근했다가 `IndexError`가 나면 함수 전체가 터짐
- 대신 빈 리스트 `[]`를 반환하게 하면 → 호출자(`chat.py`)는 "컨텍스트 없음" 상태로 자연스럽게 처리

파이썬에서 빈 리스트 `[]`, 빈 딕셔너리 `{}`, `None`, `0` 등은 모두 **falsy**로 판정되기 때문에 `if results and results["metadatas"]:` 한 줄로 "존재 + 비어있지 않음"을 같이 검사할 수 있다.

### `for metadata in results["metadatas"][0]:`

2차원 리스트 `results["metadatas"]`의 첫 번째(유일한) 쿼리 결과를 순회한다. 각 `metadata`는 아래 같은 딕셔너리:

```python
{"raw_text": "발음 점수는 100점 만점...", "source": "jarana_guide.txt"}
```

우리가 `scripts/index_docs.py`에서 `metadatas=[{"raw_text": ..., "source": ...}, ...]` 형태로 저장했기 때문에 이런 구조로 나온다.

### `raw_text = metadata.get("raw_text", "")`

딕셔너리에서 `"raw_text"` 키의 값을 꺼낸다.

`metadata["raw_text"]`(대괄호 접근) 대신 `metadata.get("raw_text", "")`을 쓴 이유:
- 대괄호 접근은 키가 없으면 `KeyError`를 던짐
- `.get("raw_text", "")`는 키가 없으면 빈 문자열 `""`을 반환 → 예외 없음
- → 메타데이터 구조가 예상과 조금 달라도 함수가 터지지 않음 (방어 프로그래밍)

### `if raw_text: raw_texts.append(raw_text)`

빈 문자열이 아닐 때만 리스트에 추가. 빈 문자열 `""`은 falsy라서 `if raw_text:` 조건이 `False`가 되어 건너뛴다.

**왜 빈 문자열을 거르는가**: 인덱싱이 잘못됐거나 메타데이터에 `raw_text`가 누락된 케이스를 걸러낸다. 빈 문자열이 LLM 프롬프트에 들어가면 `---` 구분선 사이에 공백만 나와서 프롬프트가 지저분해진다.

---

## Line 24: 최종 반환

```python
    return raw_texts
```

지금까지 모은 원본 텍스트 리스트를 반환. 정상적인 경우 길이 3짜리 리스트. 비정상(검색 결과 없음)일 땐 빈 리스트 `[]`.

이걸 받은 `chat.py`는 바로 `llm.py`의 `generate_response()`에 넘기고, 거기서 프롬프트로 조립된다:

```
[참고 문서]
발음 점수는 100점 만점...

---

발음 피드백 화면에서는...

---

점수가 낮게 나오면...

[사용자 질문]
발음 점수는 어떻게 매겨지나요?
```

이게 최종적으로 Gemini에게 전달되는 프롬프트의 모양.

---

## 이 파일이 다른 파일에서 어떻게 쓰이나

호출하는 쪽은 오직 하나, `app/routers/chat.py`다.

```python
# app/routers/chat.py
from app.rag import search_relevant_context

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    try:
        context_chunks = await search_relevant_context(request.message)
    except Exception:
        logger.exception("RAG 검색 실패")
        context_chunks = []
    # ...
    session_id, raw_response = await generate_response(
        request.session_id, context_chunks, request.message
    )
```

주목할 점 두 가지:

### 1. `try/except`로 감싸서 호출

`rag.py` 내부에서 예외가 터져도(Gemini API 실패, ChromaDB 연결 실패 등) 챗봇 전체가 죽지 않는다. 예외가 나면 `context_chunks = []`로 빈 리스트를 넣고 계속 진행 → LLM은 "관련 문서 없음" 상태로 답변 생성 → 사용자는 일단 응답을 받음.

→ RAG가 실패해도 챗봇은 계속 동작하게 설계된 것. **우아한 성능 저하(graceful degradation)** 패턴.

### 2. 이 파일의 반환값이 그대로 `generate_response`의 `context_chunks` 파라미터가 된다

`llm.py`는 이 리스트를 받아서 `"\n\n---\n\n".join(context_chunks)`로 합친다. 그래서 `rag.py`가 어떻게 잘라서 주든 `llm.py`는 그냥 구분자로 붙이기만 함. 책임이 깔끔하게 분리됨.

---

## 실행 순서 / 호출 시점

사용자가 채팅창에 질문을 입력하는 매 요청마다 아래 순서로 실행된다:

1. 사용자가 `/api/chat`에 POST 요청 전송
2. `chat.py`의 `chat()` 함수가 요청 수신
3. `chat()` 안에서 `await search_relevant_context(request.message)` 호출
4. **`rag.py`의 `search_relevant_context()` 진입**
5. `embedder.embed_query(query)` → Gemini Embedding API에 HTTP 요청 (약 100~300ms 대기)
6. 반환된 벡터를 `query_embedding` 변수에 저장
7. `asyncio.to_thread(chroma_collection.query, ...)` 호출 → 별도 스레드에서 ChromaDB 서버에 HTTP 요청
8. ChromaDB가 상위 3개 결과 반환 (약 10~50ms)
9. `results["metadatas"][0]`을 순회하며 각 항목의 `"raw_text"` 추출
10. 원본 텍스트 리스트(`raw_texts`) 반환
11. **`rag.py` 종료**, 제어가 `chat.py`로 복귀
12. `chat.py`가 받은 리스트를 `llm.py`의 `generate_response()`에 넘김

**총 소요 시간**: 대략 150~400ms. Gemini Embedding API 호출이 대부분을 차지한다.

---

## 핵심 정리

이 파일은 짧지만 **RAG의 "R"(Retrieval)** 그 자체다. 핵심 3가지만 기억하면 된다:

1. **질문 → 벡터 → 검색** 의 흐름
   - `embedder.embed_query`로 사용자 질문을 벡터로 변환
   - `chroma_collection.query`로 유사 벡터를 찾음
   - 결과의 메타데이터에서 원본 텍스트를 꺼냄

2. **`asyncio.to_thread`로 동기 API를 비동기 컨텍스트에서 안전하게 호출**
   - ChromaDB의 `query()`는 동기 함수지만 네트워크 I/O
   - 그대로 호출하면 이벤트 루프 블로킹 → 서버 마비
   - `asyncio.to_thread`로 감싸서 별도 스레드에서 실행 + 비동기 대기

3. **Summary-based Retrieval 구현**
   - 검색은 `embeddings`(요약문 벡터)로 함
   - 답변 재료는 `metadatas["raw_text"]`(원본 본문)에서 꺼냄
   - `include=["metadatas"]`만 지정한 이유가 바로 이것

RAG의 "G"(Generation)는 여기 없다. 그건 `llm.py`가 담당한다. 이 파일의 책임은 "관련 문서 원본 텍스트를 찾아서 리스트로 돌려주는 것"까지다.
