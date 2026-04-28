# `requirements.txt` + `.env` 코드 해석

## 파일 역할

두 파일 다 **프로젝트가 돌아가기 위한 "바깥 조건"**을 기술하는 파일이다. 코드처럼 로직이 들어있지는 않지만, 이 두 파일이 없으면 `app/` 아래의 어떤 파이썬 코드도 실행되지 않는다.

- **`requirements.txt`** — 이 프로젝트가 의존하는 **파이썬 패키지 목록**. `pip install -r requirements.txt` 명령으로 가상환경에 한꺼번에 설치한다.
- **`.env`** — 코드에 박아두면 안 되는 **환경변수**(API 키, 외부 서버 주소 등)를 저장하는 파일. `app/config.py`의 `load_dotenv()`가 이걸 읽어서 `os.environ`에 주입한다.

두 파일의 관계는 이렇다:
1. `requirements.txt`로 **라이브러리**를 깔고
2. `.env`로 **실행에 필요한 값**을 공급하면
3. `app/config.py`가 그 둘을 엮어서 싱글톤 객체들을 만들고
4. 나머지 애플리케이션 코드가 돌아간다

---

# 1부. `requirements.txt`

## 파일 전체

```
fastapi
uvicorn[standard]
pydantic-ai[google]
cachetools
chromadb
httpx
python-dotenv
```

총 7줄, 7개의 패키지다. 각 줄이 패키지 하나에 대응된다.

### 버전 지정 방식에 대한 선행 설명

이 파일은 **버전을 전혀 고정하지 않았다**. `fastapi==0.115.0` 같은 표기 없이 패키지 이름만 적혀있다. 파이썬 생태계의 버전 지정 문법을 먼저 훑어두면 이 선택의 의미가 보인다:

| 문법 | 의미 | 예시 |
|------|------|------|
| `pkg` | 버전 제약 없음. 설치 시점의 최신 버전 설치 | `fastapi` |
| `pkg==1.2.3` | **정확히** 이 버전만 허용 (pin) | `fastapi==0.115.0` |
| `pkg>=1.2.0` | 이 버전 **이상** 허용 | `fastapi>=0.115.0` |
| `pkg>=1.2,<2.0` | 범위 지정 (하한 포함, 상한 제외) | `fastapi>=0.115,<0.200` |
| `pkg~=1.2.0` | compatible release. `>=1.2.0, <1.3.0`과 같음 | `fastapi~=1.2.0` |
| `pkg[extra]` | extras (부가 기능) 같이 설치 | `uvicorn[standard]` |

**이 프로젝트는 전부 "버전 제약 없음" 방식**이다. 이유와 트레이드오프:

- 장점: 최신 버전의 기능/보안 패치를 자동으로 받을 수 있음. 처음 세팅할 때 편함.
- 단점: 며칠 뒤 다시 `pip install`을 돌리면 **다른 버전**이 깔려서 "내 컴퓨터에서는 되는데 동료 컴퓨터에서는 안 되는" 상황이 생길 수 있음.

운영 단계로 넘어가면 보통 `pip freeze > requirements.lock.txt`로 실제 설치된 버전들을 스냅샷 떠서 재현성을 확보한다. 이 프로젝트는 아직 그 단계까지는 가지 않은 상태.

---

## Line 1: `fastapi`

```
fastapi
```

### 역할

HTTP API 서버를 만들기 위한 **웹 프레임워크**. 이 프로젝트의 가장 바깥 껍데기.

### 이 프로젝트에서 어디에 쓰이나

- `app/main.py`에서 `app = FastAPI(...)`로 앱 객체 생성
- `app/routers/chat.py`에서 `APIRouter()`로 라우터 만들고 `@router.post("/chat")` 데코레이터로 엔드포인트 등록
- `app/models.py`의 Pydantic 모델을 요청/응답 타입으로 연결해서 **JSON 자동 검증 + 자동 직렬화**를 공짜로 얻음

### FastAPI를 고른 이유

