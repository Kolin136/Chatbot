# Jarana Chatbot - 프로젝트 구축 계획서

> **⚠️ 이 문서는 V1 시점의 계획 보존본입니다.** Spring 서버 연동(버그/문의 게시글 자동 등록, `[POST_REPORT]` 마커, `post_reporter.py`, `SPRING_API_URL` 등)은 이후 제거되었습니다. 현재 구조는 `project-docs/architecture/ARCHITECTURE.md`를 참고하세요.

## 1. 프로젝트 개요

### 1.1 목표
- **영어 발음 연습 서비스 전용 CS 에이전트** 개발
- 두 가지 핵심 기능:
  - **FAQ 답변**: 가이드 문서 기반 사용자 질문 응답
  - **버그/에러 접수**: 사용자가 신고한 에러를 접수하고 Spring 서버로 전달

### 1.2 아키텍처 원칙

#### 무상태(Stateless) 설계
- 챗봇 서버 내 RDBMS(MySQL)는 **일절 사용하지 않음**
- 대화 맥락(컨텍스트)은 **Gemini 3의 세션/스레드 ID**로 관리
- 영구 데이터 저장은 **기존 Spring API 서버에 위임**

#### 단순 직통 구조 (에이전트 루프 없음)
- PydanticAI 에이전트 루프를 사용하지 않음
- LLM이 도구 호출 여부를 판단하는 방식 배제
- **FastAPI 애플리케이션 로직이 흐름을 직접 제어**:
  - ChromaDB 검색 → 항상 실행
  - Gemini 3 호출 → 검색된 원본 + 사용자 질문을 함께 전달
  - 문의/버그 감지 → Gemini 3 응답 후처리로 판별

#### 고도화된 RAG 전략
- **Summary-based Retrieval** 전략 채택
- 요약본(Summary)으로 검색하고, 원본(Raw Text)으로 답변 생성
- 단순 청크 저장/검색 방식 지양

---

## 2. 기술 스택

| 역할 | 기술 | 비고 |
|------|------|------|
| Language | Python 3.12+ | |
| Web Framework | FastAPI | 비동기 웹서버 |
| LLM | **Gemini 3 Flash** | 추론, 답변 생성, 인덱싱 시 요약 |
| Embedding | **Gemini Embedding** (text-embedding-004) | 텍스트 → 벡터 변환 |
| SDK | google-genai | LLM + Embedding 모두 이 SDK로 호출 |
| Vector DB | ChromaDB | Persistent 모드 (임베디드) |
| HTTP Client | httpx | Spring API 비동기 통신 |
| 타입 검증 | Pydantic (FastAPI 내장) | 요청/응답 모델 |
| 환경변수 관리 | python-dotenv | .env 파일 로드 |

> **PydanticAI 제거 사유**: 에이전트 루프(LLM이 도구 호출 판단)가 이 프로젝트에서 불필요. FAQ는 항상 ChromaDB를 검색하면 되고, 버그 감지는 응답 후처리로 충분. LLM의 판단에 맡기면 오히려 불확실성만 증가.

### 2.1 API 키 및 환경변수 관리

모든 민감 정보는 `.env` 파일에서 관리하며, **`.gitignore`에 등록하여 git에 절대 포함되지 않도록** 한다.

```env
# .env
GOOGLE_API_KEY=your-google-api-key-here    # Gemini 3 Flash + Gemini Embedding 공용 (1개)
SPRING_API_URL=http://your-spring-server   # Spring 서버 주소
```

> **참고**: Google API 키 1개로 Gemini 3 Flash(LLM)와 Gemini Embedding(임베딩) 모두 호출 가능. 별도 키 불필요.

---

## 3. 핵심 흐름

### 전체 요청 처리 흐름

```
사용자 메시지
    ↓
FastAPI /chat 엔드포인트
    ↓
① ChromaDB 검색 (항상 실행)
   - 사용자 질문 → 요약본 벡터 유사도 검색
   - 매칭된 원본 텍스트(Raw Text) 추출
    ↓
② Gemini 3 호출
   - 시스템 프롬프트 + 원본 텍스트(컨텍스트) + 사용자 질문 전달
   - 세션 ID로 대화 기록 유지
   - 버그 신고 시 응답에 [POST_REPORT] 마커 포함하도록 지시
    ↓
③ 응답 후처리
   - Gemini 3 응답에서 [POST_REPORT] 마커 확인
   - 마커 있으면 → httpx로 Spring API 비동기 호출 (백그라운드)
   - 마커 제거 후 사용자에게 깔끔한 응답 반환
```

---

## 4. 핵심 기능 구현 상세

### 4-A. 고성능 RAG 시스템 (Summary-to-Raw Mapping)

#### 4-A-1. 인덱싱 단계 (사전 준비, 1회성 실행)

