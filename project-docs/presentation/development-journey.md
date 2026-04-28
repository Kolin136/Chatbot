# Jarana Chatbot 개발 과정 정리 (발표용)

> **⚠️ 본 문서는 발표 시점의 개발 여정 기록입니다.** 발표 이후 Spring 서버 연동(문의/버그 자동 접수, `[POST_REPORT]` 마커, `post_reporter.py`, `SPRING_API_URL`, `report_submitted` 등)은 모두 제거되었습니다. 현재 구조는 `project-docs/architecture/ARCHITECTURE.md` 참고.

## 0. 최종 결과물 한 줄 요약

**영어 발음 연습 서비스 'Jarana'의 CS 챗봇** — FastAPI + PydanticAI(Gemini 3) + ChromaDB 기반, FAQ 답변 + 문의/버그 자동 접수 기능, 브라우저 채팅 UI 포함.

---

## 1. 시작 — 외부 AI가 만들어준 초기 기획서

처음에는 외부 AI(웹사이트 챗봇)에게 받은 `PROJECT_PLAN.md`를 그대로 들고 와서 Claude에게 전달했습니다. 핵심 내용:

- **목표**: 영어 발음 연습 서비스 전용 CS 챗봇 (FAQ 답변 + 버그 접수)
- **무상태(Stateless) 설계**: 챗봇 서버 내 RDBMS 미사용, 영구 저장은 기존 Spring API에 위임
- **스택**: Python 3.12+, FastAPI, **PydanticAI**, Gemini 3 Flash, ChromaDB, httpx
- **고도화된 RAG**: Summary-based Retrieval (요약본 검색 → 원본 텍스트로 답변 생성)
- **버그 접수**: PydanticAI의 `@agent.tool`로 Spring API 호출

이 기획서를 그대로 실행하기 전에, 직접 검토하면서 **여러 방향 수정**을 거쳤습니다.

---

## 2. 1차 방향 수정 — PydanticAI 에이전트 루프 제거

### 문제 인식

원래 기획서대로면 LLM이 `@agent.tool`로 정의된 `get_faq_info` 도구를 "스스로 판단해서" 호출해야 합니다. 그런데 이건 **확률적 동작**입니다 — LLM이 FAQ 검색이 필요하다고 판단 안 하면 그냥 자기 지식으로 답변해버릴 수 있습니다.

### 결정

**에이전트 루프 자체를 제거**하기로 했습니다:

- FastAPI 로직이 직접 흐름을 제어
- 매 요청마다 ChromaDB를 무조건 검색 → 결과를 LLM에 전달
- LLM은 그냥 "주어진 컨텍스트로 답변만" 생성
- 버그 감지는 LLM 응답의 `[POST_REPORT]` 마커 후처리 방식으로

→ 결과적으로 PydanticAI를 빼고 `google-genai` SDK 직접 호출로 V1을 만들었습니다.

---

## 3. Spring API 스펙 명시 + 알림 기능 제거

기존 기획에 있던 **네이버웍스/메일 알림 기능 삭제**, 대신 사용자가 알려준 실제 Spring API 스펙으로 변경:

- **엔드포인트**: `POST http://localhost:8000/board-service/api/v1/posts/save/3`
- **고정값**: `attachmentCode=""`, `boardNo=3`, `postsNo=-1`, `rangeCode=1`
- **동적값**: `postsCategory` (`"contents"` or `"technical"`), `postsTitle`, `postsContent`

`postsCategory`는 LLM이 판단:
- 콘텐츠 문의 → `contents`
- 버그/기술 문의 → `technical`

---

## 4. 임베딩 모델 결정

LLM은 Gemini 3 Flash로 결정 → 임베딩 모델도 같은 Google 생태계인 **Gemini Embedding** 사용. **API 키 1개로 LLM + 임베딩 둘 다** 호출 가능.

대안이었던 ChromaDB 기본 임베더(sentence-transformers)는 한국어 성능이 불확실해서 제외.

---

## 5. ChromaDB 독립 컨테이너로 분리

처음엔 ChromaDB `PersistentClient`(임베디드 모드)로 시작하려 했지만, 중간에 **독립 컨테이너로 띄우는 방향**으로 변경:

- `chromadb/chroma:latest` 이미지를 별도 컨테이너로 실행
- 챗봇은 `HttpClient`로 접속
- docker-compose로 두 컨테이너 관리

---

## 6. V1 구현 (Phase 1~6) — google-genai SDK 직접 호출 버전

6단계로 나눠서 구현했고, **각 Phase 완료 후 Codex로 검토**한 뒤 지적사항 수정:

