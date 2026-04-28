# Jarana Chatbot

FastAPI + ChromaDB + Google Gemini 기반의 RAG 챗봇 서비스. `docs/` 폴더의 문서를 인덱싱해 사용자 질문에 컨텍스트 기반 답변을 제공한다.

## 주요 구성

- **Backend**: FastAPI (`app/`)
- **Vector Store**: ChromaDB
- **LLM / Embedding**: Google Gemini (`pydantic-ai` 사용)
- **Frontend**: 정적 HTML/JS (`front/`)

## 디렉토리 구조

```
jarana-chatbot/
├── app/                # FastAPI 애플리케이션
│   ├── main.py         # 진입점 (FastAPI 앱)
│   ├── config.py       # 환경변수 / Chroma / Embedder 초기화
│   ├── llm.py          # LLM 호출 로직
│   ├── rag.py          # 검색 증강 생성 (RAG)
│   ├── models.py       # Pydantic 모델
│   └── routers/        # API 라우터
├── front/              # 정적 프론트엔드
├── docs/               # 인덱싱 대상 문서 (.md, .txt)
├── scripts/
│   └── index_docs.py   # 문서 인덱싱 스크립트
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## 사전 요구사항

- Python 3.12+
- Docker / Docker Compose (권장)
- Google Gemini API Key

## 환경변수 설정

프로젝트 루트에 `.env` 파일 생성:

```env
GOOGLE_API_KEY=your_google_api_key_here

# 선택 항목 (기본값 있음)
GEMINI_MODEL=google-gla:gemini-3-flash-preview
EMBEDDING_MODEL=google-gla:gemini-embedding-2-preview
CHROMA_HOST=localhost
CHROMA_PORT=8001
```

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `GOOGLE_API_KEY` | Google Gemini API Key (**필수**) | - |
| `GEMINI_MODEL` | 사용할 Gemini 모델 | `google-gla:gemini-3-flash-preview` |
| `EMBEDDING_MODEL` | 임베딩 모델 | `google-gla:gemini-embedding-2-preview` |
| `CHROMA_HOST` | ChromaDB 호스트 | `localhost` |
| `CHROMA_PORT` | ChromaDB 포트 | `8001` |

## 실행 방법

### 1. Docker Compose (권장)

ChromaDB와 챗봇 서버를 한 번에 띄운다.

```bash
docker compose up --build
```

- 챗봇: http://localhost:8080
- ChromaDB: http://localhost:8001

종료:

```bash
docker compose down
```

데이터 포함 완전 삭제:

```bash
docker compose down -v
```

### 2. 로컬 실행

**(1) 의존성 설치**

```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**(2) ChromaDB 실행**

```bash
docker run -d --name chromadb -p 8001:8000 chromadb/chroma:latest
```

**(3) FastAPI 서버 실행**

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

- `--reload`: 코드 변경 시 자동 재시작 (개발용)
- 접속: http://localhost:8080

## 문서 인덱싱

`docs/` 폴더의 `.md`, `.txt` 파일을 ChromaDB에 인덱싱한다. 챗봇이 RAG로 답변하려면 최초 1회 실행이 필요하다.

```bash
# 로컬 실행 시
python -m scripts.index_docs

# Docker 환경에서 실행 시
docker compose exec chatbot python -m scripts.index_docs
```

인덱싱 단계:
1. `docs/` 폴더에서 문서 읽기
2. 단락 단위로 청크 분할
3. Gemini로 청크 요약 생성
4. 임베딩 생성
5. ChromaDB에 저장

> 참고: 요청 한도를 고려해 청크당 약 13초의 지연이 있어 문서가 많으면 시간이 소요된다.

## API 엔드포인트

서버 실행 후 자동 생성되는 OpenAPI 문서:

- Swagger UI: http://localhost:8080/docs
- ReDoc: http://localhost:8080/redoc

| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/` | 프론트엔드 페이지 |
| `POST` | `/api/chat` | 채팅 요청 |

## 개발 팁

- 라우터는 `app/routers/` 아래에 추가하고 `app/main.py`에서 `include_router`로 등록한다.
- 프론트 코드는 `front/index.html`, `front/app.js`, `front/style.css`를 직접 수정한다 (정적 마운트됨).
- ChromaDB 데이터는 Docker volume `chroma_data`에 저장된다.

## 라이선스

추후 추가 예정.
