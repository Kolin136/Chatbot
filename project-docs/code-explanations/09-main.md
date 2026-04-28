# `app/main.py` 코드 해석

## 파일 역할

**FastAPI 애플리케이션의 엔트리포인트(Entry Point)** 파일. 서버를 `uvicorn app.main:app`으로 띄울 때 가장 먼저 실행되는 파일이다.

하는 일은 크게 네 가지:

1. `FastAPI` 인스턴스를 만든다 (= "웹 서버 본체" 객체 생성)
2. CORS 미들웨어를 등록한다 (= 브라우저 cross-origin 요청 허용)
3. `routers/chat.py`의 라우터를 `/api` prefix로 붙인다 (= `POST /api/chat` 엔드포인트 연결)
4. `front/` 폴더의 정적 파일을 서빙하고 `/`에서 `index.html`을 반환한다 (= 프론트 웹페이지 제공)

로직이 거의 없는 **조립 파일**이다. 실제 일하는 코드는 `rag.py`, `llm.py`, `post_reporter.py`, `routers/chat.py`에 흩어져 있고, `main.py`는 그걸 FastAPI 앱에 "꽂아 넣는" 역할만 한다.

### 핵심 개념: ASGI 애플리케이션과 엔트리포인트

파이썬 웹 서버는 보통 **ASGI(Async Server Gateway Interface)** 라는 규격에 따라 동작한다. uvicorn은 ASGI 서버의 한 종류고, FastAPI는 ASGI 애플리케이션을 만드는 프레임워크다.

```bash
uvicorn app.main:app --port 8080 --reload
```

이 명령은 uvicorn에게 이렇게 말한다:

- `app.main` 모듈을 import 해서
- 그 안에 있는 `app`이라는 변수(FastAPI 인스턴스)를 가져와
- 그 객체를 ASGI 앱으로 취급해서 8080 포트에서 HTTP 요청을 받아 넘겨라

→ `main.py`의 목적은 uvicorn이 import할 **`app`이라는 이름의 FastAPI 인스턴스**를 모듈 최상단에 노출시키는 것이다. 파일 이름(`main`)과 변수 이름(`app`)이 합쳐져 `app.main:app`이 된다.

---

## Line 1: 임포트 — 컨텍스트 매니저 데코레이터

```python
from contextlib import asynccontextmanager
```

파이썬 표준 라이브러리 `contextlib`에서 `asynccontextmanager` 데코레이터를 가져온다.

### `asynccontextmanager`가 뭔가

"비동기 컨텍스트 매니저"를 **함수로 간단히 만들어주는 데코레이터**다. 컨텍스트 매니저란 `with` 문(비동기는 `async with`)에서 "진입 시 무엇을 하고, 빠져나올 때 무엇을 할지"를 정의하는 객체를 말한다.

일반 동기 버전:

```python
from contextlib import contextmanager

@contextmanager
def open_resource():
    # 진입 시
    resource = acquire()
    try:
        yield resource     # ← 이 지점에서 with 블록 본문이 실행됨
    finally:
        # 나갈 때
        release(resource)
```

`asynccontextmanager`는 이걸 `async`/`await`로 쓸 수 있게 한 버전이다. 여기서는 아래 `lifespan` 함수를 만드는 데 쓴다.

---

## Line 3-6: FastAPI 관련 임포트

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
```

FastAPI의 네 가지 핵심 요소를 한 번에 가져온다.

| 임포트 | 역할 | 이 파일에서의 용도 |
|--------|------|-------------------|
| `FastAPI` | 애플리케이션 본체 클래스 | `app = FastAPI(...)`로 인스턴스 생성 |
| `CORSMiddleware` | Cross-Origin Resource Sharing 미들웨어 | 브라우저 cross-origin 요청 허용 |
| `FileResponse` | 파일을 HTTP 응답으로 돌려주는 응답 객체 | 루트 경로에서 `index.html` 반환 |
| `StaticFiles` | 정적 파일 서빙 ASGI 서브앱 | `/static` 경로에 `front/` 폴더 마운트 |

**FastAPI의 철학**: "필요한 것만 명시적으로 import해서 쓴다". Django처럼 설정 파일에 모든 걸 등록하는 스타일이 아니라, 코드에서 직접 클래스를 가져다 쓰는 스타일이다. 그래서 이런 식의 얇은 import가 많다.

---

## Line 8: 라우터 임포트

```python
from app.routers.chat import router as chat_router
```

`app/routers/chat.py`에서 `router`라는 객체를 가져와서 **`chat_router`라는 이름으로 별칭**을 준다.

### `as`로 별칭을 준 이유

`routers/chat.py` 안에는 이렇게 정의돼 있다:

```python
# app/routers/chat.py
from fastapi import APIRouter