1. **문서 분할**
   - `docs/` 폴더에 있는 가이드 문서를 읽어들임
   - 단락별로 분할하여 Raw Chunk 생성

2. **요약 및 키워드 추출**
   - 각 Raw Chunk를 Gemini 3에 전달
   - LLM이 해당 청크의 **요약(Summary)** 생성
   - LLM이 해당 청크의 **핵심 키워드** 추출

3. **ChromaDB 저장**
   - **벡터로 저장되는 것**: 요약본(Summary)
   - **메타데이터에 매핑 저장되는 것**: 원본 텍스트(Raw Text)
   - 즉, 검색은 요약본 벡터로 하되, 실제 데이터는 원본이 함께 저장됨

#### 4-A-2. 검색 단계 (매 요청마다 항상 실행)

1. 사용자의 질문을 임베딩
2. ChromaDB에 저장된 **요약본 벡터**와 유사도 비교
3. 가장 유사한 항목(들)의 **원본 텍스트(Raw Text)** 추출

#### 4-A-3. 생성 단계 (답변 생성)

1. 추출된 원본 텍스트를 컨텍스트로 포함
2. 시스템 프롬프트 + 컨텍스트 + 사용자 질문을 Gemini 3에 전달
3. Gemini 3가 원본 기반으로 **상세하고 정확한 답변** 생성

> **핵심 포인트**: 요약본은 검색 정확도를 높이는 인덱스 역할, 실제 답변 생성은 원본 텍스트 기반

---

### 4-B. 버그/문의 접수 워크플로우

#### 4-B-1. Gemini 3 시스템 프롬프트에 지시

시스템 프롬프트에 다음 규칙을 포함:
- 사용자가 버그 신고 또는 문의를 하는 경우, 안심 메시지와 함께 응답 끝에 마커를 포함할 것
- 마커 형식:
  ```
  [POST_REPORT]{"postsCategory": "technical", "postsTitle": "제목", "postsContent": "내용"}[/POST_REPORT]
  ```
- `postsCategory` 판별 기준:
  - **콘텐츠 관련 문의** → `"contents"` (예: 발음 콘텐츠 오류, 학습 자료 문의 등)
  - **버그/기술 문의** → `"technical"` (예: 앱 크래시, 기능 오작동 등)
- `postsTitle`: Gemini가 사용자 메시지를 요약하여 제목 생성
- `postsContent`: 사용자가 설명한 내용을 정리하여 본문 생성

#### 4-B-2. Spring API 호출 스펙

- **엔드포인트**: `POST http://localhost:8000/board-service/api/v1/posts/save/3`
- **요청 바디 (JSON)**:

```json
{
  "attachmentCode": "",
  "boardNo": 3,
  "postsCategory": "technical",
  "postsContent": "녹음 버튼을 누르면 앱이 종료됩니다.",
  "postsNo": -1,
  "postsTitle": "녹음 시 앱 종료 현상",
  "rangeCode": 1
}
```

| 필드 | 값 | 설명 |
|------|-----|------|
| `attachmentCode` | `""` (빈 문자열 고정) | 첨부파일 없음 |
| `boardNo` | `3` (고정) | 게시판 번호 |
| `postsCategory` | `"contents"` 또는 `"technical"` | 콘텐츠 문의 / 버그 문의 |
| `postsContent` | Gemini가 생성 | 문의 내용 본문 |
| `postsNo` | `-1` (고정) | 새 글 작성 |
| `postsTitle` | Gemini가 생성 | 문의 제목 |
| `rangeCode` | `1` (고정) | 공개 범위 |

#### 4-B-3. FastAPI 응답 후처리

1. Gemini 3의 응답 텍스트에서 `[POST_REPORT]...[/POST_REPORT]` 마커 파싱
2. 마커가 존재하면:
   - 마커 내 JSON에서 `postsCategory`, `postsTitle`, `postsContent` 추출
   - 고정값(`attachmentCode`, `boardNo`, `postsNo`, `rangeCode`)과 합쳐서 요청 바디 구성
   - httpx로 Spring API **비동기 호출** (백그라운드)
   - 응답에서 마커 부분 제거 후 깔끔한 메시지만 사용자에게 반환
3. 마커가 없으면: 그대로 사용자에게 반환

#### 4-B-4. 예시 흐름

