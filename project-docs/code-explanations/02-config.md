# `app/config.py` 코드 해석

## 파일 역할

**서버 시작 시 딱 한 번 실행되면서** 애플리케이션 전체에서 사용할 설정값(환경변수)과 **싱글톤 객체**들을 만드는 파일.

여기서 만든 객체들(`embedder`, `chroma_collection`)은 서버가 살아있는 동안 계속 재사용된다. `rag.py`, `llm.py`, `scripts/index_docs.py` 등 여러 파일이 이걸 import해서 공유한다.

### 핵심 개념: "모듈 레벨 코드"

`config.py`는 일반적인 파이썬 모듈이지만, 함수 안이 아니라 **모듈 레벨**(들여쓰기 없는 최상단)에 코드가 잔뜩 있다. 이건 **import 되는 순간 한 번만 실행**된다는 특성을 이용한 것. 다른 파일에서 `from app.config import embedder`를 호출하면 그 시점에 `config.py` 전체가 실행되면서 `embedder` 변수가 만들어진다. 이후 다른 파일에서 또 `from app.config import embedder`를 해도 이미 실행된 결과가 **캐시돼서 재사용**된다. 이게 파이썬의 자연스러운 싱글톤 패턴이다.

---

## Line 1-5: 임포트

```python
import os

import chromadb
from dotenv import load_dotenv
from pydantic_ai import Embedder
```

- **`os`** — 파이썬 표준 라이브러리. 환경변수 읽을 때 `os.environ`을 사용한다.
- **`chromadb`** — ChromaDB(벡터 DB) 파이썬 클라이언트 라이브러리.
- **`dotenv.load_dotenv`** — `.env` 파일을 읽어서 `os.environ`에 환경변수로 로드하는 함수.
- **`pydantic_ai.Embedder`** — PydanticAI가 제공하는 임베딩 클래스. 텍스트를 벡터로 변환하는 역할.

임포트 순서가 **"표준 라이브러리 → 서드파티 라이브러리"** 로 분리되어 있는 건 파이썬 스타일 가이드(PEP 8) 관례.

---

## Line 7: `.env` 파일 로드

```python
load_dotenv()
```

프로젝트 루트에 있는 `.env` 파일을 읽어서 그 안에 적힌 `KEY=VALUE` 쌍들을 `os.environ`에 주입한다.

### `.env` 파일 내용 예시

```env
GOOGLE_API_KEY=AIzaSy...
CHROMA_HOST=localhost
CHROMA_PORT=8001
```

**왜 이렇게 분리하는가**:
- 코드에 API 키 같은 민감 정보를 박아두면 git에 올라갈 수 있음
- `.env`는 `.gitignore`에 등록돼서 git에 안 올라감
- 배포 환경마다 다른 값(개발/운영)을 쉽게 바꿀 수 있음

**`load_dotenv()` 호출 시점의 중요성**:
이 줄이 **`os.environ` 접근보다 먼저** 실행되어야 한다. 아래에서 `os.environ["GOOGLE_API_KEY"]` 같은 코드가 나오는데, 그때 `.env` 값이 이미 로드돼 있어야 하기 때문. 그래서 파일 최상단에 배치.

---

## Line 9-10: 필수 환경변수 검증

```python
if "GOOGLE_API_KEY" not in os.environ:
    raise RuntimeError("GOOGLE_API_KEY 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
```

`.env`에 `GOOGLE_API_KEY`가 없으면 **서버를 시작 못하게 막는다**.

### 왜 명시적으로 체크하는가

이게 없어도 나중에 `Embedder` 객체가 Gemini API를 호출할 때 결국 에러가 나긴 한다. 하지만 그 에러 메시지는 "인증 실패" 같은 알쏭달쏭한 내용이라 원인 파악이 어렵다.

여기서 명시적으로 체크하면:
- **서버 시작 즉시** 문제를 드러냄 (Fail Fast)
- **한글 메시지**로 정확한 원인 알려줌
- 운영자가 `.env` 파일을 확인해야 한다는 것까지 지시

`RuntimeError`를 raise하면 uvicorn이 서버를 시작하지 않고 종료된다.