router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    ...
```

이름이 그냥 `router`다. 만약 나중에 다른 라우터(예: `users/router.py`)를 추가해서 같이 import 하면 이름이 겹친다:

```python
from app.routers.chat import router   # router
from app.routers.users import router  # ← 위 router를 덮어씀!
```

이 사태를 막으려고 `as chat_router`로 고유한 이름을 준다. 지금은 라우터가 하나지만 확장성을 고려한 관례.

### 이 한 줄이 부르는 연쇄 import

이 import 한 줄 때문에 **파이썬이 `routers/chat.py`를 실행**하고, 그 파일 안의 import들이 순차적으로 실행된다:

```
main.py
  └─ routers/chat.py
       ├─ rag.py → config.py 실행 (여기서 embedder, chroma_collection 생성)
       ├─ llm.py → agent, _sessions 캐시 생성
       └─ post_reporter.py
```

→ **`main.py`의 이 한 줄이 실질적으로 "앱 전체 초기화"를 트리거한다**. `config.py`의 `.env` 로드, `Embedder` 생성, ChromaDB 연결, LLM `agent` 생성이 전부 이 시점에 끝난다.

> 관련: `00-flow-overview.md`의 "서버 시작 흐름"에서 이 연쇄 import가 단계별로 정리돼 있다.

---

## Line 11-13: lifespan 컨텍스트 매니저 정의

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
```

FastAPI의 **lifespan(수명 주기) 훅**을 정의하는 부분. 서버가 시작될 때와 종료될 때 실행할 코드를 여기에 작성한다.

### `lifespan`의 구조와 의미

이 함수는 세 구간으로 나뉘는 템플릿이다:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # [1] 서버 시작 전: 여기에 startup 로직
    yield
    # [2] 서버 종료 시: 여기에 shutdown 로직
```

- `yield` **이전** 코드는 uvicorn이 첫 요청을 받기 **전에** 한 번 실행된다.
- `yield` **이후** 코드는 서버가 정상 종료될 때 한 번 실행된다.
- 중간의 `yield`는 "그 동안 서버가 돌아간다"는 뜻.

### 이 프로젝트에서는 왜 비어있나

현재 코드는 `yield` 하나뿐이다. 즉 "시작할 때도 아무것도 안 하고, 끝날 때도 아무것도 안 한다". 이 프로젝트는 **무거운 초기화(`.env` 로드, `Embedder` 생성, ChromaDB 연결)를 이미 `config.py`의 모듈 레벨 코드로 끝내버렸기 때문에** lifespan에서 할 일이 없다.

그럼 왜 굳이 비어있는 lifespan을 선언했을까:

1. **확장 여지 확보** — 나중에 ChromaDB 연결 풀 정리, 백그라운드 태스크 기동/정지 같은 게 필요하면 여기에 넣으면 된다.
2. **`on_event` deprecation 대비** — 예전 FastAPI는 `@app.on_event("startup")`, `@app.on_event("shutdown")` 데코레이터를 썼지만 **deprecated** 됐다. 현재 권장 방식이 `lifespan` 컨텍스트 매니저. 미리 이 형태로 잡아둔 것.
3. **명시성** — 빈 `lifespan`이라도 선언해두면 "이 앱은 수명 주기 관리를 의식하고 있다"는 신호가 된다.

### FastAPI 인스턴스에 넘겨주는 방식

아래 `FastAPI(... lifespan=lifespan)`처럼 **함수 객체를 인자로 넘긴다**. FastAPI가 서버 기동/종료 시점에 내부에서 이 함수를 `async with`로 호출해준다.

```python
# FastAPI가 내부에서 대략 이렇게 쓴다
async with lifespan(app):
    # 서버가 요청을 받는 동안
    await serve_requests()
