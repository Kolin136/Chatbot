# 청킹 파이프라인 흐름

브라우저에서 PDF를 업로드(`POST /api/upload`)하면 내부적으로 무슨 일이 일어나는지, 그리고 결과물이 어떤 형태로 떨어지는지 설명한다.

사용법(서버 실행, UI 사용)은 [USAGE.md](./USAGE.md) 참고. 본 문서는 **흐름과 산출물 구조**에만 집중한다.

---

## 🔪 청킹 방식 개요

### 일반적인 청킹 방식 7종 비교

| 방식 | 분할 기준 | LLM/임베딩 호출 | 특징 |
|---|---|---|---|
| Fixed-size | 글자/토큰 N개마다 무조건 자름 | ❌ | 단순/빠름. 문장 중간 잘림 |
| Recursive character | 구두점 우선순위로 split (`\n\n` → `\n` → `.` → 공백) | ❌ | LangChain 기본. 의미 보존 양호 |
| Sentence-aware | 문장 경계 (NLTK/spaCy) | ❌ | 문장 단위 보장 |
| Document structure-aware | 헤더/문단/표/그림 등 문서 객체 단위 | ❌ (layout 모델) | PDF처럼 구조 있는 문서에 강함 |
| **Hybrid** (← 우리 방식) | **구조 + 토큰 한도** 동시에 | ❌ (토크나이저만, 카운팅용) | **의미 보존 + 한도 준수** 양쪽 잡음 |
| Semantic | 의미 유사도 변화점 (인접 문장 임베딩 유사도) | ✅ 임베딩 호출 | 평문에 강함, 비용/시간 ↑ |
| Agentic / LLM-based | LLM이 직접 "여기서 자르자" 결정 | ✅ LLM 호출 | 가장 정밀, 가장 비쌈 |

### 우리가 Hybrid를 쓰는 이유

PDF는 작성자가 이미 **헤더/문단/표/그림으로 의미 단위를 명시**한 문서다. 그 구조를 그대로 따라가는 게 의미 보존에 가장 효율적이다. 다만 한 섹션이 너무 길면 임베딩 모델의 입력 한도(기본 512 토큰)를 초과하므로 토큰 한도만 추가로 강제한다.

- 구조만 쓰면 → 토큰 한도 못 맞춤 (긴 섹션이 한 청크에 다 들어가 임베딩 잘림)
- 토큰만 쓰면 → 의미 깨짐 (문장 중간에 잘림)
- 둘 다 쓰면 → **의미 단위 보존 + 한도 준수** 양쪽 다 잡음

### Hybrid 작동 — 3 Pass 예시

가공의 PDF 한 페이지를 가정 (토큰 한도는 설명용으로 **100토큰**으로 가정):

```
┌──────────────────────────────────────────────────────────┐
│  PDF 페이지                                                │
│                                                            │
│  # 1. 개요                          ← 헤더                │
│  IBM은 미국 회사다.                  ← 문단 (20 토큰)      │
│  ThinkPad를 만든다.                  ← 문단 (15 토큰)      │
│                                                            │
│  # 1-1. 시스템 구성                  ← 헤더                │
│  GNS-Manager는 매우 길고 복잡한      ← 문단 (180 토큰)     │
│  설명문이다... (한참 길어서          │   ⚠️ 한도 초과       │
│  100토큰을 훌쩍 넘음)                │                      │
│                                                            │
│  [표: Rev | Date | Author]           ← 표 (60 토큰)        │
│                                                            │
│  # 1-2. 데이터 흐름                  ← 헤더                │
│  [그림: 아키텍처 다이어그램]          ← 그림 (30 토큰,      │
│                                       VLM 설명문 포함)     │
│  CAN 메시지를 보낸다.                 ← 문단 (12 토큰)      │
└──────────────────────────────────────────────────────────┘
```

#### Pass 1 — HierarchicalChunker (구조 단위로 일단 다 쪼갬)

Docling이 PDF 구조 분석 → 각 객체마다 청크 하나씩. 현재 헤더 스택을 메타로 같이 첨부.

```
청크 A  [헤더: 1. 개요]                    "IBM은 미국 회사다."           20토큰
청크 B  [헤더: 1. 개요]                    "ThinkPad를 만든다."           15토큰
청크 C  [헤더: 1. 개요 > 1-1. 시스템 구성]  "GNS-Manager는 매우 길고..."  180토큰  ⚠️
청크 D  [헤더: 1. 개요 > 1-1. 시스템 구성]  "[표: Rev|Date|Author]"        60토큰
청크 E  [헤더: 1. 개요 > 1-2. 데이터 흐름]  "[그림 + VLM 설명]"             30토큰
청크 F  [헤더: 1. 개요 > 1-2. 데이터 흐름]  "CAN 메시지를 보낸다."          12토큰
```