| Phase | 내용 | 생성/수정 파일 |
|-------|------|---------------|
| 1 | 기반 파일 | `requirements.txt`, `.env`, `.gitignore`, 디렉토리 구조 |
| 2 | 설정 + 모델 | `app/config.py`, `app/models.py` |
| 3 | 핵심 로직 | `app/rag.py`, `app/llm.py`, `app/post_reporter.py` |
| 4 | API 레이어 | `app/routers/chat.py`, `app/main.py` |
| 5 | 인덱싱 스크립트 | `scripts/index_docs.py` |
| 6 | Docker | `Dockerfile`, `docker-compose.yml` |

### Codex 검토에서 발견되어 수정한 주요 이슈

- 정규식 `\{.*?\}` JSON 내부 `}` 만나면 잘림 → 수정
- 동기 함수를 async 엔드포인트에서 호출 → 이벤트 루프 블로킹 → `asyncio.to_thread()` 적용
- CORS `allow_origins=["*"]` + `allow_credentials=True` 충돌 → credentials 제거
- ChromaDB 메타데이터 크기 제한 → `MAX_RAW_TEXT_LENGTH=5000` 적용
- 인덱싱 스크립트 단일 실패 → 재시도 + 청크 단위 스킵
- `.env`가 Docker 이미지에 COPY되는 문제 → `.dockerignore` 추가
- ChromaDB 헬스체크 부재 → healthcheck 추가
- `CHROMA_HOST=localhost`가 컨테이너 내부에서 잘못 동작 → `environment`로 `chromadb` 서비스명 오버라이드

---

## 7. 2차 방향 수정 — 다시 PydanticAI로 (V2)

V1을 다 만든 뒤, 다시 검토하다가 의문 제기:

> "근데 LLM 호출도 파이덴틱이 제공해주는 메소드로 할수있는거 아니냐"

이전에 PydanticAI를 뺀 건 **에이전트 루프(도구 호출 판단)가 불필요해서**였지, LLM 호출 자체가 문제는 아니었습니다. PydanticAI는 도구 없이 단순 LLM 호출만으로도 쓸 수 있습니다. 이렇게 하면:

- 응답 검증을 Pydantic 모델로 자동화 가능
- 타입 안전성 증가
- 코드가 더 깔끔해짐

### 추가 발견 — PydanticAI는 임베딩도 지원

처음엔 "PydanticAI는 임베딩 미지원이라서 google-genai SDK는 유지해야 한다"고 생각했는데, 사용자의 지적으로 **공식 문서를 다시 확인**해보니 `Embedder` 클래스가 존재. → google-genai SDK 직접 호출 코드를 **전부 제거**할 수 있게 됐습니다.

### V2 마이그레이션 작업

| 파일 | 변경 내용 |
|------|----------|
| `requirements.txt` | `google-genai` 제거, `pydantic-ai[google]`, `cachetools` 추가 |
| `app/config.py` | `genai_client` 제거 → PydanticAI `Embedder` |
| `app/llm.py` | `Chat` 객체 → PydanticAI `Agent` + `message_history` 수동 관리 + `TTLCache(30분)` + `history_processors` |
| `app/rag.py` | `genai.embed_content` → `embedder.embed_query()`, 동기→비동기 |
| `app/routers/chat.py` | `asyncio.to_thread()` 래핑 제거 (rag.py가 이제 비동기) |
| `scripts/index_docs.py` | `genai` → `Agent.run_sync()`(요약) + `Embedder.embed_documents()`(임베딩) |

### V1 보존

V1 구현 계획은 폐기하지 않고 `project-docs/plans/PLAN_V1_COMPLETED.md`로 별도 보존했습니다. 나중에 비교/롤백이 필요할 때 참고용.

---

## 8. 세션 TTL 도입

PydanticAI 전환 중에 별도 이슈도 같이 처리:

- 기존: 세션이 인메모리 dict에 무한 누적 → 메모리 누수 위험
- 변경: `cachetools.TTLCache(maxsize=100, ttl=1800)` 사용
  - 30분 미활동 시 세션 자동 만료
  - 최대 100개 동시 세션 (초과 시 LRU 제거)

또한 **`history_processors`**로 대화 길이를 최근 10턴으로 제한 → 컨텍스트 윈도우 초과 방지.

---

## 9. 프론트엔드 채팅 UI 작성

API 테스트만으로는 실제 동작 확인이 어려워서, **간단한 채팅 UI**를 직접 만들어 붙였습니다:

- `front/index.html`, `front/style.css`, `front/app.js` (vanilla JS, 프레임워크 없음)
- 디자인 방향: **AI스러운 보라색 금지**, 실제 고객센터 채팅 느낌 (네이비/파랑 톤)
- `app/main.py`에 `StaticFiles` 마운트해서 `/`로 접속하면 채팅 UI 표시