# with 블록을 빠져나올 때 자동으로 yield 이후 코드가 실행됨
```

→ `async with` 구문의 장점: try/finally를 직접 쓰지 않아도 "시작 코드"와 "종료 코드"가 쌍으로 묶여서, 중간에 예외가 나도 종료 코드가 반드시 실행된다는 보장이 생긴다.

---

## Line 16: FastAPI 인스턴스 생성

```python
app = FastAPI(title="Jarana Chatbot", lifespan=lifespan)
```

**이 파일의 핵심 한 줄**. FastAPI 인스턴스를 만들고 모듈 레벨 변수 `app`에 담는다. 이 `app` 객체가 uvicorn이 가져가서 돌릴 **ASGI 애플리케이션 객체**가 된다.

### 인자 두 개

| 인자 | 역할 |
|------|------|
| `title="Jarana Chatbot"` | OpenAPI 자동 문서(`/docs`, `/redoc`)의 상단 제목. 서비스 동작에는 영향 없음 |
| `lifespan=lifespan` | 위에서 만든 수명 주기 매니저 등록 |

### `FastAPI()` 호출이 하는 일

내부적으로 FastAPI 인스턴스는:

- 라우트 테이블(빈 상태) 초기화
- 미들웨어 체인(빈 상태) 초기화
- OpenAPI 스키마 생성기 준비
- 의존성 주입(Dependency Injection) 시스템 초기화

를 한다. 이 시점에는 아직 아무 엔드포인트도 등록돼 있지 않다. 아래 `app.include_router(...)`, `app.mount(...)`, `@app.get("/")` 들이 차례로 이 인스턴스에 내용을 채워 넣는다.

### `app`이라는 이름을 쓴 이유

`uvicorn app.main:app`에서 마지막 `app`이 바로 이 변수 이름을 가리킨다. 관례상 `app`을 많이 쓰지만 꼭 그래야 하는 건 아니고, 만약 `application = FastAPI(...)`로 썼다면 `uvicorn app.main:application`으로 돌려야 한다.

---

## Line 18-23: CORS 미들웨어 등록

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

브라우저의 **CORS(Cross-Origin Resource Sharing)** 제약을 풀어주는 미들웨어를 등록한다.

### 미들웨어란?

미들웨어는 "요청이 라우트 핸들러에 도달하기 **전**, 그리고 응답이 클라이언트로 나가기 **직전**"에 끼어들어서 공통 처리를 하는 컴포넌트다. 로깅, 인증, CORS 같은 **횡단 관심사(cross-cutting concerns)** 에 쓴다.

```
[클라이언트] 
    │ 요청
    ▼
[CORS 미들웨어]  ← 여기서 Origin 헤더 체크 + 응답에 CORS 헤더 추가
    │
    ▼
[라우트 핸들러] (chat, root 등)
    │
    ▼
[CORS 미들웨어]  ← 응답에 Access-Control-Allow-* 헤더 주입
    │
    ▼
[클라이언트]
```

### CORS가 왜 필요한가

브라우저는 **보안상** "현재 보고 있는 페이지와 다른 출처(origin)로 AJAX 요청을 못 보내게** 막는다. 이걸 Same-Origin Policy라고 한다.

- 프론트: `http://localhost:3000/` 에서 돌아가는 React 앱
- 백엔드: `http://localhost:8080/api/chat`

→ 포트가 다르므로 브라우저 기준으로는 "다른 출처". CORS 설정이 없으면 프론트에서 백엔드로 fetch를 날려도 **브라우저가 차단**해버린다.

해결 방법: 서버가 응답 헤더에 `Access-Control-Allow-Origin: *` 같은 값을 붙여서 "난 cross-origin 요청을 허용한다"고 알린다. 이걸 자동으로 해주는 게 `CORSMiddleware`.

### 각 옵션 의미

| 옵션 | 값 | 의미 |
|------|------|------|
| `allow_origins=["*"]` | 모든 출처 허용 | 어떤 도메인에서 온 요청이든 수락 |
| `allow_methods=["*"]` | 모든 HTTP 메서드 허용 | GET, POST, PUT, DELETE, OPTIONS 다 OK |
| `allow_headers=["*"]` | 모든 요청 헤더 허용 | Content-Type, Authorization 등 다 OK |