1. **Pydantic 통합** — FastAPI는 Pydantic을 내부에서 쓴다. `models.py`의 `ChatRequest`, `ChatResponse`가 자동으로 요청/응답 검증에 엮임. 이 프로젝트에서 PydanticAI도 쓰고 있어서 Pydantic 기반으로 스택을 통일한 것.
2. **비동기 지원** — `async def chat(...)`처럼 async 함수를 그대로 엔드포인트로 쓸 수 있음. PydanticAI Agent나 httpx처럼 **네트워크 I/O 대기 시간이 긴 작업**을 효율적으로 처리해야 해서 비동기가 필수.
3. **OpenAPI 자동 생성** — Pydantic 모델만 써놓으면 `/docs` 경로에서 Swagger UI가 공짜로 나옴.

### "async로 짠 이유" 보충

챗봇의 `/api/chat` 엔드포인트는 내부에서 세 번의 외부 호출을 한다: Gemini Embedding API → ChromaDB → Gemini LLM API. 각각 수백 ms~수 초가 걸리는 I/O 작업이다. 동기 방식이면 한 사용자 요청이 이 시간 동안 스레드를 점유해서 다른 요청이 대기한다. async로 짜면 대기 중에 다른 요청을 처리할 수 있다.

---

## Line 2: `uvicorn[standard]`

```
uvicorn[standard]
```

### 역할

FastAPI 앱을 실제로 **구동하는 ASGI 서버**. FastAPI는 "요청을 어떻게 처리할지" 정의하는 프레임워크일 뿐, 실제로 80 포트를 열고 요청을 받아주는 건 uvicorn의 일이다.

### FastAPI와의 관계 비유

- `fastapi` = 건물 설계도 + 내부 인테리어
- `uvicorn` = 전기/수도/문 설치해서 실제로 사람이 들어올 수 있게 만드는 시공 업체

두 개가 합쳐져야 실제 서버로 동작한다.

### 실행 명령

```bash
uvicorn app.main:app --port 8080 --reload
```

- `app.main:app` — `app/main.py` 파일 안의 `app`이라는 이름의 FastAPI 객체를 찾아서 구동하라는 뜻
- `--port 8080` — 8080 포트에서 리스닝
- `--reload` — 파일 변경 감지해서 자동 재시작 (개발용)

### `[standard]` extras의 의미

대괄호 안의 `standard`는 **extras**라고 부르는 옵션 의존성 그룹이다. uvicorn 자체는 최소 기능만으로도 돌릴 수 있는데, `[standard]`를 붙이면 권장 부가 패키지들이 같이 설치된다:

| 부가 패키지 | 역할 |
|------------|------|
| `httptools` | HTTP 파싱 고속화 (C 구현) |
| `uvloop` | asyncio 이벤트 루프 고속화 (macOS/Linux 한정) |
| `watchfiles` | `--reload` 동작에 필요한 파일 변경 감지 |
| `websockets` | WebSocket 프로토콜 지원 |
| `python-dotenv` | (이미 별도로 설치하긴 함) |

쉽게 말해 **"uvicorn을 제대로 쓰려면 어차피 필요한 것들"**을 한 번에 깔아주는 묶음이다. `[standard]` 없이 `uvicorn`만 설치하면 `--reload`가 동작하지 않거나 성능이 떨어질 수 있다.

### extras 문법 일반화

`패키지[옵션이름]` 형식은 pip의 표준 문법이다. 아래 `pydantic-ai[google]`도 같은 패턴.

---

## Line 3: `pydantic-ai[google]`

```
pydantic-ai[google]
```

### 역할

이 프로젝트의 **두뇌**에 해당하는 LLM 오케스트레이션 라이브러리. Pydantic 팀이 만든 공식 라이브러리로, LLM 호출을 Pydantic 스타일로 다룰 수 있게 해준다.

### 이 프로젝트에서 어디에 쓰이나

두 가지 용도로 쓰인다:

1. **`Agent` 클래스** — LLM 호출을 감싸는 객체
   - `app/llm.py`에서 `agent = Agent(GEMINI_MODEL, instructions=SYSTEM_PROMPT, ...)`로 생성
   - `agent.run(user_message, message_history=...)`로 호출
   - 시스템 프롬프트, 히스토리 프로세서, 출력 구조 등을 모두 관리