### 왜 `GOOGLE_API_KEY`만 체크하고 나머지는 안 하는가

다른 환경변수들(`CHROMA_HOST`, `CHROMA_PORT` 등)은 **기본값이 있어서** 없어도 동작한다. `GOOGLE_API_KEY`는 **기본값을 둘 수 없는 민감 정보**라 필수.

---

## Line 12-13: 일반 환경변수 로딩 (기본값 있음)

```python
CHROMA_HOST = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8001"))
```

### `os.environ.get()`의 두 번째 인자

`os.environ["KEY"]`는 키가 없으면 `KeyError`를 던지지만, `os.environ.get("KEY", "default")`는 키가 없으면 기본값을 반환한다. 선택적 환경변수에 적합.

### 각 변수의 의미

| 변수 | 용도 | 기본값 |
|------|------|--------|
| `CHROMA_HOST` | ChromaDB 서버 호스트 | `localhost` |
| `CHROMA_PORT` | ChromaDB 서버 포트 | `8001` (문자열 → int 변환) |

### `int()` 변환이 필요한 이유

환경변수는 **무조건 문자열**이다. `.env`에 `CHROMA_PORT=8001`이라고 써도 `os.environ.get("CHROMA_PORT")`는 `"8001"`(문자열)을 반환한다. ChromaDB 클라이언트는 포트를 정수로 요구하므로 `int()`로 변환해야 한다.

### Docker 환경에서 CHROMA_HOST가 달라지는 경우

`.env`에는 `CHROMA_HOST=localhost`로 적혀있지만, `docker-compose.yml`을 보면:

```yaml
chatbot:
  environment:
    - CHROMA_HOST=chromadb
```

**환경변수 override**로 Docker 내부에서는 `chromadb`(컨테이너 서비스명)를 쓴다. 로컬 개발에서는 `localhost`, Docker에서는 `chromadb`를 자동으로 사용하게 된다.

---

## Line 19-20: 모델 이름 설정

```python
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "google-gla:gemini-3.1-flash-lite-preview")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "google-gla:gemini-embedding-2-preview")
```

### PydanticAI 모델 이름 형식

`google-gla:gemini-3.1-flash-lite-preview` 형태의 문자열은 PydanticAI가 정한 **표준 모델 식별자**다. 형식은 `프로바이더:모델명`.

- `google-gla` — Google Generative Language API (Gemini의 공식 이름)
- `gemini-3.1-flash-lite-preview` — 실제 모델 이름 (가장 가벼운 3.1 시리즈)

이 식별자를 PydanticAI가 내부적으로 해석해서 적절한 API 클라이언트를 만든다. OpenAI를 쓰고 싶으면 `"openai:gpt-5"` 같은 형식으로 바꾸면 되고, 이론적으로는 이 한 줄만 바꿔도 백엔드 모델을 교체 가능.

### 왜 환경변수로 빼놨나

모델 이름도 환경변수로 빼놨기 때문에:
- 코드 수정 없이 `.env`만 고쳐서 다른 모델로 교체 가능
- 실험용으로 `gemini-3-flash-preview` 같은 다른 모델 돌려보기 쉬움
- 무료 티어 → 유료 티어 전환 시 코드 변경 최소화

### 모델 선택 이유 (히스토리)

- **초기**: `gemini-2.5-flash` → 무료 티어 rate limit이 너무 빡빡함 (분당 5회)
- **변경 후**: `gemini-3.1-flash-lite-preview` → 3.x 시리즈 중 가장 가볍고 한도 관대
- **임베딩**: `gemini-embedding-2-preview` → 최신 멀티모달 임베딩 모델

---

## Line 22: Embedder 싱글톤 생성

```python
embedder = Embedder(EMBEDDING_MODEL)
```

PydanticAI의 `Embedder` 객체를 만든다. 이 객체는 텍스트를 벡터로 변환하는 두 가지 메서드를 제공:
- `embedder.embed_query(text)` — 검색 쿼리용 임베딩 (`rag.py`에서 사용)
- `embedder.embed_documents(texts)` — 문서용 임베딩 (`scripts/index_docs.py`에서 사용)