### `"*"`를 써도 되는가?

개발/데모 환경에서는 흔한 설정이지만, 운영 환경에서는 **보안 위험**이 있다. 예를 들어 `allow_credentials=True`와 `allow_origins=["*"]`는 동시 사용이 금지돼 있다(CORS 스펙 자체에서).

Jarana 챗봇은 현재:

- 쿠키 기반 인증을 쓰지 않음 (`allow_credentials` 기본값 `False`)
- 공개 데모 용도로 프론트가 같은 서버에서 서빙됨

→ 이 조건에선 `"*"`가 실용적 선택이지만, 운영 배포 시에는 `allow_origins=["https://jarana.example.com"]`처럼 명시적으로 제한하는 게 바람직하다.

### `add_middleware` 호출 순서

`add_middleware`는 **순서대로 체인에 쌓인다**. 미들웨어가 여러 개라면 나중에 추가한 게 바깥쪽, 먼저 추가한 게 안쪽에 위치한다. 이 파일은 CORS 하나뿐이라 순서 고민이 필요 없다.

---

## Line 25: API 라우터 등록

```python
app.include_router(chat_router, prefix="/api")
```

Line 8에서 import한 `chat_router`를 **`/api`를 접두사로 붙여서** FastAPI 앱에 등록한다.

### `include_router`가 하는 일

`routers/chat.py`의 라우터에는 이렇게 정의된 엔드포인트가 있다:

```python
@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    ...
```

경로가 `/chat`이지만, `include_router(chat_router, prefix="/api")`로 등록되면 실제 공개 경로는 `"/api"` + `"/chat"` = **`/api/chat`**이 된다.

```
클라이언트가 호출 → POST http://localhost:8080/api/chat
                         │
                         ▼
                  /api prefix 매칭
                         │
                         ▼
                  chat_router의 /chat 핸들러 실행
```

### `prefix`의 의미

모든 API 엔드포인트를 `/api/...` 아래에 모으는 **네임스페이스 구분** 효과가 있다. 정적 파일(`/static`)과 메인 페이지(`/`)는 prefix가 없으므로, **URL만 봐도 "API 요청"인지 "페이지 요청"인지 구분**된다.

나중에 `users`, `auth` 같은 라우터를 추가해도 각각 `include_router(users_router, prefix="/api")`로 붙이면 `/api/users`, `/api/auth`가 되어 깔끔하게 모인다.

### 라우터 분리 패턴의 장점

한 파일(`main.py`)에 엔드포인트를 전부 쓸 수도 있지만, 이 프로젝트는 `routers/chat.py`에 분리해뒀다. 이유:

- **책임 분리**: `main.py`는 "앱 설정", `chat.py`는 "엔드포인트 로직"
- **테스트 편의**: 라우터만 따로 import해서 단위 테스트 가능
- **확장성**: 라우터 파일 추가로 기능 증설

---

## Line 27: 정적 파일 마운트

```python
app.mount("/static", StaticFiles(directory="front"), name="static")
```

`front/` 디렉토리를 **`/static` URL에 마운트**한다. 즉, 브라우저가 `http://localhost:8080/static/app.js`를 요청하면 서버는 `front/app.js` 파일을 돌려준다.

### `mount` vs `include_router`의 차이

| 메서드 | 용도 | 등록 대상 |
|--------|------|----------|
| `include_router` | 라우터(엔드포인트 묶음) 등록 | `APIRouter` 객체 |
| `mount` | 서브 ASGI 앱 등록 | `StaticFiles` 같은 독립 ASGI 앱 |

`StaticFiles`는 FastAPI의 라우터가 아니라 **그 자체로 독립된 ASGI 앱**이다. `mount`는 "이 경로 아래로 오는 모든 요청은 이 서브 앱에게 통째로 넘겨라"라는 의미.

```
GET /static/app.js
    │
    ▼
FastAPI가 /static으로 시작하는 요청임을 감지
    │
    ▼
StaticFiles 서브앱에게 "app.js" 요청을 위임
    │
    ▼
StaticFiles가 front/app.js를 찾아서 반환
```