2. **`Embedder` 클래스** — 텍스트를 벡터로 변환
   - `app/config.py`에서 `embedder = Embedder(EMBEDDING_MODEL)`로 생성
   - `embedder.embed_query(text)` — 검색 쿼리용
   - `embedder.embed_documents(texts)` — 문서용 (배치)

### `[google]` extras의 의미

PydanticAI는 **여러 LLM 프로바이더를 지원**한다. OpenAI, Anthropic, Google, Groq, Mistral 등. 기본 설치만으로는 프로바이더별 SDK가 같이 깔리지 않고, 쓸 프로바이더를 extras로 명시해야 한다.

| extras | 설치되는 프로바이더 SDK |
|--------|------------------------|
| `pydantic-ai[openai]` | OpenAI |
| `pydantic-ai[anthropic]` | Anthropic |
| `pydantic-ai[google]` | Google Gemini (google-genai SDK) |
| `pydantic-ai[groq]` | Groq |

이 프로젝트는 Gemini를 쓰기 때문에 `[google]`만 필요하다. 이렇게 extras로 분리하면:
- 안 쓰는 프로바이더의 SDK가 설치되지 않아 설치 용량이 줄어듦
- 불필요한 API 키 경고도 안 뜸

나중에 OpenAI로 갈아탈 일이 생기면 `pydantic-ai[google,openai]`처럼 쉼표로 추가하면 된다.

### PydanticAI를 쓴 이유

- `models.py`, FastAPI와 같은 Pydantic 기반으로 **스택 통일**
- Agent 추상화가 깔끔함 (system prompt, history processor, tool calling을 모두 내장)
- `history_processors=[keep_recent]`처럼 히스토리 관리 로직을 주입할 수 있는 설계
- 전체 흐름 문서에서 설명된 대로, `agent.run()` 한 방으로 시스템 프롬프트 + 히스토리 + 사용자 메시지를 묶어서 Gemini에 보낼 수 있음

---

## Line 4: `cachetools`

```
cachetools
```

### 역할

파이썬 표준 라이브러리에 없는 **TTL(Time-To-Live) 캐시**를 제공하는 외부 라이브러리.

### 이 프로젝트에서 어디에 쓰이나

`app/llm.py`에서 **세션 기반 대화 히스토리**를 메모리에 잠깐 저장하는 데 쓴다:

```python
from cachetools import TTLCache
_sessions = TTLCache(maxsize=100, ttl=1800)
```

- `maxsize=100` — 최대 100개 세션까지만 저장 (초과 시 오래된 것부터 자동 삭제)
- `ttl=1800` — 마지막 접근으로부터 1800초(30분) 지나면 자동 만료

### 왜 파이썬 표준 `functools.lru_cache`를 안 쓰는가

`functools`의 `lru_cache`는 **함수 결과 캐시**라서 "인자로 함수를 호출하면 결과를 기억해준다"는 패턴이다. 반면 이 프로젝트는 **딕셔너리처럼 쓸 수 있는 캐시**가 필요하다:

```python
_sessions[session_id] = messages      # 쓰기
history = _sessions.get(session_id, [])  # 읽기
```

`cachetools.TTLCache`는 딕셔너리 인터페이스(`__getitem__`, `__setitem__`)를 제공하면서 **시간 만료 + 크기 제한**을 자동으로 처리해준다. 표준 라이브러리에는 이걸 대체할 물건이 없어서 외부 의존성으로 추가한 것.

### 왜 Redis 같은 외부 스토리지가 아닌가

- **MVP 단계**에서는 단일 서버 프로세스의 메모리로 충분
- Redis를 쓰면 인프라 구성이 복잡해짐 (Docker 컨테이너 하나 더)
- 세션 데이터가 휘발돼도 치명적이지 않음 (30분 지나면 어차피 만료)
- 다중 서버로 스케일아웃 하게 되면 그때 Redis로 교체 고려

### 주의: 이 캐시는 서버 재시작 시 사라진다

`TTLCache`는 **프로세스 메모리**에 데이터를 저장한다. uvicorn을 껐다 켜면 모든 세션이 날아간다. 이건 의도된 동작이다 — 챗봇 대화는 오래 유지할 가치가 없고, 잃어도 복구할 필요가 없는 데이터라서.

---

## Line 5: `chromadb`