### 왜 전역 변수로 만드나

`Embedder(EMBEDDING_MODEL)` 생성 시 내부적으로 Google API 클라이언트가 초기화된다. 이걸 매 요청마다 새로 만들면:
- 초기화 비용 낭비
- 메모리 낭비
- API 연결 세팅 비용 중복

서버 시작 시 한 번만 만들어놓고 모든 요청이 **같은 객체를 공유**하는 게 효율적. 이게 싱글톤 패턴의 이유.

### 내부 동작

`Embedder` 생성자는 API 키를 `os.environ["GOOGLE_API_KEY"]`에서 자동으로 읽는다. 그래서 Line 7의 `load_dotenv()`와 Line 9-10의 검증이 이 시점보다 **먼저** 실행되어야 한다 (위에서 아래로 실행되므로 자연스럽게 순서 맞음).

---

## Line 24-28: ChromaDB 연결 + 컬렉션 생성

```python
chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
chroma_collection = chroma_client.get_or_create_collection(
    name="jarana_faq",
    embedding_function=None,
)
```

### `HttpClient` vs `PersistentClient`

ChromaDB는 두 가지 동작 모드가 있다:

- **`PersistentClient`**: 로컬 파일 시스템에 데이터를 직접 쓴다. 임베디드 모드 (SQLite 같은 느낌).
- **`HttpClient`**: 별도로 실행된 ChromaDB 서버에 HTTP로 연결한다.

우리는 `HttpClient`를 쓴다. 이유는 `docker-compose.yml`에서 ChromaDB를 **별도 컨테이너**로 띄우기 때문. 챗봇 컨테이너는 HTTP로 ChromaDB 컨테이너에 접속한다.

### `host`와 `port`

`CHROMA_HOST`와 `CHROMA_PORT` 환경변수로 주소를 지정한다. 로컬 개발 시 `localhost:8001`, Docker 환경에서는 `chromadb:8000`.

### `get_or_create_collection`

ChromaDB에서 "컬렉션"은 관계형 DB의 "테이블"과 비슷한 개념이다. 이름별로 분리된 벡터 저장 공간.

- `get_or_create` — 이름이 같은 컬렉션이 이미 있으면 그걸 가져오고, 없으면 새로 만듦
- `name="jarana_faq"` — 컬렉션 이름. 이 프로젝트는 하나만 사용
- 서버를 재시작해도 컬렉션이 사라지지 않음 (ChromaDB 컨테이너의 볼륨에 영구 저장됨)

### `embedding_function=None`의 의미

**이게 핵심 포인트**다.

ChromaDB의 `create_collection` 기본 동작은 **자체 임베딩 함수(Sentence Transformers `all-MiniLM-L6-v2`)** 를 사용하는 것이다. 그러면:
- `collection.add(documents=["text"])` 호출 시 ChromaDB가 `"text"`를 자체 모델로 벡터화해서 저장
- `collection.query(query_texts=["query"])` 호출 시 ChromaDB가 `"query"`를 자체 모델로 벡터화해서 검색

하지만 우리는 **Gemini Embedding**을 쓰고 싶다. `all-MiniLM-L6-v2`는 384차원, Gemini Embedding은 768차원(혹은 그 이상). **차원이 안 맞으면 검색 자체가 불가능**하다.

`embedding_function=None`으로 설정하면 ChromaDB는 자체 임베딩을 **비활성화**하고, 대신 **우리가 미리 계산한 벡터를 직접 넣어야 한다**고 요구한다:

```python
# 올바른 사용 예시 (index_docs.py)
collection.add(
    ids=[...],
    embeddings=[[0.1, 0.2, ...], [0.3, 0.4, ...]],  # ← 미리 Gemini로 계산한 벡터
    documents=["text1", "text2"],                     # ← 원본 텍스트 (저장만)
    metadatas=[...]
)

# 검색 시 (rag.py)
collection.query(
    query_embeddings=[[0.5, 0.6, ...]],  # ← 미리 Gemini로 계산한 쿼리 벡터
    n_results=3,
)
```