### 각 인자의 의미

| 인자 | 값 | 의미 |
|------|------|------|
| `"/static"` | 마운트 URL 경로 | 이 경로 아래로 오는 요청이 대상 |
| `StaticFiles(directory="front")` | 서빙할 ASGI 앱 | 실제 파일을 찾을 로컬 디렉토리 |
| `name="static"` | 내부 이름 | `url_for("static", path="app.js")` 같은 URL 역산에 쓰임 |

### 실제 파일 매핑 예시

`front/` 폴더에 실제로 있는 파일들:

| 파일 시스템 경로 | 브라우저 URL |
|-----------------|-------------|
| `front/index.html` | `http://localhost:8080/static/index.html` |
| `front/app.js` | `http://localhost:8080/static/app.js` |
| `front/style.css` | `http://localhost:8080/static/style.css` |

### `directory="front"`의 상대 경로 주의점

이 경로는 **서버를 실행하는 현재 작업 디렉토리 기준**이다. 프로젝트 루트에서 `uvicorn app.main:app`을 실행하면 `front/`가 루트 바로 아래에 있어서 제대로 찾는다. 하지만 `cd app && uvicorn main:app`처럼 다른 디렉토리에서 실행하면 경로가 틀어져 404가 난다.

→ 실행 위치에 의존적이라는 점은 기억해둘 것. 운영 배포에서는 보통 절대 경로나 `Path(__file__).parent` 기반으로 바꿔주는 게 안전하다.

---

## Line 30-32: 루트 경로 핸들러

```python
@app.get("/")
async def root():
    return FileResponse("front/index.html")
```

브라우저가 `http://localhost:8080/`(루트)를 요청하면 `front/index.html`을 **직접 파일로 돌려준다**.

### `@app.get("/")` 데코레이터

FastAPI의 **라우트 데코레이터**. "`GET /` 요청이 오면 아래 함수를 실행하라"는 뜻. `app.include_router`가 아니라 `app` 본체에 직접 붙이는 방식이다. 엔드포인트가 하나뿐이거나 라우터로 뺄 정도가 아닐 때 사용한다.

### `async def root()`

함수 이름 `root`는 의미상 "루트 경로"를 담당한다는 뜻. FastAPI는 함수명을 공개 경로에 쓰지 않으므로 어떤 이름이어도 무방하지만, 관례상 경로 의미를 반영하는 이름을 쓴다.

`async def`로 선언된 이유는 FastAPI가 내부에서 일관되게 코루틴으로 처리하기 위해서. `FileResponse` 자체는 동기적이지만, `async def`로 쓰는 게 표준이다. (동기 `def`로 선언해도 FastAPI가 자동으로 스레드풀에서 돌려주지만, 여기선 어차피 단순한 파일 반환이라 `async def`가 자연스럽다.)

### `FileResponse`란?

파일을 HTTP 응답 바디로 그대로 돌려주는 **FastAPI 응답 객체**. 내부적으로:

- 파일을 스트리밍 방식으로 읽어서 전송 (메모리에 다 올리지 않음)
- 파일 확장자로부터 `Content-Type` 자동 설정 (`.html` → `text/html`)
- 파일 크기를 `Content-Length` 헤더에 자동 설정
- 필요 시 `ETag`, `Last-Modified` 헤더도 붙여줌

→ 그냥 `return open("front/index.html").read()`보다 훨씬 안전하고 효율적이다.

### 왜 `/static/index.html`을 쓰지 않고 별도 핸들러를 만들었나

`app.mount("/static", ...)` 덕분에 이미 `http://localhost:8080/static/index.html`로 접근할 수 있다. 그럼 굳이 루트 핸들러가 왜 필요한가?

이유는 **사용자 경험**이다. 사용자는 `http://localhost:8080`만 입력하고 싶지 `http://localhost:8080/static/index.html`을 타이핑하고 싶지 않다. 루트 `/`로 접속했을 때 바로 챗봇 페이지가 뜨게 하는 **편의 엔드포인트**다.

내부적으로 돌려주는 파일은 같지만(`front/index.html`), `/`로 들어온 요청을 그 파일로 **직접 매핑**해주는 핀포인트 핸들러 역할이다.

