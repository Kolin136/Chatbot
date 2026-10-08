# PDF 기반 로컬 RAG 챗봇

PDF를 업로드하면 자동으로 청킹·임베딩되어 벡터 DB에 적재되고,
그 위에서 자연어 질의응답이 가능하다. 채팅·임베딩·이미지/표 설명(VLM)은 **로컬 LM Studio**에서
처리한다. **문서가 외부 API로 전송되는 경로가 없다.**

## 핵심 기능

- **PDF 업로드 → 자동 파이프라인**: Docling으로 PDF 파싱 → 이미지/표를 VLM으로 자연어 설명 생성 → 청킹 → 임베딩 → ChromaDB 적재
- **청킹 전략 3종**: Docling Hybrid(문서 구조 기반) / LangChain Semantic(임베딩 유사도 기반) / Fixed Size(고정 토큰 — 앞 두 전략의 효과를 재는 기준선). PDF를 로컬 비전 모델로 분석해 전략을 **추천**받을 수도 있음
- **Parent-Child 색인**: 임베딩 모델 한도를 넘는 청크를 자식 조각으로 쪼개 전부 색인하고, 검색되면 **부모 청크 전체**를 LLM에 전달 — 잘림으로 인한 정보 손실 제거
- **문서 언어 선택(한국어/English)**: 이미지/표 VLM 설명을 문서 언어에 맞춰 생성
- **청크 수동 교정**: 임베딩 전 미리보기에서 청크 텍스트를 직접 수정 (파싱 오류·오배치 보정)
- **하이브리드 검색**: Dense(벡터) + BM25(Sparse) → RRF로 순위 융합. dense 단독도 가능
- **RAGAS 평가**: 청킹·저장·검색 전략 조합의 RAG 품질을 RAGAS로 채점·비교 (자세한 내용은 [`evaluation/README.md`](evaluation/README.md))

## 기술 스택

| 영역 | 사용 |
|------|------|
| Backend | Python 3.10, FastAPI, asyncio, httpx |
| PDF 파싱 | Docling (layout 비전 + TableFormer + DocumentFigureClassifier, CPU 강제) |
| 청킹 | Docling HybridChunker / LangChain SemanticChunker / 자체 Fixed Size (토크나이저 offset 기반) |
| Chat · VLM · 임베딩 | **로컬 LM Studio** (OpenAI 호환): chat/VLM = `google/gemma-4-e4b`, 임베딩 = `text-embedding-multilingual-e5-large-instruct`(1024차원) |
| LLM 클라이언트 | `pydantic-ai` (Chat/VLM), 자체 `LMStudioEmbedder`(httpx) |
| Vector Store | ChromaDB (별도 컨테이너) |
| 검색 | ChromaDB dense + `rank_bm25` + `kiwipiepy`(한국어 토크나이즈) + RRF |
| 평가 | RAGAS 0.4.3 (로컬 LM Studio 채점) |
| PDF → 이미지 | `pypdfium2` — 전략 추천·평가셋 생성 시 PDF를 페이지 이미지 + 텍스트로 변환해 로컬 VLM에 전달 |
| Frontend | React 18 UMD CDN + Babel inline (**빌드 없음**, `front/` 정적 서빙) |

## 동작 흐름

```
PDF 업로드 → Docling 파싱 → 이미지/표 VLM 설명(ko/en)
          → 청킹(Hybrid | Semantic | Fixed) → (미리보기에서 수동 교정)
          → 자식 분할(한도 초과분만) → 임베딩 → ChromaDB 컬렉션
질문 → 검색(dense | hybrid: BM25+RRF) → 부모 단위로 중복 제거
     → 컨텍스트 + LLM 답변
(선택) RAGAS 평가 → 전략 조합별 점수 비교
```

## 디렉토리 구조