```
사용자: "녹음하면 앱이 자꾸 꺼져요"
    ↓
ChromaDB 검색 → (관련 문서 있으면 포함, 없으면 빈 컨텍스트)
    ↓
Gemini 3 응답:
  "불편을 드려 죄송합니다. 해당 문제를 접수했으며 빠른 시일 내에 수정하겠습니다.
   [POST_REPORT]{"postsCategory":"technical","postsTitle":"녹음 시 앱 종료 현상","postsContent":"녹음 버튼을 누르면 앱이 종료됩니다."}[/POST_REPORT]"
    ↓
FastAPI 후처리:
  - [POST_REPORT] 마커 감지
  - Spring API로 전송:
    {"attachmentCode":"","boardNo":3,"postsCategory":"technical",
     "postsContent":"녹음 버튼을 누르면 앱이 종료됩니다.",
     "postsNo":-1,"postsTitle":"녹음 시 앱 종료 현상","rangeCode":1}
  - 마커 제거 후 사용자에게 전달:
    "불편을 드려 죄송합니다. 해당 문제를 접수했으며 빠른 시일 내에 수정하겠습니다."
```

---

## 5. 구현 단계별 상세 미션

### Step 1: 프로젝트 초기화

- [ ] `requirements.txt` 생성
  - `fastapi`
  - `uvicorn`
  - `google-genai`
  - `chromadb`
  - `httpx`
  - `python-dotenv`
- [ ] `.env` 파일 템플릿 생성 (Gemini 3 API 키, Spring API URL 등)
- [ ] Gemini 3 API 클라이언트 설정
- [ ] ChromaDB `PersistentClient` 설정 및 초기화
- [ ] Dockerfile + docker-compose.yml 작성
- [ ] 프로젝트 디렉토리 구조 생성

### Step 2: 고도화된 인덱싱 스크립트 작성

- [ ] `docs/` 폴더 내 가이드 문서 읽기 로직
- [ ] 문서 → 단락별 분할(Raw Chunk) 로직
- [ ] 각 Raw Chunk → Gemini 3 요약 + 키워드 추출 로직
- [ ] ChromaDB에 요약본 벡터 저장 + 메타데이터에 원본 매핑 저장 로직
- [ ] 인덱싱 스크립트 실행 엔트리포인트

### Step 3: 핵심 서비스 로직 구현

- [ ] RAG 검색 모듈: ChromaDB에서 질문으로 원본 텍스트 검색/반환
- [ ] Gemini 3 호출 모듈: 시스템 프롬프트 + 컨텍스트 + 질문 조합하여 호출
- [ ] 시스템 프롬프트 작성
  - CS 에이전트 역할 정의
  - 반드시 제공된 컨텍스트 기반으로만 답변하도록 지시
  - 버그 신고 시 [POST_REPORT] 마커 포함 규칙 명시
- [ ] 응답 후처리 모듈: [POST_REPORT] 마커 파싱 + Spring API 호출 + 마커 제거
- [ ] 세션 관리: Gemini 3 세션/스레드 ID 기반 대화 기록 유지

### Step 4: API 엔드포인트 구현

- [ ] `/chat` 엔드포인트 구현
  - 요청: `session_id`, `user_message`, `user_info`
  - 처리: ChromaDB 검색 → Gemini 호출 → 후처리 → 응답
  - 응답: `response_message`, `session_id`
- [ ] 요청/응답 Pydantic 모델 정의 (엄격한 타입 체크)
- [ ] 에러 핸들링 및 응답 포맷 통일

---

## 6. 예상 프로젝트 구조

```
jarana-chatbot/
├── PROJECT_PLAN.md          # 이 계획서
├── requirements.txt         # Python 의존성
├── .env                     # 환경변수 (API 키 등)
├── Dockerfile
├── docker-compose.yml
├── docs/                    # 가이드 문서 (RAG 소스)
│   └── *.md / *.txt
├── scripts/
│   └── index_docs.py        # 인덱싱 스크립트
├── app/
│   ├── main.py              # FastAPI 앱 엔트리포인트
│   ├── config.py            # 설정 (환경변수, ChromaDB, Gemini 등)
│   ├── rag.py               # RAG 검색 로직 (ChromaDB 조회)
│   ├── llm.py               # Gemini 3 호출 로직
│   ├── bug_detector.py      # [POST_REPORT] 마커 파싱 + Spring API 호출
│   ├── models.py            # Pydantic 요청/응답 모델
│   └── routers/
│       └── chat.py          # /chat 엔드포인트 라우터
└── chroma_data/             # ChromaDB 영속 데이터 (volume 마운트)
```

---

## 7. 외부 연동 정보

### Spring API 서버
- 문의/버그 접수 엔드포인트: `POST http://localhost:8000/board-service/api/v1/posts/save/3`
- 전송 데이터: 게시글 형태의 JSON (4-B-2 참조)

### Gemini 3 Flash
- 역할 1: RAG 인덱싱 시 요약 + 키워드 추출 (인덱싱 스크립트)
- 역할 2: 사용자 질문에 대한 답변 생성 (컨텍스트 기반)
- 역할 3: 문의/버그 감지 시 [POST_REPORT] 마커 포함 응답
- 대화 맥락: 세션/스레드 ID 기반 관리