```
chromadb
```

### 역할

**벡터 데이터베이스**. 텍스트를 벡터(숫자 배열)로 저장하고 유사도 검색을 해주는 특수 DB.

### 이 프로젝트에서 어디에 쓰이나

- `app/config.py`에서 `chromadb.HttpClient(host=..., port=...)`로 **서버에 접속**하는 클라이언트 생성
- `chroma_client.get_or_create_collection(name="jarana_faq", embedding_function=None)`로 컬렉션 핸들 확보
- `scripts/index_docs.py`가 인덱싱 시 `collection.add(ids, embeddings, documents, metadatas)`로 20개 청크 저장
- `app/rag.py`가 질의 시 `collection.query(query_embeddings=..., n_results=3)`로 가장 비슷한 3개 검색

### 클라이언트 모드 두 가지

ChromaDB는 설치해도 **서버 역할 + 클라이언트 역할**을 한 패키지에서 다 한다:

| 모드 | 설명 | 이 프로젝트에서 |
|------|------|---------------|
| `PersistentClient` | 로컬 파일 시스템에 직접 쓰기 (SQLite 느낌) | 사용 안 함 |
| `HttpClient` | 별도로 띄운 ChromaDB 서버에 HTTP로 접속 | **이걸 씀** |

Docker Compose로 ChromaDB를 **별도 컨테이너**로 띄우기 때문에 `HttpClient`가 필요하다. 챗봇 컨테이너는 HTTP 네트워크로 ChromaDB 컨테이너에 접속한다.

### 이 패키지가 설치되면 따라오는 것들

`chromadb`는 내부적으로 꽤 많은 걸 가져온다:
- sqlite 드라이버
- 기본 임베딩 모델 (`all-MiniLM-L6-v2`) — 단, 우리는 `embedding_function=None`으로 이걸 끈다
- numpy, pandas 같은 수치 계산 라이브러리

패키지 용량이 제법 크지만 한 번 설치하면 그만이다.

### 왜 ChromaDB인가 (다른 벡터 DB 대비)

- **진입 장벽 낮음** — `pip install`만으로 로컬에서 바로 돌아감
- **Docker 이미지 공식 제공** — 인프라 세팅 쉬움
- **Summary-based Retrieval 패턴 지원** — metadata에 원본 텍스트 저장 + 벡터는 요약문으로 검색이 한 컬렉션에서 가능
- **무료** — Pinecone 같은 SaaS와 달리 호스팅 비용 없음

---

## Line 6: `httpx`

```
httpx
```

### 역할

**비동기 HTTP 클라이언트**. 파이썬에서 외부 API로 HTTP 요청을 보낼 때 쓰는 라이브러리.

> 참고: 현재 코드베이스에서는 직접적인 외부 HTTP 호출이 없어 사실상 사용되지 않는다. PydanticAI 등의 의존성에서 간접적으로 쓰일 수 있으며, 추후 외부 API 연동이 필요할 때 활용 가능.

### `requests` 대신 `httpx`를 쓰는 이유 (참고)

파이썬에서 HTTP 요청 하면 보통 `requests` 라이브러리를 떠올린다. 그런데 `requests`는 **동기**만 지원한다. async 함수 안에서 동기 클라이언트를 쓰면 이벤트 루프를 블로킹해서 다른 요청이 밀린다. `httpx`는 `requests`와 거의 동일한 API를 가지면서도 `AsyncClient`로 비동기 호출을 지원한다.

---

## Line 7: `python-dotenv`

```
python-dotenv
```

### 역할

**`.env` 파일을 읽어서 `os.environ`에 환경변수로 주입해주는** 작은 라이브러리. 딱 이것만 한다.

### 이 프로젝트에서 어디에 쓰이나

`app/config.py`의 제일 윗부분:

```python
from dotenv import load_dotenv
load_dotenv()
```

이 두 줄이 끝이다. `load_dotenv()`가 호출되면:
1. 현재 디렉토리(또는 상위 디렉토리)에서 `.env` 파일을 찾는다
2. 파일 내용을 파싱해서 `KEY=VALUE` 쌍으로 분리한다
3. 각 쌍을 `os.environ[KEY] = VALUE`로 주입한다
4. **이미 환경변수로 설정돼 있던 값은 기본적으로 덮어쓰지 않는다** (Docker 환경변수 override가 가능한 이유)