```
jarana-chatbot/
├── app/                      # FastAPI 애플리케이션
│   ├── main.py               # 진입점 (최상단에서 PyTorch MPS fallback env 설정)
│   ├── config.py             # .env 단일 진입점 — LM Studio/Chroma/임베더 초기화
│   ├── rag.py                # dense 검색 + 부모 단위 중복 제거
│   ├── retrieval.py          # 하이브리드 검색 (Dense + BM25 + RRF)
│   ├── llm.py                # 챗 Agent + 대화 히스토리 캐시
│   ├── models.py             # Pydantic 모델
│   ├── text_utils.py         # 문장 경계 추적 (청킹·자식분할 공용)
│   ├── pdf_pages.py          # PDF → 페이지 이미지 + 텍스트 (로컬 VLM 입력용)
│   ├── embeddings/
│   │   ├── lmstudio.py       # LMStudioEmbedder
│   │   └── child_split.py    # Parent-Child 자식 분할
│   ├── chunking/             # Docling 변환 + VLM 어노테이터 + 전략 분기
│   │   ├── annotator.py      # 이미지/표 → VLM 설명 (언어 ko/en)
│   │   └── strategies/       # common(공용 역매핑), docling/hybrid,
│   │                         # langchain/semantic, fixed_size
│   ├── evaluation_jobs.py    # RAGAS 평가 작업 상태 저장소
│   └── routers/              # upload / embed / chat / collections / evaluation
├── evaluation/               # RAGAS 오프라인 A/B 평가 하니스 (README 참조)
├── front/                    # React SPA (빌드 없음, 정적 서빙)
├── chunking-results/         # 업로드 PDF + 청킹 산출물 (.gitignore)
├── docs/                     # 프로젝트 문서 (ARCHITECTURE/ADR/PRD/UI_GUIDE/RAGAS_PLAN)
├── docker-compose.yml
├── Dockerfile
├── .env.example              # .env 템플릿 (복사해서 사용)
└── requirements.txt
```

## 사전 요구사항

- Python 3.10
- **LM Studio** — chat/VLM 모델(`google/gemma-4-e4b` 등 vision 지원)과 임베딩 모델(`e5-large-instruct`)을 로드하고 로컬 서버(OpenAI 호환) 실행
- ChromaDB (Docker 컨테이너 권장)

## 환경변수 (`.env`)

`app/config.py`가 `.env` **단일 진입점**으로 모든 외부 서비스 설정을 읽는다. 호스트/포트/모델 ID는 코드에 박지 않고 `.env`만 수정한다.
`.env`는 git에 올라가지 않으므로(`.gitignore`) 저장소를 받은 뒤 **직접 만들어야 한다.**

### 설정 절차

**1. 예시 파일을 복사한다** (프로젝트 루트 = `requirements.txt`가 있는 위치)

```bash
cp .env.example .env
```

**2. 복사한 `.env`의 아래 3개를 본인 환경 값으로 바꾼다.** 이 3개만 있으면 앱이 뜬다.

```env
# LM Studio 서버 주소. 끝에 /v1 까지 포함해야 한다.
#   같은 PC에서 LM Studio를 띄웠다면  → http://localhost:1234/v1
#   다른 PC(LAN)에서 띄웠다면         → http://<그 PC의 IP>:1234/v1
# 포트는 LM Studio → Developer 탭에 표시된 값을 쓴다 (기본 1234).
LMSTUDIO_BASE_URL=http://localhost:1234/v1

# LM Studio에 **로드해 둔** 모델 ID. 아래 명령으로 확인한 값을 그대로 붙인다.
#   curl http://localhost:1234/v1/models
# 임베딩 모델은 다국어 지원 모델을 권장한다(한국어 문서라면 필수).
EMBEDDING_MODEL=text-embedding-multilingual-e5-large-instruct
# 이미지/표 설명을 생성하므로 **vision 지원 모델**이어야 한다.
CHAT_MODEL=google/gemma-4-e4b
```

이 3개가 없으면 앱이 시작되지 않는다(`app/config.py`가 `_require`로 읽어 즉시 에러).