### 다른 대안과의 비교

정적 프론트가 있는 앱에서 루트를 처리하는 방법 몇 가지:

| 방법 | 설명 | 이 프로젝트의 선택 |
|------|------|------------------|
| 리다이렉트 (`RedirectResponse`) | `/`로 오면 `/static/index.html`로 이동 | 안 씀. URL이 지저분해짐 |
| `StaticFiles(html=True)` | `mount("/", StaticFiles(html=True))` | 안 씀. `/api` 라우터와 충돌 위험 |
| **`FileResponse`로 직접 반환** | 루트 핸들러가 파일 객체를 반환 | **채택**. 깔끔하고 명시적 |

→ 세 번째 방식이 "`/`는 챗봇 페이지, `/api/*`는 API, `/static/*`는 기타 리소스"라는 경로 구조를 가장 명확하게 표현한다.

---

## 이 파일이 다른 파일에서 어떻게 쓰이나

이 파일은 **다른 파일에서 import 되지 않는다**. 반대로 **uvicorn이 실행 시 이 파일을 import한다.**

```bash
uvicorn app.main:app --port 8080 --reload
```

`app.main:app`의 해석:

- `app.main` → `app/main.py` 모듈을 import
- `:app` → 그 모듈의 `app` 변수(FastAPI 인스턴스)를 가져옴

이 `app` 인스턴스를 uvicorn이 ASGI 앱으로 취급해서, 들어오는 HTTP 요청을 이 객체에 넘긴다. 내부적으로 FastAPI가 URL 매칭/미들웨어 체인/핸들러 호출을 모두 처리한다.

### `--reload` 옵션의 의미

개발 모드에서 흔히 붙이는 옵션. 파이썬 파일이 변경되면 uvicorn이 **자동으로 서버를 재시작**한다. 코드를 고치고 저장하면 수초 내에 새 코드가 반영되므로 개발 생산성이 올라간다.

주의: 서버가 재시작되면 `config.py`, `llm.py`의 모듈 레벨 객체(`embedder`, `chroma_collection`, `agent`, `_sessions`)가 **전부 날아가고 새로 만들어진다**. LLM 세션 캐시(`_sessions`)도 초기화되므로 대화 이력이 사라진다. 운영 서버에서는 `--reload`를 쓰지 않는다.

---

## 실행 순서 / 호출 시점

### 서버 시작 시 (한 번)

1. 터미널에서 `uvicorn app.main:app --port 8080 --reload` 실행
2. uvicorn이 `app.main` 모듈을 import 시도
3. `main.py`의 **Line 1-6** 실행 → `asynccontextmanager`, FastAPI 관련 클래스 로드
4. `main.py`의 **Line 8** 실행 → `from app.routers.chat import router as chat_router`
5. **연쇄 import 시작**:
   - `routers/chat.py` 로드
   - `chat.py`가 `rag.py` import → `rag.py`가 `config.py` import → **`config.py` 전체 실행**
     - `.env` 로드, `GOOGLE_API_KEY` 검증, `embedder` 생성, ChromaDB 연결, `chroma_collection` 획득
   - `chat.py`가 `llm.py` import → **`llm.py` 전체 실행**
     - `Agent` 인스턴스 생성, `_sessions` TTLCache 생성
   - `chat.py`가 `post_reporter.py` import
6. 연쇄 import 종료, 제어가 `main.py`로 복귀
7. `main.py`의 **Line 11-13** 실행 → `lifespan` 함수 정의 (호출은 아직 안 됨)
8. `main.py`의 **Line 16** 실행 → `FastAPI(...)` 인스턴스 생성, `app` 변수에 저장
9. `main.py`의 **Line 18-23** 실행 → `CORSMiddleware`를 `app`에 등록
10. `main.py`의 **Line 25** 실행 → `chat_router`를 `/api` 접두사로 `app`에 등록 (= `POST /api/chat` 가능)
11. `main.py`의 **Line 27** 실행 → `/static`에 `front/` 정적 파일 서브 앱 마운트
12. `main.py`의 **Line 30-32** 실행 → `root()` 핸들러 데코레이터 등록 (= `GET /` 가능)
13. **`main.py` 실행 완료**, uvicorn이 모듈 import를 마침
14. uvicorn이 `app.router.lifespan_context`를 호출 → **`lifespan` 함수 진입**, `yield` 이전 코드 실행 (현재는 빈 상태라 즉시 `yield`)
15. uvicorn이 HTTP 서버를 열고 `8080` 포트에서 요청 대기 시작