### 왜 `.env` 파일을 쓰는가

코드에 API 키를 직접 박는 방식과 비교:

```python
# 위험한 방식
GOOGLE_API_KEY = "AIzaSyDfBVjKowubm5..."  # git에 올라감, 탈취 위험
```

```python
# 안전한 방식
GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]  # .env에서 로드, git에 안 올라감
```

`.env` 파일은 `.gitignore`에 등록해서 git에 커밋하지 않는 것이 철칙이다.

### 왜 별도 라이브러리가 필요한가

파이썬 자체에는 `.env` 파일 자동 로딩 기능이 없다. `os.environ`은 OS가 넘겨준 환경변수만 읽는다. 로컬 개발 시 매번 `export GOOGLE_API_KEY=...`를 치는 건 번거로우니, `.env` 파일에 한 번 적어두고 `python-dotenv`가 읽도록 한다.

### 운영 환경에서는 `.env`가 필요 없을 수도 있다

Docker나 Kubernetes 같은 운영 환경에서는 환경변수를 **컨테이너 실행 시점에 주입**한다:

```yaml
# docker-compose.yml
chatbot:
  environment:
    - GOOGLE_API_KEY=${GOOGLE_API_KEY}
    - CHROMA_HOST=chromadb
```

이 경우 `os.environ`에 이미 값이 들어있으므로 `load_dotenv()`는 **아무것도 안 한다** (덮어쓰지 않으므로). 즉 로컬에서는 `.env`가 소스가 되고 운영에서는 Docker가 소스가 되는, 일관된 인터페이스가 완성된다.

---

## 의존성 간 관계 요약

```
[웹 프레임워크 스택]
  fastapi           ─┐
  uvicorn[standard]  ├─ HTTP 서버 (요청 수신/응답)
                    ─┘

[LLM 스택]
  pydantic-ai[google] ── Gemini Agent + Embedder

[데이터 저장 스택]
  chromadb          ── 벡터 DB (RAG 검색용)
  cachetools        ── 세션 메모리 캐시 (대화 히스토리)

[외부 통신]
  httpx             ── 비동기 HTTP 클라이언트 (현재 직접 사용처는 없음)

[설정]
  python-dotenv     ── .env 파일 로드
```

**7개밖에 안 된다**는 점이 이 프로젝트의 장점이다. MVP 스타일로 꼭 필요한 것만 추려놓았다. 의존성이 적으면 설치도 빠르고, 보안 취약점 관리도 쉽고, 업그레이드 충돌도 줄어든다.

---

## 설치 방법 (참고)

```bash
# 가상환경 생성
python -m venv .venv
source .venv/bin/activate

# 의존성 설치
pip install -r requirements.txt
```

이 한 번의 명령으로 위 7개 패키지 + 그들의 의존성(수십 개)이 한꺼번에 깔린다. pip는 의존성 그래프를 자동으로 해결해준다.

---

# 2부. `.env`

## 파일 전체

```env
GOOGLE_API_KEY=<REDACTED>
CHROMA_HOST=localhost
CHROMA_PORT=8001
```

총 3줄, 3개의 환경변수가 정의돼있다. 실제 파일에는 `GOOGLE_API_KEY`에 Google이 발급한 실제 키가 들어가 있지만, **보안상 이 문서에는 마스킹 처리**한다.

### `.env` 파일 문법 기본

- 한 줄에 하나의 변수: `KEY=VALUE`
- `=` 양옆에 공백 넣지 않음
- 따옴표는 선택 (`KEY="value"`도 됨)
- 주석은 `#`으로 시작
- 빈 줄 허용

---

## Line 1: `GOOGLE_API_KEY`

```env
GOOGLE_API_KEY=<REDACTED>
```

### 의미

**Google Generative Language API(Gemini)에 접근하기 위한 API 키**. 이 키가 있어야 Gemini 모델을 호출할 수 있다.

### 발급 방법

1. https://aistudio.google.com/ 접속
2. 구글 계정 로그인
3. "Get API key" 버튼 클릭
4. 새 프로젝트 생성 → API 키 발급
5. `AIzaSy...` 로 시작하는 긴 문자열이 키