**3. ChromaDB를 기본값(`localhost:8001`)과 다르게 띄웠다면** `CHROMA_HOST` / `CHROMA_PORT`를 추가한다.

외부 API 키는 필요 없다. 청킹 전략 추천과 RAGAS 평가셋 생성도 LM Studio의 비전 모델을 쓴다.

> **주의 — 토크나이저는 임베딩 모델과 같은 계열로 맞춰야 한다.**
> `CHUNK_TOKENIZER_MODEL`(기본 `intfloat/multilingual-e5-large-instruct`)로 청크 토큰 수를 센다.
> 임베딩 모델을 바꾸면 이 값도 함께 바꿔야 한다. 다르면 토큰 수 계산이 어긋나 청크가
> 한도를 다 못 쓰거나(과다 계산) 초과해 잘린다(과소 계산).

### 전체 키 목록

아래는 기본값을 포함한 전체 설정이다. **바꾸고 싶은 키만** `.env`에 넣으면 된다.

```env
# ─── PyTorch / Docling 가속 ────────────────────────────────────
# Apple Silicon MPS GPU는 float64 미지원 — 미지원 연산을 CPU로 자동 fallback (안전망).
PYTORCH_ENABLE_MPS_FALLBACK=1

# Docling 모델 추론 디바이스. cpu | mps | cuda | auto (default: cpu)
# CPU 강제 이유: MPS는 일부 Docling 모델 추론에서 float64 텐서로 죽음.
# GPU 가속 시도하려면 mps 또는 auto 로 변경 (안 죽으면 더 빠름).
DOCLING_DEVICE=cpu

# ─── LM Studio (OpenAI 호환, 인증 없음) ─────────────────────────
# 노트북 → 데스크탑 LM Studio 호출.
# 데스크탑 위치/포트 바뀌면 LMSTUDIO_BASE_URL 한 줄만 수정.
# base_url 끝의 /v1 까지 포함. 코드는 여기에 "/embeddings", "/chat/completions" 만 붙임.
# 본인 LM Studio가 떠 있는 호스트 IP/포트로 교체. 예: http://192.168.0.50:1234/v1
LMSTUDIO_BASE_URL=http://<LM_STUDIO_HOST>:<PORT>/v1

# LM Studio에 로드된 모델 ID (GET {base_url}/models 의 data[].id 와 동일)
EMBEDDING_MODEL=text-embedding-multilingual-e5-large-instruct
CHAT_MODEL=google/gemma-4-e4b

# ─── ChromaDB ──────────────────────────────────────────────────
CHROMA_HOST=localhost
CHROMA_PORT=8001

# ─── 청킹 ──────────────────────────────────────────────────────
# 임베딩 모델의 max_context_length(512) 와 정렬.
# 토크나이저는 반드시 EMBEDDING_MODEL과 동일 계열이어야 한다 —
# 다르면 토큰 수 계산이 어긋나 한도를 다 못 쓰거나(과다 계산) 초과해 잘린다(과소 계산).
# all-MiniLM-L6-v2(영어용)는 한국어를 실제보다 2~2.6배 부풀려 세서 e5로 교체했다.
CHUNK_TOKENIZER_MODEL=intfloat/multilingual-e5-large-instruct
CHUNK_MAX_TOKENS=512

# Skip할 picture 분류 라벨 (DocumentFigureClassifier-v2.5 라벨, 쉼표 구분)
# 후보: bar_chart, bar_code, chemistry_markush_structure, chemistry_molecular_structure,
#       flow_chart, icon, line_chart, logo, map, other, pie_chart, qr_code,
#       remote_sensing, screenshot, signature, stamp
SKIP_PICTURE_CLASSES=logo

# LLM 호출 간격(초). LM Studio는 자체 한도 없음 — 0 권장.
# GPU 부하 분산 차원에서 1~2초 주는 것도 가능.
CHUNK_VLM_INTERVAL_SEC=0
EMBED_SUMMARY_INTERVAL_SEC=0

# 청킹 전략 (docling_hybrid | langchain_semantic | fixed_size) — 프론트가 매번 지정하면 무시됨
CHUNK_STRATEGY=docling_hybrid
# LangChain SemanticChunker 옵션
# breakpoint_threshold_type: percentile | standard_deviation | interquartile
SEMANTIC_BREAKPOINT_TYPE=percentile
# percentile=95(기본), standard_deviation=3, interquartile=1.5
SEMANTIC_BREAKPOINT_AMOUNT=95
# SemanticChunker가 한 번에 임베딩 보낼 문장 수. LM Studio는 한도 없지만 메모리 안정성 차원에서 유지.
SEMANTIC_EMBED_BATCH_SIZE=32

# 고정 크기 청킹(fixed_size) 목표 토큰 수. 토크나이저는 CHUNK_TOKENIZER_MODEL 공용.
# 256인 이유: docling_hybrid 실측 평균이 225토큰이라 크기를 맞춰야 "청킹 방식" 차이만 비교된다.
# 512는 "넘으면 잘린다"는 상한이지 목표가 아니다 — 꽉 채우면 한 청크에 여러 주제가
# 섞여 벡터가 평균화되고 어느 질문에도 어정쩡하게 매칭된다.
FIXED_CHUNK_SIZE=256

# ─── Parent-Child 색인 (큰 청크를 자식 벡터로 분할) ─────────────
# 시멘틱 청킹은 크기 상한이 없어 임베딩 모델 한도를 넘는 청크가 나온다.
# 넘긴 만큼은 조용히 잘려 검색에 존재하지 않게 되므로, 초과 청크만 자식으로 쪼개
# 각각 벡터를 만든다. 검색에 걸리면 LLM에는 부모 청크 전체가 전달된다.
# 청킹이 아니라 임베딩 시점에 동작하므로 전략과 무관하게 적용된다
# (docling_hybrid·fixed_size는 이미 한도 이하라 no-op).
EMBED_MAX_TOKENS=512
# 자식 목표 토큰 수. 256마다 끊는 게 아니라 ceil(전체/이 값)개로 균등 분할할 때의
# 기준이다(짜투리 조각 방지). 경계는 목표 지점에서 가장 가까운 문장 끝.
EMBED_CHILD_TARGET_TOKENS=256

# ─── 하이브리드 검색 (Dense + BM25 + RRF) ──────────────────────
# Dense/Sparse 후보 수는 컬렉션 청크 수의 비율로 결정 (clamp 적용).
# 공식: top_k = clamp(int(N * PERCENT), MIN, MAX)
#   N=25  → 10 (MIN)
#   N=100 → 30
#   N=1000 → 200 (MAX)
HYBRID_TOPK_PERCENT=0.30
HYBRID_TOPK_MIN=10
HYBRID_TOPK_MAX=200
# Dense + Sparse 두 검색 결과를 합칠 때 쓰는 융합 공식의 상수 — score = Σ 1/(K + rank).
# 작으면(예: 10) 1등 청크 가중치↑, 크면(예: 60) 상위권 평탄화. 60은 학계 표준 (Cormack et al. 2009).
HYBRID_RRF_K=60

# 검색 결과 중 LLM 컨텍스트로 전달할 최종 청크 수.
# 늘리면 답변이 풍부해지지만 토큰 비용↑ + LLM이 헷갈릴 가능성↑. 줄이면 핵심만.
HYBRID_FINAL_TOP_N=3

# BM25 인덱스를 메모리에 들고 있을 컬렉션 수 (LRU 캐시).
# 16 = 자주 쓰는 16개 컬렉션은 즉시 검색. 17번째 검색 시 가장 오래 안 쓴 1개가 자동 제거됨.
# 제거된 컬렉션을 다시 검색하면 BM25 빌드 1~2초 소요. 컬렉션 많고 메모리 여유 있으면 늘려도 OK.
HYBRID_CACHE_MAXSIZE=16

# ─── PDF 페이지 렌더링 (전략 추천 / 평가셋 생성용) ──────────────
# 두 기능은 PDF를 페이지 이미지 + 텍스트 레이어로 변환해 로컬 VLM(CHAT_MODEL)에 보낸다.
# 상용 API가 내부적으로 하는 전처리를 직접 수행하는 것 — 문서가 외부로 나가지 않는다.
# 이 값은 페이지 렌더 해상도(긴 변 기준 px). 키우면 작은 글씨 인식이 좋아지지만
# 이미지 토큰이 늘어 모델 컨텍스트를 빨리 소모한다.
PDF_PAGE_RENDER_MAX_PX=1024
```