→ ChromaDB는 "벡터 저장 + 유사도 검색 엔진"으로만 쓰고, 실제 임베딩은 Gemini가 담당하는 구조. 이렇게 해야 일관된 벡터 공간에서 검색이 가능하다.

### `chroma_client`도 전역 변수로 유지하는 이유

`chroma_collection`만 쓰면 될 것 같지만 `chroma_client`도 따로 노출해둔 이유는 **`scripts/index_docs.py`에서 필요**하기 때문. 인덱싱 스크립트는 기존 컬렉션을 삭제하고 새로 만드는데, 그때 클라이언트 객체가 필요하다:

```python
# index_docs.py
chroma_client.delete_collection("jarana_faq")
collection = chroma_client.get_or_create_collection(...)
```

일반 챗봇 런타임에서는 `chroma_collection`만 쓰지만, 인덱싱 때는 `chroma_client`도 필요.

---

## 이 파일이 다른 파일에서 어떻게 쓰이나

```python
# app/rag.py
from app.config import chroma_collection, embedder

async def search_relevant_context(query):
    result = await embedder.embed_query(query)
    results = await asyncio.to_thread(chroma_collection.query, ...)
```

```python
# app/llm.py
from app.config import GEMINI_MODEL

agent = Agent(GEMINI_MODEL, instructions=SYSTEM_PROMPT, ...)
```

```python
# scripts/index_docs.py
from app.config import GEMINI_MODEL, chroma_client, embedder
```

**모든 파일이 `config.py`를 import한다**. 이 한 파일이 전체 애플리케이션의 공통 기반이 된다.

---

## 실행 순서 (서버 시작 시)

1. uvicorn이 `app.main` import 시도
2. `main.py`가 `routers.chat` import
3. `chat.py`가 `rag.py`, `llm.py` import
4. 이들 중 첫 번째 파일이 `config` import 시도 → **`config.py` 실행 시작**
5. `import os, chromadb, ...` (의존성 로드)
6. `load_dotenv()` — `.env` 파일 읽어서 환경변수 주입
7. `GOOGLE_API_KEY` 존재 여부 검증 (없으면 RuntimeError로 서버 종료)
8. 환경변수들을 모듈 레벨 상수로 저장 (`CHROMA_HOST`, `CHROMA_PORT`, ...)
9. `Embedder(EMBEDDING_MODEL)` — PydanticAI 임베더 인스턴스화
10. `chromadb.HttpClient(...)` — ChromaDB 서버 연결
11. `get_or_create_collection(...)` — 컬렉션 핸들 획득
12. **`config.py` 실행 종료**, 전역 변수들이 메모리에 상주
13. 다른 파일들이 `from app.config import ...`로 이 값들을 가져다 씀

---

## 이 파일의 설계 의도 요약

| 개념 | 구현 방식 |
|------|----------|
| **설정 중앙화** | 모든 환경변수/상수를 한 곳에 모음 |
| **싱글톤 패턴** | 모듈 레벨 변수로 한 번만 초기화, 모든 파일이 공유 |
| **Fail Fast** | 필수 환경변수 없으면 서버 시작 자체를 차단 |
| **환경 유연성** | 기본값 + 환경변수 override로 로컬/운영 구분 |
| **외부 임베딩 주입** | `embedding_function=None`으로 ChromaDB 자체 임베더 끄고 Gemini 강제 |
| **책임 분리** | 설정만 담당하고 로직은 다른 파일들이 담당 |

---

## 핵심 정리

`config.py`는 **"서버 시작 시 한 번 실행돼서 전역 객체들을 만들어두는 셋업 파일"** 이다. 로직은 거의 없고, 환경변수 로드 + 클라이언트 초기화가 전부.

가장 중요한 두 가지:
1. **`embedder`, `chroma_collection`이 싱글톤**이라는 것 — 매 요청마다 새로 만드는 게 아니라 한 번 만들고 공유
2. **`embedding_function=None`의 의미** — ChromaDB의 내장 임베딩을 거부하고, Gemini Embedding을 직접 주입하는 구조

이 두 가지만 이해하면 나머지 파일들(`rag.py`, `llm.py`, `index_docs.py`)에서 `config`를 어떻게 쓰는지 자연스럽게 읽힌다.