이대로면 문제: C는 너무 큼(180), A·B·E·F는 너무 작음(15~30).

#### Pass 2 — Split (한도 초과 청크 쪼갬)

토크나이저로 토큰 수 측정. 100 넘는 거 분할.

```
청크 C (180토큰)                                  ⚠️ 한도 초과
   ↓ split (문장/단어 경계 기준)
청크 C-1  [헤더: 1. 개요 > 1-1. 시스템 구성]   "GNS-Manager는 매우 길고..."  95토큰
청크 C-2  [헤더: 1. 개요 > 1-1. 시스템 구성]   "...나머지 후반부 내용"        85토큰
```

다른 청크는 한도 안이라 그대로 둠.

#### Pass 3 — Merge (같은 헤더 가진 작은 형제끼리 합침)

연속된 청크 쌍 검사. **헤더가 똑같고** 합쳐도 100토큰 안이면 merge.

```
검사: A(20) + B(15) = 35   → 같은 헤더 [1. 개요], 100 안 → MERGE ✅
검사: C-2(85) + D(60) = 145 → 같은 헤더지만 100 초과 → 합치지 않음
검사: E(30) + F(12) = 42   → 같은 헤더 [1-2.] → MERGE ✅
```

**Pass 3 후 최종 결과 (5개):**

```
청크 1  [1. 개요]              "IBM은 미국 회사다. ThinkPad를 만든다."   35토큰  ← A+B merged
청크 2  [1. 개요 > 1-1. ...]   "GNS-Manager는 매우 길고..."             95토큰
청크 3  [1. 개요 > 1-1. ...]   "...나머지 후반부"                        85토큰
청크 4  [1. 개요 > 1-1. ...]   "[표: ...]"                              60토큰
청크 5  [1. 개요 > 1-2. ...]   "[그림 + 설명] CAN 메시지를 보낸다."     42토큰  ← E+F merged
```

#### 변화 요약

```
시작 PDF 객체:    6개 (문단2 + 큰문단1 + 표1 + 그림1 + 문단1)
                    ↓
Pass 1 결과:      6개  (구조 그대로 각각 청크화)
                    ↓
Pass 2 결과:      7개  (큰 청크 1개 → 2개로 split)
                    ↓
Pass 3 결과:      5개  (작은 형제끼리 2번 merge)
```

**최종**: 모든 청크가 100토큰 한도 안 + 가능한 한 의미 단위(같은 헤더 묶음) 유지.

### 핵심 직관

- **Pass 1** = "PDF 구조 따라 자연스럽게 자름" → 의미 보존
- **Pass 2** = "너무 크면 임베딩 안 들어가니까 쪼갬" → 한도 강제
- **Pass 3** = "너무 작으면 검색 품질 떨어지니까 같은 단원 형제끼리 합침" → 효율 향상

→ "글자 N개 단위" 청킹과 결정적으로 다른 점: PDF 구조를 따라가면서 토큰 한도만 안전선으로 사용.

### 헤더 정보 전파 규칙

위 예시의 청크 4 같은 표/그림 청크도 모두 **자기 위의 가장 가까운 헤더 스택**을 메타로 가짐. 즉:

- 헤더 "1-3" 등장 → 그 아래 등장한 모든 문단/표/그림 청크는 `headings: ["1-3"]` 가짐
- 페이지가 바뀌어도 다음 헤더가 나올 때까지 유지 (페이지 경계 무관)
- "1-3의 이미지"는 독립 청크가 아니라 **"1-3 소속 이미지"** 로 식별됨

이미지/표 청크가 RAG 답변에서 "5.2 절을 참고하세요, 다이어그램은 [원본 이미지]" 식으로 정확한 출처와 함께 활용될 수 있는 근거.

---

## 📜 실행 흐름 (단계별)

### 0단계 — 업로드 진입점
- 브라우저: `http://localhost:8080/upload` 폼에서 PDF 선택 → 제출
- FastAPI: `POST /api/upload` (multipart/form-data, `file` + `do_ocr`)
- 서버:
  - `docs/<stem>/` 폴더 생성 (충돌 시 `<stem>__YYYYMMDD-HHMMSS`)
  - 원본 PDF를 `docs/<stem>/<stem>.pdf` 로 저장
  - `job_id` 발급 후 `BackgroundTasks` 로 청킹 시작 → 즉시 응답
- 브라우저: 2초마다 `GET /api/upload/status/{job_id}` 폴링 → 진행률 표시