### 이 프로젝트에서 어디에 쓰이나

**직접 참조되는 곳은 한 군데**지만, **간접적으로는 거의 모든 LLM 호출**에 쓰인다.

#### 직접 참조 — `app/config.py` (Line 9-10)

```python
if "GOOGLE_API_KEY" not in os.environ:
    raise RuntimeError("GOOGLE_API_KEY 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
```

여기서 **존재 여부만 체크**한다. 값 자체를 코드가 직접 쓰지는 않는다.

#### 간접 참조 — PydanticAI가 자동으로 읽음

PydanticAI의 `Embedder`와 `Agent`는 생성 시 내부적으로 `os.environ["GOOGLE_API_KEY"]`를 **자동으로 읽어서** Google API 클라이언트에 전달한다.

```python
# app/config.py
embedder = Embedder(EMBEDDING_MODEL)  # 내부에서 GOOGLE_API_KEY 자동 사용

# app/llm.py
agent = Agent(GEMINI_MODEL, ...)      # 내부에서 GOOGLE_API_KEY 자동 사용
```

즉 **코드 어디에도 `GOOGLE_API_KEY`를 명시적으로 넘기는 부분이 없지만**, `load_dotenv()`로 `os.environ`에 올려놓기만 하면 PydanticAI가 알아서 가져다 쓴다.

### 왜 Fail Fast 체크가 있나

PydanticAI는 키가 없어도 객체 생성 자체는 성공시키고, 실제로 API 호출할 때가 되어서야 "인증 실패" 에러를 낸다. 그 에러 메시지는 알쏭달쏭해서 원인 파악이 어렵다.

`config.py`가 서버 시작 시점에 **"`.env` 파일을 확인하세요"** 같은 명확한 한글 메시지로 실패시키면 디버깅 시간이 훨씬 줄어든다.

### 보안 주의사항

- **git에 절대 커밋하지 말 것** — `.gitignore`에 `.env`가 반드시 포함돼야 함
- **로그에 출력하지 말 것** — 실수로 `print(os.environ["GOOGLE_API_KEY"])` 하지 않도록 주의
- **유출 시 즉시 폐기** — Google AI Studio에서 키를 삭제하고 재발급
- 무료 티어라도 **할당량 초과 시 계정에 영향**을 줄 수 있음

### 이 문서에서 값이 마스킹된 이유

실제 `.env` 파일에는 `AIzaSy...`로 시작하는 진짜 키가 들어있지만, 이 문서에서는 `<REDACTED>`로 대체했다. 문서가 git에 커밋되어도 실제 키는 새어나가지 않도록 하기 위해서다.

---

## Line 2: `CHROMA_HOST`

```env
CHROMA_HOST=localhost
```

### 의미

**ChromaDB 서버가 돌아가고 있는 호스트 주소**. 챗봇이 벡터 검색을 하려면 ChromaDB 서버에 접속해야 하는데, 그 서버가 어디 있는지를 알려주는 값.

### 이 프로젝트에서 어디에 쓰이나

#### `app/config.py` (Line 15)

```python
CHROMA_HOST = os.environ.get("CHROMA_HOST", "localhost")
```

기본값이 `localhost`라서 `.env`에 없어도 같은 결과. 마찬가지로 명시적 문서화 목적.

#### `app/config.py` (Line 24)

```python
chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
```

여기서 실제로 사용된다. `HttpClient`는 "이 호스트의 이 포트에서 돌아가고 있는 ChromaDB 서버에 HTTP로 접속하겠다"는 의미.

### 로컬 vs Docker 환경

이 프로젝트는 **두 가지 실행 시나리오**가 있다:

**시나리오 A: 로컬에서 챗봇 개발 중**

```
┌─ 내 맥북 ──────────────────────┐
│  [터미널 1] ChromaDB 서버     │ ← localhost:8001
│  [터미널 2] uvicorn (챗봇)    │ → localhost:8001로 접속
└────────────────────────────────┘
```

이 경우 챗봇은 `localhost:8001`로 ChromaDB에 접속한다. `.env`의 `CHROMA_HOST=localhost`가 그대로 쓰임.