### 발견된 문제 + 즉시 수정

1. **한글 IME 입력 시 마지막 글자가 따로 전송되는 버그** — `e.isComposing` + `keyCode 229` 가드 추가
2. **LLM 응답에 마크다운 `**` 기호가 그대로 표시되는 문제** — 시스템 프롬프트에 "마크다운 금지" 규칙 추가

---

## 10. 실제 환경에서 테스트

### 의존성 설치 + ChromaDB 컨테이너 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
docker compose up chromadb -d
```

### 인덱싱 스크립트 실행 시 문제 발생

처음 인덱싱 시도 시 **Gemini API 무료 티어 quota 초과** (분당 5 요청 제한) — `gemini-2.5-flash`로 시도 중이었음.

### 모델 변경

발표 거리: **"기획서엔 Gemini 3 Flash라고 적혀있었는데 실제 구현에선 2.5 Flash로 잘못 들어가 있던 것"** 발견. 변경:

- LLM: `gemini-2.5-flash` → `gemini-3.1-flash-lite-preview` (가장 가벼운 3.x 시리즈)
- 임베딩: `gemini-embedding-001` → `gemini-embedding-2-preview` (최신 멀티모달)
- 인덱싱 스크립트의 요청 간격: 0.5초 → 13초 (rate limit 회피)

### 인덱싱 성공

20개 청크 → 요약 20개 → 임베딩 20개 → ChromaDB 저장 20개 모두 성공.

### 브라우저 테스트

`http://localhost:8080/` 접속해서 실제 채팅 동작 확인:
- 발음 점수 기준 질문 → RAG 기반 정확한 답변
- "내 이름은 철수다" → "내 이름이 뭐게?" 질문 → **개인정보 거절** (의도된 동작 — CS 챗봇이 사용자 개인정보를 알아선 안 됨)
- 버그 신고 메시지 → `[POST_REPORT]` 마커 정상 동작

---

## 11. PydanticAI 전환 후 Codex 재검토

V1 단계에서는 각 Phase 마다 Codex 검토를 했지만, V2(PydanticAI 전환) 이후 검토를 안 한 게 마음에 걸려서 **다시 Codex로 전체 검토**.

### 결과: 51건 발견

- 51건 중 **현실적으로 의미 있는 17건**만 추려내고 나머지는 무시
  - 무시 사유: 의도된 fail-fast, 1회성 스크립트라 무관, 프론트 버튼 비활성화로 동시 요청 불가 등
- 17건을 HIGH/MEDIUM/LOW 3단계로 분류해서 전부 수정

### 핵심 수정사항 (HIGH 3건)

1. **`llm.py keep_recent` 시스템 프롬프트 손실 방지** — 대화 10턴 넘으면 첫 메시지(시스템 프롬프트)가 잘려나가 LLM이 역할 망각 → `[messages[0]] + messages[-9:]`로 첫 메시지 항상 보존
2. **`rag.py` 이벤트 루프 블로킹 해결** — 동기 ChromaDB 호출을 `asyncio.to_thread()`로 감싸서 다른 요청 stall 방지
3. **`chat.py` 단계별 에러 핸들링** — RAG/LLM/Spring 어느 단계 실패해도 graceful degradation

---

## 12. 서비스 외 질문 차단 분석 (개선 후보)

**현재**: 시스템 프롬프트만으로 차단 (확률적, 약함)

**PydanticAI가 제공하는 더 강력한 메커니즘 4가지**를 공식 문서에서 확인:
1. **Union Output Type** — `output_type=[ServiceAnswer, OutOfScope]`로 타입 자체로 분기
2. **Output Validator + ModelRetry** — 응답 후 검증, 실패 시 LLM 재시도
3. **Router Agent Pattern** — 분류 전용 에이전트로 카테고리 분기
4. **Lifecycle Hooks (Capabilities, Agent.iter)** — 모델 호출 가로채기

→ 분석 결과를 `project-docs/issues/off-topic-blocking-analysis.md`로 정리. **이번 발표 후 개선 후보**로 남겨둔 상태.

---

## 13. 최종 디렉토리 구조

