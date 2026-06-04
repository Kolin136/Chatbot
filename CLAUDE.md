# 프로젝트: Jarana Chatbot

PDF 기반 RAG 챗봇. 사용자가 PDF를 업로드하면 자동으로 청킹·임베딩되어 벡터 DB에 적재되고, 그 위에서 자연어 질의응답이 가능.

## 기술 스택
- Python 3.10, FastAPI, asyncio, httpx
- **Docling**: PDF → 구조화 객체. layout 비전 모델 + TableFormer(표) + DocumentFigureClassifier(그림 분류). `AcceleratorOptions(device=CPU)` 강제(Apple Silicon MPS float64 미지원 회피).
- **LangChain SemanticChunker** (`langchain_experimental`): 임베딩 유사도 기반 의미 단위 청킹 전략 (Docling Hybrid와 선택 가능)
- **LM Studio** (OpenAI 호환 REST 백엔드): Chat/VLM = `google/gemma-4-e4b`, 임베딩 = `text-embedding-multilingual-e5-large-instruct` (1024차원)
- **pydantic_ai** `Agent` + `OpenAIChatModel` + `OpenAIProvider(base_url=LM Studio)` — Chat/VLM 호출
- 자체 `LMStudioEmbedder` — `httpx`로 `/v1/embeddings` 직접 호출, 매 호출마다 새 `AsyncClient`
- **ChromaDB** HttpClient (별도 컨테이너). 컬렉션은 고정 인스턴스 없이 매 호출 시 `get_or_create_collection(...)`으로 동적 접근
- 프론트: React UMD CDN + babel inline (빌드 없음, `front/`에서 정적 서빙)

## 아키텍처 규칙
- **CRITICAL**: 호스트/포트/모델 ID 일체 코드에 박지 말 것. **`.env` → `app/config.py` 단일 진입점**만 사용. 데스크탑 위치/포트 바뀌면 `.env`만 수정.
- **CRITICAL**: ChromaDB 메타에 `raw_text`를 어떤 모드든 채울 것. `app/rag.py:74`가 `meta.get("raw_text") or doc`로 우선 사용 — `raw_text` 빠지면 LLM 답변 컨텍스트가 깨짐.
- **CRITICAL**: `app/main.py` 최상단에 `os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")`을 **다른 모든 import보다 먼저** 둘 것. PyTorch import 후엔 적용 안 됨.
- 컬렉션은 동적. 고정 인스턴스 만들지 말고 `chroma_client.get_or_create_collection(name=...)`으로 호출 시점에 잡기.
- `text` vs `contextualized_text` 분리 유지 — 임베딩 입력은 `contextualized_text`, LLM 컨텍스트는 `text`.
- VLM 자연어 설명문은 통합 텍스트에 인라인 삽입("이 문서에 그림이 하나 있다. 그 설명: ...") — SemanticChunker가 이미지/표를 의미 단위로 흡수하도록.
- LangChain SemanticChunker의 sync `embed_documents`는 `asyncio.to_thread`로 별도 스레드에서 실행 → 메인 loop에 코루틴을 `run_coroutine_threadsafe`로 던지는 패턴(`app/chunking/strategies/langchain/semantic/embeddings_adapter.py`) 유지.
- `LMStudioEmbedder`는 매 호출마다 새 `httpx.AsyncClient(...)`. 모듈 레벨 인스턴스 금지 (복잡한 dispatch 환경에서 broken pool state 발생).

## 디렉터리 구조 (요지)
- `app/` — FastAPI + 청킹 + RAG + 임베딩
  - `app/config.py` — `.env`에서 모든 외부 서비스 설정 로드. `embedder`, `chat_model`, `chroma_client` 단일 인스턴스
  - `app/main.py` — uvicorn 진입점. 최상단에 PyTorch MPS fallback env 설정
  - `app/routers/` — upload / embed / chat / collections
  - `app/rag.py` — 검색. `metadata.raw_text` 우선
  - `app/llm.py` — Agent 정의 + 대화 히스토리 TTL 캐시
  - `app/embeddings/lmstudio.py` — LM Studio 임베딩 HTTP 클라이언트
  - `app/chunking/` — Docling 변환 + VLM + 전략 분기 (Hybrid / Semantic)
- `front/` — React SPA (빌드 없음, 정적 서빙)
- `chunking-results/` — PDF 업로드 후 변환된 산출물 (원본 PDF, markdown, chunks.jsonl, 이미지/표, mapping.json). `.gitignore` 처리됨
- `docs/` — 프로젝트 문서 (ARCHITECTURE/ADR/PRD/UI_GUIDE + plan 문서들)
- `project-docs/` — code-explainer 에이전트가 생성하는 라인 단위 코드 해석 마크다운

## 개발 프로세스
- **plan-first**: 새 기능/리팩터링은 Claude의 plan mode로 설계 → 사용자 승인 → 실행. plan 문서는 `docs/`에 적치해 이력화.
- **커밋 메시지**: Conventional Commits 형식 (한국어 본문 OK). 예: `feat: 임베딩 시 LLM 요약을 UI 토글로 선택 가능하게 변경`, `refactor: 청킹 산출물 디렉터리 docs/ → chunking-results/ 리네임`
- 임시 진단 코드는 디버깅 끝나면 별도 커밋으로 정리.

## .env 필수 키 (예시)
```env
LMSTUDIO_BASE_URL=http://<desktop-ip>:1369/v1
EMBEDDING_MODEL=text-embedding-multilingual-e5-large-instruct
CHAT_MODEL=google/gemma-4-e4b
CHROMA_HOST=localhost
CHROMA_PORT=8001
DOCLING_DEVICE=cpu
PYTORCH_ENABLE_MPS_FALLBACK=1
```

## 자주 쓰는 명령
```bash
.venv/bin/uvicorn app.main:app                       # 개발 서버 (운영도 동일)
.venv/bin/pip install -r requirements.txt            # 의존성 설치
.venv/bin/python test.py                             # LM Studio 연결 smoke test
.venv/bin/python -c "from app.config import embedder; print(type(embedder).__name__)"  # config import 검증
```

## 알려진 함정
- **VS Code 내장 터미널의 macOS 로컬 네트워크 권한 누락** — uvicorn을 VS Code 터미널에서 띄우면 LAN의 LM Studio로 outbound가 `EHOSTUNREACH`로 즉시 실패. 시스템 설정 → 개인정보 보호 및 보안 → 로컬 네트워크에서 VS Code 허용 필요. 일반 Terminal.app/iTerm2에선 문제 없음.
- **LM Studio rerank API 없음** — `jina-reranker-v3`를 로드해도 호출할 표준 endpoint 없음 (Feature Request #521 Open). reranker는 별도 llama.cpp server 또는 노트북 자체 sentence-transformers로 처리해야 함.
- **임베딩 모델 max_context=512 토큰** — 청크가 그보다 길면 LM Studio가 자동 잘라 임베딩 → 잘린 뒷부분 정보 매칭에 미반영. 답변엔 영향 없음(rag.py가 metadata.raw_text 우선 사용).
- **pydantic_ai 1.77의 `Agent(history_processors=[...])` deprecation 경고** — 동작은 정상. 새 패턴은 `capabilities=[ProcessHistory(...)]` 또는 `Hooks(before_model_request=...)`.