### 1단계 — 환경 준비
- `.env` 파일에서 `GOOGLE_API_KEY`, `GEMINI_MODEL` 자동 로드 (`python-dotenv`)
- `app/upload_jobs.py::job_store` 에 `JobState(status="running")` 등록

### 2단계 — 파일 단위 처리

PDF 한 개당 다음 7개 step이 순서대로 실행된다 (`app/chunking/__init__.py::process_pdf`).
각 step 시작 시 `progress_callback(percent, step_key, message)` 호출 → `job_store` 갱신 → 브라우저 폴링에 반영.

#### Step ① PDF → DoclingDocument 변환
```
Docling이 PDF 페이지를 한 장씩 분석:
  - 텍스트 추출 (텍스트 PDF는 직접, 기본 OCR 꺼짐)
  - Layout 인식 (헤더/문단/그림/표 영역 분리)
  - 표 구조 인식 (행/열 파악)
  - 그림 영역을 PIL Image 객체로 추출
```
**검증 사례** (HLD): 이미지 31개, 표 4개 인식.

#### Step ② 이미지 → 자연어 설명문 (VLM 호출)
```
for pic in doc.pictures:
    Annotator._throttle()                       # 직전 호출로부터 13초 보장 (rate limit)
    PIL 이미지를 PNG bytes로 변환
    → Pydantic AI Agent (기본 GEMINI_MODEL env, fallback "gemini-3-flash-preview") 호출
    → "이 그림을 한국어로 설명해 주세요" + 이미지 첨부
    → 응답: "이 그림은 시스템 아키텍처 다이어그램으로..."
    → 메모리 dict에 저장 (self_ref → 설명문)
```
- **Rate limit**: 첫 호출은 즉시, 2번째부터 직전 호출 후 13초 경과 보장 (`DEFAULT_MIN_INTERVAL_SEC=13.0`). Gemini free tier 분당 한도 회피.
- **실패 시**(API 키 없음/quota 초과/503/429): 빈 문자열 반환, WARNING 로그 남기고 다음 picture로 진행.

#### Step ③ 표 → 자연어 설명문 (LLM 호출)
```
for tbl in doc.tables:
    표를 markdown 텍스트로 변환 (DataFrame.to_markdown())
    Annotator._throttle()                       # 13초 rate limit (이미지와 공유)
    → Pydantic AI Agent 호출 (텍스트만)
    → 응답: "이 표는 리비전 이력으로 4개 컬럼..."
    → 메모리 dict에 저장
```

#### Step ④ 원본 파일 저장
```
images/picture_N.png       (Docling Figure export 방식: pic.get_image(doc).save(...))
tables/table_N.md          (DataFrame.to_markdown())
tables/table_N.html        (table.export_to_html(doc))
tables/table_N.csv         (DataFrame.to_csv())
```

#### Step ⑤ mapping.json 생성
청크와 원본 파일을 잇는 메타데이터. `self_ref`(`#/pictures/N`, `#/tables/N`)가 키.

#### Step ⑥ 전체 markdown 통문서 저장
```python
MarkdownDocSerializer(doc=doc).serialize().text
```
`<PDF이름>.md` 파일로 떨어진다. **이건 검증/디버깅용** — PDF가 markdown으로 어떻게 풀렸는지 눈으로 보는 용도. 임베딩에는 사용하지 않는다.

#### Step ⑦ HybridChunker로 청킹 → chunks.jsonl
```
HybridChunker가 DoclingDocument를 돌면서:
  - 헤더 계층 보존 (1, 1-2 같은 단원 추적)
  - 토큰 한도(기본 512) 넘으면 split
  - 너무 작으면 같은 헤더 형제끼리 merge
  - 표/이미지 자리에는 커스텀 serializer가 Step ②/③에서 만든 설명문을 박음
  
결과: 청크들이 한 줄씩 JSONL로 저장됨
```
**검증 사례** (HLD, 1.3MB, 12페이지): 청크 76개 생성, 이미지 31개, 표 4개.

### 3단계 — 작업 완료
- `job_store` 에 `status="completed"` + 결과 요약(`chunk_count`, `picture_count`, `table_count`, `out_dir`) 기록
- 브라우저 폴링이 완료 상태 감지 → 진행률 100% + 결과 표시 후 종료

---

## 📦 결과물 디렉토리 구조