**시나리오 B: Docker Compose로 전체 띄움**

```
┌─ Docker 네트워크 ──────────────┐
│  [컨테이너 A] chromadb 서비스  │
│  [컨테이너 B] chatbot 서비스   │ → chromadb:8000으로 접속
└────────────────────────────────┘
```

이 경우 챗봇 컨테이너 입장에서는 ChromaDB가 `localhost`에 있지 않다. Docker Compose가 만드는 가상 네트워크 안에서 **서비스명**(`chromadb`)으로 접근해야 한다.

### Docker 환경에서의 override

`docker-compose.yml`에는 이렇게 적혀있다:

```yaml
chatbot:
  environment:
    - CHROMA_HOST=chromadb
```

이 설정이 `.env` 파일의 값을 **덮어쓴다**. 앞서 설명한 `python-dotenv`의 동작 — "이미 환경변수로 설정된 값은 덮어쓰지 않는다" — 덕분에 Docker가 넣어준 `CHROMA_HOST=chromadb`가 우선 적용된다.

→ 결과적으로 **로컬 개발에서는 `localhost`, Docker에서는 `chromadb`**가 자동으로 선택된다. `.env` 파일과 `docker-compose.yml`이 협력해서 두 환경을 모두 지원.

---

## Line 4: `CHROMA_PORT`

```env
CHROMA_PORT=8001
```

### 의미

**ChromaDB 서버의 포트 번호**.

### 값이 8001인 이유

ChromaDB의 **기본 포트는 8000**이지만, 이 프로젝트는 일부러 `8001`을 쓴다. 이유는 포트 충돌을 피하기 위해서다:

| 서비스 | 포트 |
|--------|------|
| 챗봇 FastAPI | 8080 |
| ChromaDB (로컬 실행) | **8001** |

ChromaDB의 기본 포트(8000)와 다른 로컬 서비스 충돌을 피하려고 `8001`을 쓴다.

### 이 프로젝트에서 어디에 쓰이나

#### `app/config.py` (Line 16)

```python
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8001"))
```

**여기서 한 가지 중요한 변환이 일어난다**: `int()`.

환경변수는 **무조건 문자열**이다. `.env`에 `CHROMA_PORT=8001`이라고 써도 `os.environ.get("CHROMA_PORT")`는 `"8001"`(문자열)을 반환한다. 그런데 ChromaDB 클라이언트는 포트를 **정수**로 요구한다:

```python
chromadb.HttpClient(host="localhost", port=8001)  # int 요구
chromadb.HttpClient(host="localhost", port="8001") # str이면 에러
```

그래서 `int("8001")`로 변환해서 넘긴다. 이 한 줄이 없으면 서버 시작 시 타입 에러가 발생한다.

### 기본값도 문자열로 적은 이유

```python
os.environ.get("CHROMA_PORT", "8001")
```

기본값도 정수 `8001`이 아니라 문자열 `"8001"`인 게 눈에 띈다. 이유는 **일관성**이다. `os.environ.get`은 환경변수가 있을 때는 문자열을 반환하므로, 기본값도 문자열로 맞춰야 타입이 섞이지 않는다. 그래야 `int(...)` 한 번으로 일괄 변환할 수 있다.

### Docker 환경에서 포트가 달라질 수 있음

Docker Compose 안에서 ChromaDB 컨테이너의 **내부 포트는 기본값 8000**이다. 컨테이너끼리 통신할 때는 호스트 머신의 포트와 무관하다:

```yaml
chromadb:
  ports:
    - "8001:8000"   # 호스트:컨테이너
```

이 설정의 의미:
- 호스트 머신에서 `localhost:8001`로 접근 → ChromaDB 컨테이너 내부의 8000으로 포워딩 (로컬 개발용)
- 컨테이너끼리는 `chromadb:8000`으로 접근

그래서 Docker 환경의 챗봇 컨테이너는 `CHROMA_HOST=chromadb`, `CHROMA_PORT=8000`으로 override 받는다. `.env` 파일의 `CHROMA_PORT=8001`은 로컬 개발 전용 값이다.

---

## `.env`에 **없는** 환경변수들