> 위 블록을 그대로 복사해 쓰지 않아도 된다 — **필수 3개만 적는 것이 가장 간단하다.**
> `LMSTUDIO_BASE_URL`·`EMBEDDING_MODEL`·`CHAT_MODEL`은 반드시 본인 환경 값으로 교체할 것.

## 실행

### 1) 로컬 실행 (개발)

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# ChromaDB (별도 터미널/컨테이너)
docker run -d --name chromadb -p 8001:8000 chromadb/chroma:latest

# 앱 서버
.venv/bin/uvicorn app.main:app --reload
```

- 접속: http://localhost:8000 (uvicorn 기본 포트)
- ⚠️ macOS: VS Code 내장 터미널은 로컬 네트워크 권한 누락으로 LAN의 LM Studio 접속이 막힐 수 있다. 일반 Terminal.app/iTerm2 권장.

### 2) Docker Compose

```bash
docker compose up --build      # 챗봇 :8080, ChromaDB :8001
docker compose down            # 종료 (-v 추가 시 데이터 삭제)
```

`.env`의 `LMSTUDIO_BASE_URL`은 컨테이너에서 접근 가능한 주소여야 한다(LM Studio는 호스트/LAN에서 별도 실행).

## 사용 흐름 (웹 UI)

1. **청킹 & 임베딩** 탭 — PDF 업로드 → (문서 언어·청킹 전략 선택) → 청킹 → 컬렉션 이름 지정 후 임베딩
2. **챗봇 대화** 탭 — 컬렉션 선택 후 질문. 하이브리드 검색 토글 가능
3. **RAGAS 평가** 탭 — 평가셋 생성(로컬 VLM)·검수·저장 → 컬렉션/검색모드 조합별 채점 → 점수 비교 ([`evaluation/README.md`](evaluation/README.md))

## API 엔드포인트

서버 실행 후 Swagger UI: http://localhost:8000/docs

| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/` | 프론트엔드 SPA |
| `POST` | `/api/upload` | PDF 업로드 → 청킹 작업 시작 (`strategy`, `lang`, `do_ocr`) |
| `GET` | `/api/upload/status/{job_id}` | 청킹 진행 상태 |
| `POST` | `/api/upload/recommend` | 청킹 전략 추천 (로컬 VLM) |
| `GET` | `/api/chunkings` · `/api/chunkings/{doc}/chunks` | 청킹 결과/청크 조회 |
| `POST` | `/api/embed` · `GET /api/embed/status/{id}` | 임베딩 작업 / 상태 |
| `GET` | `/api/collections` · `DELETE /api/collections/{name}` | 컬렉션 목록 / 삭제 |
| `POST` | `/api/chat` | 채팅 (RAG, `hybrid` 플래그) |
| `POST` | `/api/evaluation` ·  `/api/evaluation/generate-evalset` · `/api/evaluation/eval-sets` … | RAGAS 평가/평가셋 |

## 참고 문서

- [`CLAUDE.md`](CLAUDE.md) — 아키텍처 규칙·함정·개발 프로세스 (소스 오브 트루스)
- [`docs/`](docs/) — ARCHITECTURE / ADR / PRD / UI_GUIDE / RAGAS_PLAN
- [`evaluation/README.md`](evaluation/README.md) — RAGAS 평가 하니스 사용법
