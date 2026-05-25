# PDF 청킹 파이프라인 사용법

## 개요

브라우저에서 PDF를 업로드하면 자동으로 청킹된다. 원본 PDF와 청킹 결과는 `docs/<문서이름>/` 폴더에 통합 저장.

표/이미지는 **Pydantic AI(기본 Gemini)** 가 자연어 설명문으로 변환해 청크 안에 함께 박힌다. 원본 이미지(PNG) / 원본 표(md, html, csv) 도 별도 폴더에 저장된다.

> **임베딩/벡터DB 저장은 본 파이프라인 범위 밖.** 본 단계는 RAG 입력으로 쓸 청크 산출까지.

## 모듈 구조

```
app/
├── main.py                  # FastAPI 진입점
├── upload_jobs.py           # 메모리 기반 job store (job_id, 진행률, 결과)
├── routers/
│   └── upload.py            # POST /api/upload, GET /api/upload/status/{job_id}
└── chunking/
    ├── __init__.py          # process_pdf(progress_callback 지원)
    ├── pipeline.py          # Docling PdfPipelineOptions 빌더
    ├── annotator.py         # Pydantic AI Agent (13초 rate limit)
    ├── serializers.py       # 커스텀 Picture/Table serializer
    ├── exporters.py         # 원본 저장 + mapping.json
    └── chunker.py           # HybridChunker + chunks.jsonl 직렬화

front/
└── upload.html              # 업로드 폼 + 진행률 폴링
```

## 사전 준비

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. API 키

기본 VLM은 Gemini이므로 Google AI Studio API 키 필요.

```bash
# .env 파일에 작성
GOOGLE_API_KEY=...
GEMINI_MODEL=gemini-3-flash-preview   # 선택 — 기본값과 동일
```

다른 모델로 교체할 경우 환경변수 추가 (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY` 등).

### 3. 청킹 토크나이저 설정 (선택)

청크 한도/토크나이저는 환경변수로 변경 가능. 실제 RAG 임베딩 모델의 토크나이저/한도와 정렬할수록 임베딩 품질 좋아짐.

```bash
# .env (기본값)
CHUNK_TOKENIZER_MODEL=sentence-transformers/all-MiniLM-L6-v2
CHUNK_MAX_TOKENS=512
```

| 변수 | 기본값 | 의미 |
|---|---|---|
| `CHUNK_TOKENIZER_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | 토큰 수 측정용 HuggingFace 토크나이저 |
| `CHUNK_MAX_TOKENS` | `512` | 청크 한 개의 최대 토큰 수 |

**언어별 토큰-글자 비율** (MiniLM 기준):
- 영어: 1글자 ≈ 0.2 토큰 → 512 토큰 = 약 2,300자
- 한국어: 1글자 ≈ 1.5~1.8 토큰 → 512 토큰 = 약 300자

한국어 PDF 위주면 `CHUNK_MAX_TOKENS=1024~2048` 또는 한국어 친화 토크나이저(예: `BAAI/bge-m3`) 권장.

⚠️ 변경 후 서버 재시작 필요.

## 서버 실행

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

브라우저에서 `http://localhost:8080/upload` 접속.

## 업로드 흐름

1. **파일 선택** — `.pdf` 만 허용
2. **OCR 옵션** — 스캔본 PDF 일 때만 체크 (텍스트 PDF는 끄는 게 정확)
3. **제출** — `POST /api/upload` 호출, 즉시 `job_id` 응답
4. **진행률 표시** — 브라우저가 2초마다 `GET /api/upload/status/{job_id}` 폴링
5. **완료** — 결과 요약 (출력 폴더, 청크/이미지/표 개수) 표시

## API

### `POST /api/upload`

multipart/form-data:
- `file`: PDF 파일 (필수)
- `do_ocr`: bool (기본 false)

응답:
```json
{
  "job_id": "550e8400-e29b-...",
  "doc_name": "my-document",
  "saved_path": "docs/my-document/my-document.pdf"
}
```

### `GET /api/upload/status/{job_id}`

응답:
```json
{
  "job_id": "550e8400-e29b-...",
  "status": "running",
  "progress": 47,
  "step": "vlm_image",
  "message": "이미지 12/31 처리 중",
  "result": null,
  "error": null
}
```

`status`: `pending` | `running` | `completed` | `failed`

완료 시 `result`:
```json
{
  "doc_name": "my-document",
  "out_dir": "docs/my-document",
  "chunk_count": 76,
  "picture_count": 31,
  "table_count": 4
}
```

## 중복 파일명 처리

같은 이름 PDF를 다시 올리면 `<stem>__YYYYMMDD-HHMMSS` 타임스탬프가 붙어 새 폴더로 생성됨. 이전 결과는 그대로 유지.

## 출력 디렉토리 구조

```
docs/
└── <PDF 파일명>/
    ├── <PDF 파일명>.pdf      # 업로드한 원본
    ├── <PDF 파일명>.md       # 전체 markdown 통문서
    ├── chunks.jsonl          # 청크 결과 (한 줄 = 한 청크)
    ├── mapping.json          # 청크 ↔ 원본 매핑
    ├── images/               # 원본 이미지 PNG
    └── tables/               # 원본 표 (md/html/csv 각각)
```

자세한 스키마는 [PIPELINE.md](./PIPELINE.md) 참조.

## 자주 묻는 질문

### Q. "after"가 "aner"로 잘못 변환되는데?
OCR 오류. 텍스트 PDF면 OCR 끔(체크박스 해제) 상태로 두면 해결.

### Q. Gemini 외 다른 LLM 쓰려면?
`.env`의 `GEMINI_MODEL` 값을 변경 (예: `openai:gpt-4o`, `anthropic:claude-sonnet-4-5`). 해당 API 키 환경변수도 함께 설정.

### Q. VLM 호출 한도 초과 (429)?
`app/chunking/annotator.py`의 `DEFAULT_MIN_INTERVAL_SEC=13.0` 으로 호출 간격이 조정되어 있음. 그래도 일일 한도 소진 시엔 다음날까지 대기 또는 빌링 활성화 필요.

### Q. 서버 재시작 후 job 상태는?
메모리 기반이라 사라짐. 청킹 결과 파일은 영구 보존되므로 문제 없음. 진행 중이었던 작업은 중단됨.

## 한계 / 알려진 사항

- 표 자체를 PNG 이미지로는 저장하지 않음 (공식 Docling 옵션 없음). md/html/csv 세 형식만.
- VLM 출력은 비결정적 — 같은 PDF를 두 번 돌려도 description 텍스트는 달라질 수 있음.
- 동시 업로드 N건이면 동시에 처리됨 — quota 한도 빠르게 소진 가능.