```
docs/
└── <PDF 파일명>/                    ← PDF stem과 동일한 폴더명
    ├── <PDF 파일명>.pdf             ← 업로드한 원본 PDF
    ├── <PDF 파일명>.md              ← Step ⑥ 결과 (검증용 전체 markdown)
    ├── chunks.jsonl                 ← Step ⑦ 결과 (실제 RAG 입력)
    ├── mapping.json                 ← Step ⑤ 결과 (조인용 메타)
    ├── images/                      ← Step ④ 결과
    │   ├── picture_0.png
    │   ├── picture_1.png
    │   └── ...
    └── tables/                      ← Step ④ 결과
        ├── table_0.md
        ├── table_0.html
        ├── table_0.csv
        └── ...
```

PDF가 N개면 같은 구조의 폴더가 N개 생긴다. 원본 PDF와 청킹 결과가 한 폴더에 통합됨.

---

## 📄 각 결과물 파일 상세

### 1. `<PDF이름>.md` — 검증용 전체 markdown
PDF를 통째로 markdown으로 풀어낸 것.
- 표는 markdown 표 (`| col | col |`)
- 이미지 자리에는 `<!-- image -->` placeholder
- 헤더 계층(`#`, `##`) 유지
- **용도**: "Docling이 내 PDF를 제대로 읽었나" 눈으로 확인. 헤더 계층/표 구조 검증.
- **임베딩에 사용하지 않는다.**

### 2. `chunks.jsonl` — 메인 결과물 (RAG 입력)
한 줄(JSON 객체) = 한 청크.

**실제 청크 샘플** (HLD에서 표가 들어간 청크):
```json
{
  "chunk_id": "des_..._HLD#00002",
  "doc_name": "des_..._HLD",
  "text": "| Rev. | Date | Author | ... |\n| 1.0 | 2025.12.05 | Giang Hoang | ... |",
  "contextualized_text": "Revision History\n| Rev. | Date | ...",
  "headings": ["Revision History"],
  "page_nos": [2, 3],
  "page_start": 2,
  "page_end": 3,
  "doc_item_refs": ["#/texts/N", "#/tables/0"],
  "picture_refs": [],
  "table_refs": ["#/tables/0"]
}
```

| 필드 | 의미 | RAG에서 용도 |
|---|---|---|
| `chunk_id` | 청크 고유 ID (`<doc>#<5자리>` 정렬 가능) | 벡터DB의 PK |
| `doc_name` | 원본 PDF stem | 필터링 메타 |
| `text` | 청크 원본 텍스트 (표 markdown, 이미지 설명문 인라인) | LLM 컨텍스트 입력 |
| **`contextualized_text`** | **헤더(1, 1-2) prepend된 임베딩용 텍스트** | **✅ 이걸 임베딩** |
| `headings` | 단원 헤더 리스트 (계층 순) | 필터링/하이라이트 메타 |
| `page_nos` | 청크가 걸친 페이지 번호 리스트 (정렬됨) | PDF 페이지 매칭 |
| `page_start` | `page_nos[0]` 편의 필드 (없으면 null) | 빠른 페이지 조회 |
| `page_end` | `page_nos[-1]` 편의 필드 (없으면 null) | 빠른 페이지 조회 |
| `doc_item_refs` | 청크에 들어간 모든 doc 요소 `self_ref` | 추적용 |
| `picture_refs` | 그 중 picture만 | mapping.json 조인 키 |
| `table_refs` | 그 중 table만 | mapping.json 조인 키 |

### 3. `mapping.json` — 청크 ↔ 원본 매핑
청크가 가진 `picture_refs`/`table_refs` 값을 그대로 키로 사용해 원본 파일과 메타데이터를 조회한다.

```json
{
  "doc_name": "des_..._HLD",
  "source_pdf": "docs/des_..._HLD.pdf",
  "pictures": {
    "#/pictures/0": {
      "index": 0,
      "image_path": "images/picture_0.png",
      "description": "이 그림은 ...",
      "page_no": 1
    }
  },
  "tables": {
    "#/tables/0": {
      "index": 0,
      "md_path": "tables/table_0.md",
      "html_path": "tables/table_0.html",
      "csv_path": "tables/table_0.csv",
      "description": "이 표는 ...",
      "page_no": 2
    }
  }
}
```

### 4. `images/` 폴더
- Step ① 에서 Docling이 추출한 원본 PIL 이미지를 Step ④ 에서 PNG로 떨어뜨림
- 파일명: `picture_<index>.png` (0부터)
- **용도**: VLM 호출 입력(메모리에서 사용), 디버깅, RAG 답변에 원본 그림 첨부

### 5. `tables/` 폴더
- 표 하나당 3형식 (`.md`, `.html`, `.csv`)
- 파일명: `table_<index>.<ext>`
- **왜 셋 다?**
  - `md` — 사람이 읽기 / LLM 입력하기 좋음
  - `html` — 셀 병합 등 복잡한 구조 보존
  - `csv` — pandas로 다시 로드해 데이터 처리 가능