### 요청 수신 시 (반복)

- **브라우저가 `/`로 접속** → `root()` 호출 → `front/index.html` 반환
- **브라우저가 `/static/app.js` 요청** → `StaticFiles` 서브앱이 `front/app.js` 반환
- **프론트가 `POST /api/chat` 호출** → CORS 미들웨어 통과 → `chat_router`의 `chat()` 핸들러 진입 → `rag.py` → `llm.py` → `post_reporter.py` 순으로 로직 실행 → 응답 반환

### 서버 종료 시 (한 번)

1. 터미널에서 `Ctrl+C` 누름
2. uvicorn이 종료 신호 수신
3. 진행 중이던 요청을 마저 처리
4. `lifespan` 함수의 `yield` **이후** 코드 실행 (현재는 없음)
5. 프로세스 종료

---

## 이 파일의 설계 의도 요약

| 개념 | 구현 방식 |
|------|----------|
| **엔트리포인트** | 모듈 최상단에 `app = FastAPI(...)` 변수 노출. uvicorn이 `app.main:app`로 집어감 |
| **조립 파일** | 로직은 전혀 없고, 라우터/미들웨어/정적 파일을 FastAPI 인스턴스에 "꽂기"만 함 |
| **연쇄 import 트리거** | `from app.routers.chat import ...` 한 줄로 `config.py`, `llm.py` 등이 줄줄이 초기화됨 |
| **수명 주기 훅 준비** | 현재는 비어있지만 `lifespan` 컨텍스트 매니저 자리를 미리 확보 (deprecated `on_event` 회피) |
| **정적 파일 + API 공존** | `/`는 HTML, `/static/*`은 정적 리소스, `/api/*`는 JSON API로 경로 분리 |
| **개발 편의 CORS** | `allow_origins=["*"]`로 느슨하게 열어 프론트/백엔드 혼합 개발 원활 |

---

## 핵심 정리

`main.py`는 Jarana 챗봇의 **"FastAPI 앱 조립 설명서"** 다. 실제 일하는 코드는 한 줄도 없고, 다음 세 가지만 한다:

1. **FastAPI 인스턴스 생성**: `app = FastAPI(title="Jarana Chatbot", lifespan=lifespan)`
2. **필요한 부품 등록**: CORS 미들웨어, `/api`용 chat 라우터, `/static` 정적 파일 마운트
3. **루트 페이지 핸들러**: `/`로 접속 시 `front/index.html` 반환

가장 중요한 포인트 세 가지:

- **`from app.routers.chat import router as chat_router` 한 줄이 전체 앱 초기화의 진짜 방아쇠**다. 이 한 줄 때문에 `config.py` → `rag.py` → `llm.py` 순서로 연쇄 import가 일어나면서 `embedder`, `chroma_collection`, `agent`, `_sessions` 같은 싱글톤 객체들이 전부 만들어진다. `main.py`는 이 모든 게 끝난 뒤에야 자기 코드를 이어서 실행한다.
- **`lifespan`은 지금 비어있지만 자리가 잡혀 있다**. 향후 연결 풀 정리나 백그라운드 태스크가 필요하면 여기에 추가하면 되고, deprecated된 `@app.on_event`로 회귀할 필요가 없다.
- **경로 설계가 명확하다**: `/`는 프론트 페이지, `/static/*`은 프론트 리소스, `/api/*`은 JSON API. 세 영역이 겹치지 않게 분리돼 있어서 추후 기능을 추가해도 충돌 없이 확장할 수 있다.

이 파일을 이해하면 `uvicorn app.main:app`을 입력한 순간부터 서버가 첫 요청을 받기까지 어떤 파일들이 어떤 순서로 초기화되는지가 전부 눈에 들어온다. 그 흐름의 시작점이자 종착점이 바로 이 `main.py`의 `app` 변수다.