```
jarana-chatbot/
├── .dockerignore
├── .env                           # API 키, 환경변수 (git 제외)
├── .gitignore
├── Dockerfile
├── docker-compose.yml             # chatbot + chromadb 2개 컨테이너
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── config.py                  # PydanticAI Embedder + ChromaDB 클라이언트
│   ├── models.py                  # Pydantic 데이터 모델
│   ├── rag.py                     # RAG 검색 (PydanticAI Embedder)
│   ├── llm.py                     # PydanticAI Agent + 세션 TTL
│   ├── post_reporter.py           # [POST_REPORT] 마커 처리 + Spring 호출
│   ├── main.py                    # FastAPI 앱
│   └── routers/
│       └── chat.py                # /api/chat 엔드포인트
├── scripts/
│   └── index_docs.py              # 1회성 인덱싱 스크립트
├── docs/                          # RAG 소스 문서
│   └── jarana_guide.txt
├── front/                         # 채팅 UI
│   ├── index.html
│   ├── style.css
│   └── app.js
└── project-docs/                  # 프로젝트 문서
    ├── architecture/
    │   └── ARCHITECTURE.md
    ├── plans/
    │   ├── PROJECT_PLAN.md        # 외부 AI 초기 기획서
    │   └── PLAN_V1_COMPLETED.md   # V1 (google-genai 직접) 보존본
    ├── issues/
    │   └── off-topic-blocking-analysis.md
    └── presentation/
        └── development-journey.md  # 이 문서
```

---

## 14. 핵심 의사결정 타임라인 요약 (회의 발표용)

| 순서 | 결정 | 이유 |
|------|------|------|
| 1 | 외부 AI 기획서 그대로 안 따름 | Claude와 검토하면서 더 단순/안전한 방향으로 바꿈 |
| 2 | PydanticAI 에이전트 루프 제거 (V1) | LLM의 도구 호출 판단이 확률적이라 신뢰성 낮음 |
| 3 | 마커 기반 버그 접수 (`[POST_REPORT]`) | 도구 호출 대신 응답 후처리로 확실히 잡음 |
| 4 | Spring 알림 기능 제거 | Spring 측에서 처리하므로 챗봇 책임 분리 |
| 5 | Gemini 임베딩 채택 | API 키 1개로 LLM + 임베딩 통합, 한국어 성능 |
| 6 | ChromaDB 독립 컨테이너 | 데이터 격리, 운영 분리 |
| 7 | 각 Phase 완료 후 Codex 검토 | 품질 게이트, 사후 발견 비용 절감 |
| 8 | **다시 PydanticAI 도입 (V2)** | 단순 LLM 호출만 할 거면 PydanticAI가 더 깔끔, 임베딩까지 통합 가능 |
| 9 | 세션 TTL 도입 (`cachetools.TTLCache`) | 인메모리 세션 무한 누적 방지 |
| 10 | 프론트엔드 채팅 UI 직접 작성 | 실제 동작을 눈으로 확인 |
| 11 | Gemini 모델 버전 업데이트 | 2.5 Flash → 3.1 Flash Lite, 임베딩도 v2 preview |
| 12 | V2 Codex 재검토 + 17건 수정 | V2 마이그레이션 후 미점검 상태 보완 |
| 13 | 서비스 외 질문 차단 한계 인식 | 시스템 프롬프트만으로는 약함, 개선 방안 문서화 |

---

## 15. 회의에서 강조할 포인트

### 잘 한 부분
- **방향 수정을 두려워하지 않음**: V1을 다 만든 후 V2로 갈아엎는 결정을 내림. 매몰비용에 끌려가지 않음.
- **각 단계별 Codex 검증**: 사람 눈으로 못 잡는 동시성/예외 처리 이슈를 자동 검토로 잡음.
- **외부 의존성 최소화**: PydanticAI 하나로 LLM + 임베딩 통합, 직접 SDK 호출 전부 제거.
- **실제 동작 검증**: 채팅 UI 만들어서 사용자 시점에서 반복 테스트.

### 개선 여지
- **서비스 외 질문 차단**: 현재는 시스템 프롬프트만 사용 → PydanticAI의 Union output type, Validator 등으로 강화 가능.
- **세션 영속화**: 현재는 인메모리, 서버 재시작 시 소멸 → 필요 시 Redis 등으로 외부화.
- **Gemini 무료 티어 한계**: 인덱싱 시 rate limit으로 sleep을 길게 줘야 함 → 유료 티어 또는 더 가벼운 모델로 대응.
- **Spring 서버 의존**: 문의 접수가 Spring API에 묶여 있어서 Spring 다운 시 접수 불가 → 큐잉 시스템 도입 검토 가능.

### 데모 시연 포인트
1. `http://localhost:8080/` 접속 → 채팅 UI 표시
2. "발음 점수는 어떻게 매겨지나요?" → RAG 기반 정확한 답변 데모
3. "녹음하면 앱이 자꾸 꺼져요" → 안심 메시지 + "✓ 문의 접수 완료" 뱃지 + Spring API로 게시글 자동 등록 데모
4. "내 이름이 뭐게?" → 서비스 무관 질문 거절 데모
5. 같은 세션 ID로 연속 대화 → 맥락 유지 데모