---

## 🔄 데이터 조인 흐름 (RAG에서 활용 방식)

```
사용자 질문
  ↓
임베딩 검색 (chunks.jsonl의 contextualized_text 임베딩과 비교)
  ↓
관련 청크 K개 발견
  ↓
청크의 picture_refs / table_refs
  ↓ (조인 키)
mapping.json
  ↓
원본 이미지 경로 / 표 CSV 경로 / 페이지 번호 / VLM 설명문
  ↓
LLM 컨텍스트 구성 (chunk.text + 필요시 원본 표 데이터)
  ↓
답변 생성
  ↓
답변 + 출처 표시 ("원본: HLD 7페이지 그림 3")
```

`mapping.json` 덕분에 답변에 페이지 번호/원본 이미지를 같이 보여줄 수 있다.

---

## 🧩 컴포넌트 매핑 (코드 ↔ 흐름)

| Step | 코드 위치 | 핵심 함수/클래스 |
|---|---|---|
| ① 변환 | `app/chunking/pipeline.py` | `build_converter()` → `DocumentConverter` |
| ② 이미지 VLM | `app/chunking/annotator.py` | `Annotator.describe_image()` + `_throttle()` (13초 rate limit) |
| ③ 표 LLM | `app/chunking/annotator.py` | `Annotator.describe_table()` + `_throttle()` |
| ④ 원본 저장 | `app/chunking/exporters.py` | `save_picture_images()`, `save_tables()` |
| ⑤ mapping.json | `app/chunking/exporters.py` | `write_mapping_json()` |
| ⑥ markdown 통문서 | `app/chunking/exporters.py` | `save_full_markdown()` |
| ⑦ 청킹 | `app/chunking/chunker.py` | `build_chunker()`, `write_chunks_jsonl()`, `_collect_pages()` |
| 커스텀 직렬화 | `app/chunking/serializers.py` | `ExternalAnnotationPictureSerializer`, `ExternalAnnotationTableSerializer` |
| 전체 조립 | `app/chunking/__init__.py` | `process_pdf(progress_callback=...)` |
| HTTP 진입점 | `app/routers/upload.py` | `POST /api/upload`, `GET /api/upload/status/{job_id}` |
| 작업 상태 | `app/upload_jobs.py` | `JobStore`, `JobState` (메모리 싱글톤) |
| UI | `front/upload.html` | 폼 + 2초 폴링 + 진행률 바 |

---

## ⚠️ 주의사항

### VLM 호출 실패 시 동작
Step ②/③ 에서 LLM 호출이 실패해도 파이프라인은 멈추지 않는다 (`Annotator.describe_image/table` 내부에서 except로 잡고 빈 문자열 반환).
- description은 빈 문자열로 mapping.json에 기록됨
- 청크에는 표 markdown만 들어가고 이미지 자리는 `<!-- image -->` placeholder로 떨어짐
- 구조는 완전하므로 나중에 description만 채워 넣는 후처리 가능

### Gemini Free Tier Quota
13초 rate limit으로 분당 한도(~4.6 RPM)는 회피하지만, 일일 한도/이미지 많은 PDF에서는 여전히 `429 RESOURCE_EXHAUSTED` 가능. 이 경우:
1. **빌링 활성화** — Google AI Studio에서 결제 연결 → 유료 티어 한도로 전환
2. **모델 교체** — `.env` 의 `GEMINI_MODEL` 값을 `openai:gpt-4o` / `anthropic:claude-sonnet-4-5` 로 변경 + 해당 API 키 설정
3. **재시도** — 분당 한도 초과 시 잠시 후 다시 업로드 (일일 한도 초과면 다음날)

### 중복 업로드 / 재실행
- **다른 세션에서 같은 이름 PDF 재업로드**: 라우터(`app/routers/upload.py:_resolve_doc_name`)가 `<stem>__YYYYMMDD-HHMMSS` 타임스탬프 붙여 새 폴더 생성 → 기존 결과 유지.
- **`process_pdf` 함수 직접 재호출** (같은 `output_root`/`<stem>`): 기존 파일 덮어쓰기. LLM 출력은 비결정적이라 description 텍스트는 매번 다를 수 있음.

### Job 상태 영속성
`app/upload_jobs.py` 의 `JobStore` 는 메모리 기반 — **서버 재시작 시 모든 job 상태 사라짐**. 단, 청킹 결과 파일(`docs/<stem>/`)은 영구 보존되므로 결과 자체는 무손실. 진행 중이던 작업은 중단.