`config.py`를 보면 환경변수를 참조하는 줄이 이 외에도 있다:

```python
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "google-gla:gemini-3.1-flash-lite-preview")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "google-gla:gemini-embedding-2-preview")
```

이 두 개는 `.env`에 **없다**. 왜일까?

| 변수 | `.env`에 없는 이유 |
|------|---------------------|
| `GEMINI_MODEL` | 모델 교체 실험을 자주 하지 않는 한 기본값으로 충분 |
| `EMBEDDING_MODEL` | 마찬가지로 고정 |

**원칙**: 환경변수로 **만들 수 있게** 해두되, 실제로 덮어쓸 일이 없으면 `.env`에 안 적어도 된다. 필요할 때만 추가하면 된다. `.env`가 너무 길어지면 오히려 관리가 어려워진다.

---

## 이 `.env` 파일이 로드되는 흐름

```
1. 개발자가 uvicorn 실행
     ↓
2. uvicorn이 app/main.py import
     ↓
3. main.py가 routers/chat.py import
     ↓
4. chat.py가 rag.py import
     ↓
5. rag.py가 app/config.py import
     ↓
6. config.py 맨 윗줄: load_dotenv() 실행
     ↓
7. python-dotenv가 .env 파일 찾아서 파싱
     ↓
8. os.environ에 3개 변수 주입:
     - GOOGLE_API_KEY = <REDACTED>
     - CHROMA_HOST    = localhost
     - CHROMA_PORT    = 8001
     ↓
9. config.py의 나머지 줄들이 os.environ.get(...)으로 이 값을 읽음
     ↓
10. Embedder, ChromaDB 클라이언트 등의 싱글톤 객체 생성
     ↓
11. 서버 시작 완료, 요청 받을 준비 끝
```

**한 번만 로드된다**는 게 핵심이다. 서버가 돌아가는 동안 `.env` 파일을 수정해도 반영되지 않는다. `--reload` 옵션으로 uvicorn을 돌리면 파일 변경 시 재시작되면서 다시 로드된다.

---

## 전체 정리 — 이 두 파일의 관계

```
requirements.txt (라이브러리 설치)
    ↓
.venv 에 7개 패키지 + 의존성 설치됨
    ↓
.env (실행 시 필요한 값)
    ↓
app/config.py의 load_dotenv()가 .env 읽음
    ↓
os.environ에 3개 환경변수 주입
    ↓
config.py가 그 값으로 싱글톤 객체 생성
  - Embedder (GOOGLE_API_KEY 자동 사용)
  - chroma_client (CHROMA_HOST, CHROMA_PORT 사용)
    ↓
rag.py, llm.py, index_docs.py가
  config.py의 싱글톤을 import해서 사용
    ↓
챗봇 동작
```

---

## 핵심 정리

1. **`requirements.txt`는 7줄짜리 의존성 목록**이다. 버전 pin이 없어서 `pip install` 시점의 최신 버전이 깔린다. MVP 단계에서는 편하지만 운영 단계에서는 `pip freeze`로 lock 파일을 만드는 게 좋다.

2. **각 패키지가 한 가지 역할을 맡는다**. FastAPI/uvicorn(서버), PydanticAI(LLM), ChromaDB(벡터 저장), cachetools(세션 캐시), httpx(비동기 HTTP, 현재 직접 사용처는 없음), python-dotenv(.env 로드). 중복이 없고 필요한 것만 있다.

3. **`.env` 파일은 3줄**이고 실제로는 `GOOGLE_API_KEY`만이 절대적으로 필수다. 나머지 2개는 기본값이 있어서 생략 가능.

4. **보안 핵심**: `GOOGLE_API_KEY` 실제 값을 이 문서, 코드, git에 노출시키지 말 것. `.env`는 `.gitignore`에 반드시 등록. 이 문서에서도 `<REDACTED>`로 마스킹했다.

5. **Docker 환경에서는 `.env`의 값이 덮어쓰여진다**. 특히 `CHROMA_HOST=chromadb`로 override돼서 컨테이너 네트워크를 쓴다. `python-dotenv`가 "이미 설정된 환경변수는 덮어쓰지 않는다"는 동작 덕분에 두 환경이 자연스럽게 양립한다.
