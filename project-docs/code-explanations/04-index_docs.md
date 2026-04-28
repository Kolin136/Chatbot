# `scripts/index_docs.py` 코드 해석

## 파일 역할

**챗봇 서버와 별개로, 수동으로 한 번씩 돌리는 "사전 준비 스크립트"** 다. 가이드 문서(`docs/*.md`, `docs/*.txt`)를 읽어서 → 단락별로 쪼개고 → 각 단락의 요약을 LLM으로 만들고 → 그 요약을 벡터로 바꿔서 → ChromaDB에 저장하는 5단계 파이프라인.

이 작업이 끝나면 ChromaDB에 수십 개의 검색용 항목이 쌓여있는 상태가 되고, 이후 챗봇 서버가 사용자 질문을 받을 때마다 이 데이터를 검색해서 답변에 활용한다.

### 실행 방법

```bash
source .venv/bin/activate
python -m scripts.index_docs
```

`-m` 옵션으로 모듈처럼 실행하는 이유는 내부에서 `from app.config import ...`로 `app` 패키지를 import하기 때문. 직접 `python scripts/index_docs.py`로 실행하면 파이썬이 `app` 모듈을 못 찾아서 에러가 난다.

### 실행 시점

- 신규 배포 시 한 번
- `docs/` 폴더의 가이드 문서를 수정/추가한 후
- 그 외에는 돌릴 필요 없음 (이미 ChromaDB에 저장돼 있음)

### 핵심 아이디어: "Summary-based Retrieval"

이 스크립트의 설계를 이해하려면 이 개념부터 잡아야 한다.

- **검색용 벡터** = LLM이 생성한 짧은 요약문의 벡터 (파생 텍스트)
- **답변용 텍스트** = 원본 본문 전체 (원본 소스)

왜 이렇게 나누는가:
- 원본 본문은 길어서 벡터화하면 의미가 뭉개진다. 짧은 요약이 검색 성능이 더 좋다.
- 하지만 실제 답변 생성에는 정보량이 많은 원본이 필요하다.
- 그래서 **검색은 요약 벡터로 하고, 반환은 메타데이터에 숨겨둔 원본으로** 한다.

> **용어 주의**: 이 패턴은 종종 "Small-to-Big Retrieval"이라는 이름으로 혼동되지만, 엄밀히는 다르다. Small-to-Big은 "같은 원본 텍스트의 부분(문장) → 전체(단락)" 관계이고, Summary-based는 "LLM이 생성한 요약 → 원본 텍스트" 관계다. 이 프로젝트는 후자에 해당하며, LlamaIndex에서는 "Document Summary Index"라고도 부른다.

이 구조가 `collection.add()` 호출부에서 명확하게 드러난다 (나중에 설명).

---

## Line 1-3: 표준 라이브러리 임포트

```python
import asyncio
import time
from pathlib import Path
```

- **`asyncio`** — 파이썬 표준 비동기 라이브러리. 이 스크립트는 동기 코드 위주지만, 임베더의 `embed_documents()`가 `async` 함수라 `asyncio.run()`으로 한 번만 비동기 함수를 호출하기 위해 필요하다.
- **`time`** — 표준 시간 라이브러리. 여기서는 `time.sleep(13)`처럼 **일부러 대기**하는 데 쓴다. 이유는 아래에서 설명.
- **`pathlib.Path`** — 파일 경로를 다루는 객체 지향 라이브러리. `os.path` 대신 권장되는 현대적인 방식. `Path("docs")`처럼 쓰면 경로를 객체로 다룰 수 있고, `.exists()`, `.glob()`, `.read_text()` 같은 메서드를 바로 호출할 수 있다.

---

## Line 5: 서드파티 임포트

```python
from pydantic_ai import Agent
```

PydanticAI의 `Agent` 클래스. 이 스크립트 안에서 **요약 전용 에이전트**를 하나 만들기 위해 필요하다. 챗봇 본체의 `llm.py`에도 `Agent`가 있지만, 그건 "CS 챗봇 응답 생성용"이고 여기는 "문서 요약용"이라 용도가 다르다. 같은 `Agent` 클래스를 **인스트럭션만 다르게** 두 번 사용하는 구조.

---

## Line 7: 프로젝트 내부 임포트

```python
from app.config import GEMINI_MODEL, chroma_client, embedder
```

`app/config.py`에서 세 가지를 가져온다.

| 이름 | 용도 |
|------|------|
| `GEMINI_MODEL` | 모델 식별자 문자열 (예: `google-gla:gemini-3.1-flash-lite-preview`) |
| `chroma_client` | ChromaDB `HttpClient` 객체. 컬렉션을 삭제/생성할 때 필요 |
| `embedder` | PydanticAI `Embedder` 객체. 요약문을 벡터로 바꿀 때 사용 |

**중요**: `chroma_collection`은 가져오지 않고 `chroma_client`만 가져온다. 왜냐하면 이 스크립트는 기존 컬렉션을 **삭제하고 새로 만드는** 작업을 하기 때문. `chroma_collection`은 "이미 존재하는 컬렉션 핸들"이라 여기서 쓰면 혼란스럽다. 대신 `chroma_client`에서 직접 `delete_collection` + `get_or_create_collection`으로 새 핸들을 만든다.

또 이 한 줄의 부수효과로 **`config.py` 전체가 실행된다**. `load_dotenv()`, 환경변수 검증, `Embedder` 생성, ChromaDB 연결이 전부 이 import 시점에 일어난다. 스크립트가 본격적으로 동작하기 전에 이미 모든 클라이언트가 준비된 상태가 되는 것.

---

## Line 9-12: 요약 전용 Agent 싱글톤 생성

```python
summary_agent = Agent(
    GEMINI_MODEL,
    instructions="주어진 텍스트를 요약하고 키워드를 추출하는 도우미입니다.",
)
```

모듈 레벨에서 `Agent` 하나를 만들어 둔다. `config.py`의 `embedder`와 비슷한 **모듈 싱글톤 패턴**. 스크립트가 import되는 순간 한 번 만들어지고, 이후 `summarize_chunk()`가 몇 번 호출되든 같은 에이전트를 재사용한다.

### `instructions`의 역할

PydanticAI `Agent`의 `instructions` 파라미터는 **시스템 프롬프트**와 같은 역할을 한다. 이 에이전트에 질문이 올 때마다 LLM 호출의 시작 부분에 이 문장이 자동으로 붙는다.

한 줄짜리 간단한 인스트럭션인 이유: 실제 요약 지시는 아래의 `SUMMARY_PROMPT`가 상세하게 담고 있기 때문. 여기는 "너는 요약 도우미야" 정도의 역할 부여만 담당.

### `llm.py`의 agent와 다른 점

| 항목 | `llm.py`의 `agent` | 여기의 `summary_agent` |
|------|------------------|---------------------|
| 용도 | 사용자 질문에 답변 | 문서 단락 요약 |
| `instructions` | CS 에이전트 시스템 프롬프트 (긴 규칙) | 한 줄짜리 역할 부여 |
| 호출 방식 | `await agent.run(...)` (비동기) | `summary_agent.run_sync(...)` (동기) |
| 호출 빈도 | 매 사용자 요청마다 | 인덱싱 시 청크 개수만큼 |
| 히스토리 | 있음 (세션별) | 없음 (일회성) |

같은 `Agent` 클래스지만 완전히 다른 목적으로 쓰는 두 개의 인스턴스. 두 에이전트가 서로를 모르고 독립적으로 동작한다.

---

## Line 14-23: 요약 프롬프트 템플릿

```python
SUMMARY_PROMPT = """\
아래 텍스트를 1~2문장으로 요약하고, 검색에 유용한 핵심 키워드 3~5개를 추출하세요.

형식:
요약: <요약문>
키워드: <쉼표로 구분된 키워드>

텍스트:
{text}
"""
```

여러 줄에 걸친 문자열 템플릿. 나중에 `SUMMARY_PROMPT.format(text=raw_text)`로 `{text}` 자리에 실제 단락이 채워진다.

### `"""\` 맨 앞의 백슬래시

```python
SUMMARY_PROMPT = """\
아래 텍스트를...
```

삼중 따옴표 바로 뒤에 `\`가 붙어 있다. 이건 "바로 뒤의 줄바꿈을 무시하라"는 의미. 만약 `\`가 없으면:

```
\n아래 텍스트를...
```

이렇게 첫 줄이 빈 줄로 시작한다. `\`를 넣으면:

```
아래 텍스트를...
```

깔끔하게 첫 글자부터 시작한다. 사소한 디테일이지만 LLM 프롬프트에서 불필요한 공백 줄을 없애는 테크닉.

### 왜 이런 형식을 강요하나

```
요약: <요약문>
키워드: <쉼표로 구분된 키워드>
```

LLM 출력이 이 형식을 따르게 하면 후처리하기 편하다... 고 생각할 수 있는데, **실제로는 이 코드에서 파싱하지 않는다**. `result.output`을 통째로 받아서 그냥 벡터화해버린다. 그래도 형식을 강요하는 이유는:

- LLM이 요약과 키워드를 **둘 다** 출력하게 유도하는 효과
- 키워드가 본문에 포함되면 임베딩 벡터에 키워드 정보가 반영됨 → 검색 품질 향상
- 결과적으로 "요약 + 키워드 섞인 텍스트"가 검색 인덱스의 기반이 된다

---

## Line 25-28: 상수 정의

```python
MIN_CHUNK_LENGTH = 50
MAX_RAW_TEXT_LENGTH = 5000
ADD_BATCH_SIZE = 200
SUMMARIZE_MAX_RETRIES = 3
```

매직 넘버를 상수로 뽑아둔 것. 각각의 의미:

| 상수 | 값 | 용도 |
|------|-----|------|
| `MIN_CHUNK_LENGTH` | 50 | 50자 미만인 단락은 버림. 너무 짧은 문장(헤더, 빈 줄, 한 단어 등)은 검색에 쓸모없음 |
| `MAX_RAW_TEXT_LENGTH` | 5000 | 단락이 너무 길면 5000자까지만 저장. ChromaDB 메타데이터 크기 제한 회피 |
| `ADD_BATCH_SIZE` | 200 | ChromaDB에 한 번에 넣는 청크 개수. 너무 많이 한꺼번에 보내면 메모리/네트워크 부담 |
| `SUMMARIZE_MAX_RETRIES` | 3 | 요약 LLM 호출이 실패하면 최대 3번까지 재시도 |

**대문자 + 언더스코어** 네이밍은 파이썬에서 "상수"를 나타내는 관례(PEP 8). 파이썬에는 진짜 상수가 없어서 실제로는 수정 가능하지만, 개발자끼리 "이건 건드리지 말자"는 약속.

---

## Line 31-38: `read_documents` — 문서 읽기

```python
def read_documents(docs_dir: Path) -> list[tuple[str, str]]:
    documents = []
    for file_path in sorted(docs_dir.glob("*")):
        if file_path.suffix in (".md", ".txt"):
            text = file_path.read_text(encoding="utf-8")
            documents.append((file_path.name, text))
            print(f"  읽기 완료: {file_path.name} ({len(text)}자)")
    return documents
```

`docs/` 폴더의 모든 `.md`와 `.txt` 파일을 읽어서 `(파일명, 본문)` 튜플의 리스트로 반환한다.

### 함수 시그니처

```python
def read_documents(docs_dir: Path) -> list[tuple[str, str]]:
```

- 인자 `docs_dir`는 `Path` 객체 (문자열 아님)
- 반환 타입은 `list[tuple[str, str]]` — "문자열 튜플의 리스트"
- 예: `[("jarana_guide.md", "파일 내용..."), ("faq.txt", "...")]`

### `docs_dir.glob("*")`

`Path.glob(패턴)`은 해당 디렉토리에서 패턴에 맞는 파일을 찾아주는 메서드. `"*"`는 "모든 파일"을 의미. 파이썬 `os.listdir()`의 객체지향 버전이라고 보면 됨.

### `sorted(...)`

`glob()`의 결과는 운영체제마다 순서가 다를 수 있어서 **항상 같은 순서**로 처리하기 위해 정렬. 이게 없으면 macOS에서는 A 순서, Linux에서는 B 순서로 처리돼서 디버깅이 어려울 수 있다.

### `file_path.suffix in (".md", ".txt")`

`suffix`는 파일 확장자를 반환한다 (예: `".md"`). 이 한 줄로 "마크다운 또는 텍스트 파일만" 필터링.

`.pdf`나 `.docx` 같은 파일은 자동으로 건너뛴다. PDF 지원을 추가하려면 여기에 `".pdf"`를 넣고 해당 파서를 붙이면 되는 확장 포인트.

### `file_path.read_text(encoding="utf-8")`

파일 전체를 한 번에 문자열로 읽는다. 명시적으로 `encoding="utf-8"`을 지정한 이유는 **한국어 파일 깨짐 방지**. 특히 Windows에서는 기본 인코딩이 `cp949`로 되어 있어서 utf-8 한글 파일이 깨지는 경우가 있다. 명시하면 안전.

### `documents.append((file_path.name, text))`

튜플로 묶어서 리스트에 추가. `.name`은 파일 경로 전체가 아니라 **파일명만**(`jarana_guide.md`) 반환.

### 로그 출력

```python
print(f"  읽기 완료: {file_path.name} ({len(text)}자)")
```

파일을 읽을 때마다 진행 상황을 `print`. 스크립트가 오래 걸리는 작업이라 진행 상황이 안 보이면 멈춘 건지 돌아가는 건지 알 수 없다. 그래서 단계별로 로그를 찍는다.

들여쓰기(`  `)는 바깥에서 `[1/5] 문서 읽기` 같은 대제목을 찍고, 이 아래에 하위 로그를 나란히 보여주기 위한 시각적 트릭.

---

## Line 41-57: `split_into_chunks` — 단락 분할

```python
def split_into_chunks(filename: str, text: str) -> list[dict]:
    paragraphs = text.split("\n\n")
    chunks = []
    chunk_idx = 0
    for para in paragraphs:
        para = para.strip()
        if len(para) < MIN_CHUNK_LENGTH:
            continue
        chunks.append(
            {
                "id": f"{filename}_chunk_{chunk_idx}",
                "raw_text": para[:MAX_RAW_TEXT_LENGTH],
                "source": filename,
            }
        )
        chunk_idx += 1
    return chunks
```

한 개의 문서 텍스트를 **단락 단위로** 쪼개서 청크(chunk) 리스트로 만든다.

### 청킹(chunking)이란

RAG에서 "청킹"은 긴 문서를 검색 단위로 잘게 자르는 작업. 자르는 기준은 여러 가지가 있음:

- **문자 수 기준** (예: 500자씩)
- **토큰 수 기준** (예: LLM 토큰 200개씩)
- **문장 기준** (예: 3문장씩)
- **단락 기준** (예: 빈 줄로 구분된 단락마다) ← **우리가 쓰는 방식**
- **의미 기준** (LLM으로 의미 단위 분할)

각자 장단점이 있는데, 단락 기준은 **가장 간단하면서도 의미 경계를 꽤 잘 보존**한다. 사람이 글을 쓸 때 자연스럽게 단락을 나누기 때문에, 그 경계를 그대로 따라가면 문맥이 깨지지 않는다.

### `text.split("\n\n")`

**두 개의 줄바꿈**(`\n\n`)을 기준으로 텍스트를 자른다. 마크다운이나 일반 텍스트에서 빈 줄 하나는 "단락 구분"을 의미하는 관례.

```
첫 번째 단락입니다.
여러 줄로 이어질 수 있습니다.

두 번째 단락입니다.
```

`split("\n\n")`하면 이걸 `["첫 번째 단락입니다.\n여러 줄로 이어질 수 있습니다.", "두 번째 단락입니다."]` 두 개로 나눈다.

### `para.strip()`

단락 앞뒤의 공백/줄바꿈 제거. 파일 맨 끝에 붙어있는 불필요한 개행 같은 걸 정리한다.

### `if len(para) < MIN_CHUNK_LENGTH: continue`

50자 미만인 단락은 스킵. 예를 들어:

- `# 제목` (헤더 한 줄) → 스킵
- `---` (구분선) → 스킵
- 짧은 한 문장(이미지 캡션 등) → 스킵

이런 것들은 검색에 쓸모없거나 오히려 잡음이 되므로 거르는 것.

### 청크 딕셔너리 구조

```python
{
    "id": f"{filename}_chunk_{chunk_idx}",
    "raw_text": para[:MAX_RAW_TEXT_LENGTH],
    "source": filename,
}
```

각 청크는 세 개의 키로 구성된 딕셔너리:

| 키 | 예시 값 | 의미 |
|---|---|---|
| `id` | `"jarana_guide.md_chunk_0"` | ChromaDB에서 이 청크를 식별하는 고유 ID |
| `raw_text` | `"발음 점수는 100점 만점으로..."` | 원본 단락 본문 (최대 5000자) |
| `source` | `"jarana_guide.md"` | 어느 파일에서 왔는지 출처 |

### `para[:MAX_RAW_TEXT_LENGTH]` — 문자열 슬라이싱

`para[:5000]`는 문자열의 앞에서 5000자까지 잘라내는 슬라이스. 5000자 이하면 원본 그대로, 초과하면 뒤를 잘라낸다.

왜 자르는가: **ChromaDB 메타데이터는 크기 제한이 있고**, 너무 큰 텍스트가 들어가면 저장 실패 위험이 있기 때문. 5000자를 넘는 단락이 거의 없긴 하지만 안전장치.

### `chunk_idx`의 용도

```python
chunk_idx = 0
...
chunk_idx += 1
```

청크마다 0, 1, 2, ... 순번을 매긴다. 이게 왜 필요하냐면, 같은 파일에서 여러 청크가 나오므로 **파일명만으로는 고유 ID가 안 되기 때문**. `"jarana_guide.md_chunk_0"`, `"jarana_guide.md_chunk_1"`처럼 번호를 붙여서 구분한다.

**중요**: `chunk_idx`는 `MIN_CHUNK_LENGTH` 필터를 통과한 청크에만 증가한다. 즉, 50자 미만이라 스킵된 단락은 번호를 먹지 않는다. 그래서 최종 ID는 연속된 번호가 된다 (중간에 빵꾸 없음).

---

## Line 60-70: `summarize_chunk` — LLM으로 요약 생성

```python
def summarize_chunk(raw_text: str) -> str | None:
    for attempt in range(SUMMARIZE_MAX_RETRIES):
        try:
            result = summary_agent.run_sync(SUMMARY_PROMPT.format(text=raw_text))
            if result.output:
                return result.output
            print(f"    요약 결과가 비어있음, 재시도 {attempt + 1}/{SUMMARIZE_MAX_RETRIES}")
        except Exception as e:
            print(f"    요약 실패: {e}, 재시도 {attempt + 1}/{SUMMARIZE_MAX_RETRIES}")
        time.sleep(1)
    return None
```

한 개의 청크 본문을 받아서 Gemini에 보내 요약을 생성한다. 실패하면 최대 3번 재시도.

### 반환 타입 `str | None`

요약 성공 시 문자열, 3번 다 실패하면 `None`을 반환한다. `| None`은 "이 값이 없을 수도 있음"을 명시적으로 표현하는 타입 힌트 (Python 3.10+).

호출하는 쪽에서 `if summary is None:`으로 체크해서 처리해야 한다는 신호.

### `for attempt in range(SUMMARIZE_MAX_RETRIES)`

`range(3)`는 `0, 1, 2`를 순회. 총 3번의 시도 기회가 있다는 뜻.

### `summary_agent.run_sync(...)`

`llm.py`에서는 `await agent.run(...)` (비동기)를 쓰지만, 여기서는 `run_sync` (동기)를 쓴다.

왜:
- 이 스크립트는 FastAPI 이벤트 루프 안이 아니라 **평범한 파이썬 스크립트**로 실행됨
- 청크 하나씩 순서대로 처리하면 되므로 동시성이 필요 없음
- 동기 API가 코드 작성이 더 간단

`async def`/`await` 복잡성을 피하기 위한 선택.

### `SUMMARY_PROMPT.format(text=raw_text)`

Line 14-23의 템플릿에 실제 본문을 넣는다. `{text}` 자리에 `raw_text`가 채워진 최종 프롬프트가 LLM에 전달된다.

### `result.output`

PydanticAI의 `run_sync()`는 `RunResult` 객체를 반환하고, 그 안의 `.output`이 LLM이 생성한 실제 텍스트.

### `if result.output:` — 빈 응답 방어

```python
if result.output:
    return result.output
print(f"    요약 결과가 비어있음, 재시도 {attempt + 1}/{SUMMARIZE_MAX_RETRIES}")
```

LLM이 가끔 빈 문자열을 반환하는 경우가 있다 (안전 필터에 걸리거나, 특수한 입력일 때). 이걸 그냥 통과시키면 빈 요약이 벡터화돼서 검색 품질이 망가지므로, 빈 응답도 **실패로 간주**하고 재시도한다.

파이썬에서 빈 문자열 `""`은 `bool` 평가 시 `False`로 취급된다. 그래서 `if result.output:`만 써도 "None도 아니고 빈 문자열도 아닐 때"를 한 번에 체크 가능.

### `try/except`로 API 에러 방어

```python
try:
    result = summary_agent.run_sync(...)
    ...
except Exception as e:
    print(f"    요약 실패: {e}, 재시도 {attempt + 1}/{SUMMARIZE_MAX_RETRIES}")
```

외부 API 호출은 네트워크 에러, rate limit, 타임아웃 등 언제든 실패할 수 있다. `Exception`을 통째로 잡아서 **어떤 에러가 나든 프로그램이 죽지 않고 재시도**하게 한다.

`as e`로 에러 객체를 받아서 `print`로 찍어주면 디버깅할 때 원인 파악에 도움이 된다.

### `time.sleep(1)` — 재시도 간격

```python
time.sleep(1)
```

재시도 사이에 1초 대기. API 서버가 일시적으로 과부하일 때 바로 재시도하면 또 실패하기 쉬우므로 약간 텀을 둔다. 이런 패턴을 **백오프(backoff)** 라고 부름 (여기서는 가장 단순한 상수 백오프).

### 3번 다 실패하면 `None` 반환

```python
return None
```

`for` 루프가 끝까지 돌면 함수 끝에 도달해 `None`이 반환된다. 호출 쪽에서 `None` 체크로 이 청크를 스킵하게 만드는 설계.

---

## Line 73-75: `embed_summaries` — 요약문 → 벡터

```python
async def embed_summaries(summaries: list[str]) -> list[list[float]]:
    result = await embedder.embed_documents(summaries)
    return [emb for emb in result.embeddings]
```

요약문 리스트를 받아서 벡터 리스트로 변환한다. **전체 요약을 한 번에** 임베딩 API에 보내는 배치 처리.

### 타입 힌트가 알려주는 구조

```python
summaries: list[str]           # ← 입력: ["요약1", "요약2", ...]
-> list[list[float]]           # ← 출력: [[0.1, 0.2, ...], [0.3, 0.4, ...], ...]
```

각 요약이 하나의 실수 리스트(벡터)로 변환된다. 벡터 하나의 차원은 보통 768이나 1536 같은 숫자.

### `async def` + `await`

이 함수만 비동기로 작성된 이유:

PydanticAI의 `Embedder.embed_documents()`가 **async 함수**이기 때문. `embed_query`는 `await`로 호출해야 하므로, 이걸 쓰는 함수도 `async def`여야 한다.

### 왜 요약 함수는 `run_sync`인데 이건 async인가

같은 이유를 뒤집어서 생각하면 됨:

- `Agent.run_sync()` — PydanticAI가 제공하는 **동기** 래퍼 버전이 있음
- `Embedder.embed_documents()` — **비동기 버전만** 있음

그래서 이 함수만 `async`로 만들고, `run_indexing`에서 `asyncio.run()`으로 감싸서 한 번만 이벤트 루프를 연다.

### `[emb for emb in result.embeddings]` — 리스트 컴프리헨션

```python
return [emb for emb in result.embeddings]
```

이건 결과적으로 `list(result.embeddings)`와 같다. 왜 굳이 컴프리헨션을 쓰는가 하면, `result.embeddings`가 제너레이터나 특수 이터러블일 수 있어서 **평범한 리스트로 확실히 변환**하기 위함. 그래야 나중에 `embeddings[i:i+200]` 같은 슬라이싱이 문제없이 동작한다.

### 배치 임베딩의 이점

```python
result = await embedder.embed_documents(summaries)  # 20개를 한 번에
```

청크 하나씩 20번 API 호출하는 대신 **리스트를 통째로 한 번** 보낸다. 이점:

- API 호출 횟수 감소 (20회 → 1회)
- rate limit 부담 감소
- 전체 처리 시간 단축

그래서 요약은 하나씩 처리하지만(LLM은 긴 생성을 해야 하므로 배치 효율이 덜함), 임베딩은 배치로 처리한다.

---

## Line 78-142: `run_indexing` — 메인 오케스트레이터

전체 파이프라인을 순서대로 실행하는 함수. 5단계로 명확히 나뉘어 있다.

### Line 79-82: 초기 검증

```python
def run_indexing():
    docs_dir = Path("docs")
    if not docs_dir.exists():
        print("docs/ 폴더가 없습니다.")
        return
```

`docs/` 폴더가 프로젝트 루트에 있는지 확인. 없으면 메시지 찍고 조용히 종료.

**주의**: `Path("docs")`는 **상대경로**다. 현재 작업 디렉토리(`pwd`) 기준으로 해석되므로, 프로젝트 루트에서 실행해야 한다. 그래서 `python -m scripts.index_docs`를 프로젝트 루트에서 돌리는 게 전제.

만약 `scripts/` 폴더 안에서 직접 실행하면 `docs/` 폴더를 못 찾아 에러가 난다.

### Line 84-88: [1/5] 문서 읽기

```python
print("[1/5] 문서 읽기")
documents = read_documents(docs_dir)
if not documents:
    print("docs/ 폴더에 .md 또는 .txt 파일이 없습니다.")
    return
```

위에서 정의한 `read_documents` 호출. `.md`/`.txt`가 하나도 없으면 역시 조기 종료.

`[1/5]`, `[2/5]` 같은 단계 표시는 진행 상황을 직관적으로 보여주기 위한 장치.

### Line 90-96: [2/5] 단락 분할

```python
print("[2/5] 단락 분할")
all_chunks = []
for filename, text in documents:
    chunks = split_into_chunks(filename, text)
    all_chunks.extend(chunks)
    print(f"  {filename}: {len(chunks)}개 청크")
print(f"  총 {len(all_chunks)}개 청크")
```

모든 문서를 순회하면서 각각을 청킹. 결과를 하나의 리스트 `all_chunks`에 다 합친다.

### `list.extend()` vs `list.append()`

```python
all_chunks.extend(chunks)  # chunks의 원소들을 하나씩 풀어서 추가
# vs
all_chunks.append(chunks)  # chunks 리스트 자체를 원소로 추가
```

여기서는 `extend`를 써야 한다. `append`를 쓰면 `[[청크1, 청크2], [청크3, 청크4]]`처럼 중첩 리스트가 돼버린다.

### for 루프의 언패킹

```python
for filename, text in documents:
```

`documents`는 `[("파일명", "본문"), ...]` 형태의 튜플 리스트. 루프에서 자동으로 튜플을 언패킹해서 `filename`과 `text` 두 변수에 할당한다. `for item in documents: filename = item[0]; text = item[1]` 보다 훨씬 간결.

### Line 98-112: [3/5] 요약 생성 — 가장 오래 걸리는 단계

```python
print("[3/5] 요약 생성 (PydanticAI Agent)")
valid_chunks = []
summaries = []
for i, chunk in enumerate(all_chunks):
    summary = summarize_chunk(chunk["raw_text"])
    if summary is None:
        print(f"  청크 {chunk['id']} 요약 실패 — 건너뜀")
        continue
    chunk["summary"] = summary
    valid_chunks.append(chunk)
    summaries.append(summary)
    if (i + 1) % 5 == 0:
        print(f"  {i + 1}/{len(all_chunks)} 처리")
    time.sleep(13)
print(f"  요약 완료: {len(summaries)}개 (건너뜀: {len(all_chunks) - len(valid_chunks)}개)")
```

이 부분이 **전체 스크립트에서 가장 오래 걸리는 구간**이다. 청크 하나마다 Gemini API를 호출해야 하고, 중간에 13초씩 쉰다.

### `enumerate`로 인덱스와 원소를 동시에

```python
for i, chunk in enumerate(all_chunks):
```

`enumerate`는 리스트에 인덱스를 붙여준다. `[(0, 청크1), (1, 청크2), ...]` 같은 효과. `i`는 진행률 출력에만 쓴다.

### `valid_chunks`와 `summaries`의 이중 관리

```python
valid_chunks = []
summaries = []
```

왜 두 리스트를 따로 관리하는가:

- `valid_chunks` — ID, 원본, 출처 정보까지 포함한 딕셔너리 리스트 (ChromaDB에 저장할 때 필요)
- `summaries` — 요약문만 모은 리스트 (임베딩 API에 통째로 넘길 때 필요)

임베딩 API는 단순히 **문자열 리스트**만 받기 때문에, 딕셔너리 전체를 넘길 수 없다. 그래서 요약문만 따로 뽑은 리스트를 별도로 유지한다.

### `continue`로 실패 청크 스킵

```python
if summary is None:
    print(f"  청크 {chunk['id']} 요약 실패 — 건너뜀")
    continue
```

`summarize_chunk`가 3번 재시도 후 포기해서 `None`을 반환했으면, 해당 청크는 **포기하고 다음 청크로**. 이게 있어서 한두 개가 실패해도 전체 인덱싱은 계속 진행된다.

그래서 나중에 `len(valid_chunks)`와 `len(all_chunks)`가 다를 수 있고, 그 차이를 "건너뜀: X개"로 로그에 남긴다.

### `chunk["summary"] = summary` — 딕셔너리에 필드 추가

기존 청크 딕셔너리에 `summary` 키를 **새로 추가**한다. 파이썬 딕셔너리는 자유롭게 키를 추가할 수 있다.

이 필드는 이후에 직접 쓰이지는 않지만(`summaries` 리스트가 따로 있으니까), 디버깅이나 확장을 위한 백업 용도.

### `if (i + 1) % 5 == 0:` — 5개마다 진행률 출력

```python
if (i + 1) % 5 == 0:
    print(f"  {i + 1}/{len(all_chunks)} 처리")
```

청크 하나마다 진행률을 찍으면 로그가 너무 시끄럽다. 5개마다만 찍는다.

`(i + 1)`을 쓰는 이유: `i`는 0부터 시작하므로, 5개 처리한 시점은 `i=4`. `(i + 1) % 5 == 0` → `5 % 5 == 0` → True.

### `time.sleep(13)` — Rate Limit 회피

```python
time.sleep(13)
```

**이게 이 스크립트에서 가장 의아할 수 있는 줄**이다. 왜 13초씩 쉬는가?

Gemini 무료 티어의 rate limit은 분당 5회 요청(RPM = 5). 60초 / 5회 = **12초** 간격이 최소. 여유를 두어 13초로 설정.

청크 20개 × 13초 = **4분 30초** 정도 소요. 엄청 느리지만 무료 티어에서는 어쩔 수 없다.

**유료 티어로 전환 시**: 이 숫자를 줄이거나 없앨 수 있다. 또는 `asyncio.gather`로 병렬 호출 가능.

### Line 114-116: 유효 청크 0개면 종료

```python
if not valid_chunks:
    print("유효한 청크가 없습니다. 종료합니다.")
    return
```

모든 청크가 요약 실패했으면 더 진행할 의미가 없으니 종료. 안전장치.

### Line 118-120: [4/5] 임베딩 생성

```python
print("[4/5] 임베딩 생성 (PydanticAI Embedder)")
embeddings = asyncio.run(embed_summaries(summaries))
print(f"  임베딩 완료: {len(embeddings)}개")
```

### `asyncio.run()`의 역할

```python
embeddings = asyncio.run(embed_summaries(summaries))
```

`embed_summaries`는 `async def` 함수라서 그냥 호출하면 코루틴 객체만 반환되고 실제로 실행되지 않는다. `asyncio.run()`으로 감싸면:

1. 새 이벤트 루프 생성
2. 코루틴 실행
3. 완료되면 결과 반환
4. 이벤트 루프 종료

이 스크립트는 동기 스크립트인데 비동기 함수 **하나만** 쓰고 싶을 때 이 패턴을 사용한다. FastAPI 같은 웹 서버는 이미 이벤트 루프가 있으니 `asyncio.run()`을 쓰면 안 되지만, 평범한 스크립트는 이게 가장 간단한 방법.

### 임베딩은 빠르다

3단계(요약)는 4분 30초 걸렸지만, 4단계(임베딩)는 **몇 초** 안에 끝난다. 이유:

- 배치 호출 (1회 API 요청)
- 임베딩 API는 요약 생성보다 훨씬 빠름 (토큰 생성이 아니라 벡터 추출)

### Line 122-127: [5/5] ChromaDB 컬렉션 재생성

```python
print("[5/5] ChromaDB 저장")
chroma_client.delete_collection("jarana_faq")
collection = chroma_client.get_or_create_collection(
    name="jarana_faq",
    embedding_function=None,
)
```

### `delete_collection` + `get_or_create_collection` = "초기화"

```python
chroma_client.delete_collection("jarana_faq")
collection = chroma_client.get_or_create_collection(name="jarana_faq", embedding_function=None)
```

이 두 줄은 **컬렉션을 완전히 초기화**하는 패턴. 기존 데이터를 싹 지우고 빈 컬렉션을 새로 만든다.

왜 초기화하는가:
- 인덱싱을 두 번 돌리면 기존 데이터와 새 데이터가 섞여서 중복이 생김
- 문서 내용이 바뀌었을 때 "삭제 후 재생성"이 가장 깔끔
- `collection.delete(ids=[...])`로 특정 항목만 지우는 것보다 단순

**단점**: 인덱싱 실행 중에는 잠깐 컬렉션이 비어있는 상태가 된다. 그래서 프로덕션에서는 "새 컬렉션에 쌓고 → 이름 바꾸기" 같은 패턴을 쓰기도 하지만, 이 프로젝트는 그 정도까지 안 간다.

### `embedding_function=None`

`config.py`의 `chroma_collection`에서도 같은 설정이었다. "ChromaDB 자체 임베딩 쓰지 말고, 우리가 미리 계산한 벡터를 직접 넣을게"라는 선언.

이 설정이 일치해야 나중에 `rag.py`에서 검색할 때 벡터 공간이 맞아떨어진다.

### Line 128-140: 배치로 ChromaDB에 저장

```python
for i in range(0, len(valid_chunks), ADD_BATCH_SIZE):
    batch_chunks = valid_chunks[i : i + ADD_BATCH_SIZE]
    batch_embeddings = embeddings[i : i + ADD_BATCH_SIZE]
    batch_summaries = summaries[i : i + ADD_BATCH_SIZE]
    collection.add(
        ids=[c["id"] for c in batch_chunks],
        embeddings=batch_embeddings,
        documents=batch_summaries,
        metadatas=[
            {"raw_text": c["raw_text"], "source": c["source"]}
            for c in batch_chunks
        ],
    )
```

### `range(0, len(valid_chunks), ADD_BATCH_SIZE)`

`range(시작, 끝, 스텝)` 형태. 0부터 시작해서 200씩 건너뛴다. 예를 들어 청크가 500개면 `0, 200, 400`을 순회.

### 슬라이싱으로 배치 쪼개기

```python
batch_chunks = valid_chunks[i : i + ADD_BATCH_SIZE]
```

`i`부터 `i + 200`까지 자르기. 마지막 배치는 200개 미만일 수 있는데, 파이썬 슬라이싱은 범위를 넘어가도 에러 없이 **있는 만큼만** 반환한다. 편리한 특성.

세 리스트(`valid_chunks`, `embeddings`, `summaries`)를 **같은 인덱스로** 자르기 때문에 각 배치가 대응된다. 이 셋이 항상 **같은 순서와 같은 길이**여야 한다는 게 숨은 전제.

### 왜 배치로 나누나

```python
ADD_BATCH_SIZE = 200
```

ChromaDB에 한 번에 수천 개를 넣으면 메모리 부족이나 네트워크 타임아웃이 생길 수 있다. 200개씩 끊어서 여러 번 `add` 호출하는 게 안전.

현재 프로젝트의 청크는 수십 개 수준이라 사실상 배치가 한 번에 끝나지만, **확장성을 위한 안전장치**로 남겨둔 것.

### `collection.add()`의 4가지 인자 — 핵심 중의 핵심

```python
collection.add(
    ids=[c["id"] for c in batch_chunks],
    embeddings=batch_embeddings,
    documents=batch_summaries,
    metadatas=[
        {"raw_text": c["raw_text"], "source": c["source"]}
        for c in batch_chunks
    ],
)
```

이 네 개 파라미터가 **Summary-based Retrieval의 설계를 그대로 보여주는 부분**이다.

| 파라미터 | 값 | 의미 |
|---|---|---|
| `ids` | `["jarana_guide.md_chunk_0", ...]` | 청크 고유 ID |
| `embeddings` | `[[0.1, 0.2, ...], ...]` | **검색에 쓰는 벡터** (요약 기반) |
| `documents` | `["요약1", "요약2", ...]` | **검색 결과로 반환되는 텍스트** (요약문) |
| `metadatas` | `[{"raw_text": 원본, "source": 파일명}, ...]` | **답변 생성에 쓰는 원본** |

### 이 구조가 왜 영리한가

챗봇이 답변할 때의 흐름을 다시 보자:

```
사용자 질문 → 쿼리를 벡터로 → ChromaDB 검색 → 유사한 항목 3개 반환
                                                    ↓
                             "요약"이 반환됨 (documents 필드)
                             "원본"도 반환됨 (metadatas 필드의 raw_text)
                                                    ↓
                             rag.py는 "원본"을 꺼내서 LLM에게 전달
```

- **벡터 검색의 정확도**: 짧고 정제된 요약 벡터로 검색 → 노이즈가 적음
- **답변의 정보량**: 메타데이터에서 꺼낸 원본 전체 → LLM에게 풍부한 맥락 제공

만약 `embeddings`로 원본 벡터를 저장했다면:
- 긴 텍스트의 의미가 뭉개져 검색 품질 저하
- 짧은 질문과 긴 문서의 벡터 거리가 멀어서 매칭 안 됨

만약 `metadatas`에 원본을 안 넣었다면:
- LLM이 요약문만 보고 답변해야 해서 세부 정보 부족

**검색은 요약(파생), 답변은 원본(소스)**. 이게 Summary-based Retrieval의 실제 구현.

### 리스트 컴프리헨션 두 가지

```python
ids=[c["id"] for c in batch_chunks],
...
metadatas=[
    {"raw_text": c["raw_text"], "source": c["source"]}
    for c in batch_chunks
],
```

같은 `batch_chunks`를 두 번 순회하면서 필요한 필드만 뽑아낸다. 딕셔너리에서 일부 필드만 꺼내는 파이썬의 전형적 패턴.

### Line 141-142: 완료 로그

```python
print(f"  저장 완료: {collection.count()}개 항목")
print("인덱싱 완료!")
```

`collection.count()`는 현재 컬렉션에 있는 항목 개수. 방금 추가한 개수와 일치해야 정상.

---

## Line 145-146: 스크립트 진입점

```python
if __name__ == "__main__":
    run_indexing()
```

### `if __name__ == "__main__"`의 의미

파이썬에서 모듈이 실행되는 방식은 두 가지:

1. **직접 실행** (`python -m scripts.index_docs`) → `__name__` = `"__main__"`
2. **다른 파일에서 import** (`from scripts.index_docs import run_indexing`) → `__name__` = `"scripts.index_docs"`

이 조건문은 "**직접 실행됐을 때만** `run_indexing()`을 호출하라"는 뜻. import 됐을 때는 함수들이 정의만 되고 실행되지는 않는다.

### 왜 이렇게 분리하나

- 다른 파일에서 `from scripts.index_docs import summarize_chunk`처럼 특정 함수만 가져다 쓰고 싶을 때, 전체 스크립트가 돌아버리면 곤란하다.
- 직접 실행용 진입점과 "재사용 가능한 함수 모음"을 한 파일에 공존시키는 파이썬 관례.

---

## 이 스크립트가 `rag.py`와 어떻게 맞물리나

이 스크립트가 ChromaDB에 저장한 데이터를 `rag.py`가 어떻게 꺼내는지 보면 전체 그림이 완성된다.

### 인덱싱 시 (이 스크립트)

```python
collection.add(
    ids=[...],
    embeddings=[[0.1, 0.2, ...], ...],      # 요약 벡터
    documents=["요약1", ...],                # 요약 텍스트
    metadatas=[{"raw_text": 원본, ...}, ...] # 원본 텍스트는 여기에 숨김
)
```

### 검색 시 (`rag.py`)

```python
# ① 사용자 질문을 벡터로
result = await embedder.embed_query(query)
query_embedding = result.embeddings[0]

# ② 벡터 검색
results = await asyncio.to_thread(
    chroma_collection.query,
    query_embeddings=[query_embedding],
    n_results=n_results,
    include=["metadatas"],  # ← 메타데이터만 요청
)

# ③ 메타데이터에서 원본 텍스트 꺼냄
for metadata in results["metadatas"][0]:
    raw_text = metadata.get("raw_text", "")
```

주목할 점:
- 검색은 **요약 벡터**(인덱싱 시 넣은 `embeddings`)와 **쿼리 벡터**의 유사도로 이루어짐
- 반환값으로는 `metadatas`만 요청하고, 그 안의 `raw_text`(원본)를 꺼냄
- `documents`(요약문)는 사용하지 않음 — 그건 백업 용도

→ 인덱싱과 검색이 설계적으로 **딱 맞물리는 쌍**이라는 게 이 구조의 핵심.

---

## 실행 시 콘솔 출력 예시

```
[1/5] 문서 읽기
  읽기 완료: jarana_guide.md (12345자)
[2/5] 단락 분할
  jarana_guide.md: 20개 청크
  총 20개 청크
[3/5] 요약 생성 (PydanticAI Agent)
  5/20 처리
  10/20 처리
  15/20 처리
  20/20 처리
  요약 완료: 20개 (건너뜀: 0개)
[4/5] 임베딩 생성 (PydanticAI Embedder)
  임베딩 완료: 20개
[5/5] ChromaDB 저장
  저장 완료: 20개 항목
인덱싱 완료!
```

3단계에서 약 4분 30초 대기가 필요하고, 나머지 단계는 각각 몇 초 이내로 끝난다.

---

## 이 파일의 설계 의도 요약

| 개념 | 구현 방식 |
|------|----------|
| **Summary-based Retrieval** | `embeddings`=요약 벡터, `metadatas.raw_text`=원본 텍스트로 분리 |
| **Fail-Soft 전략** | 청크 일부 실패해도 전체 인덱싱 계속 진행 (`continue`) |
| **재시도 로직** | 요약 실패 시 최대 3번 재시도 후 포기 |
| **배치 처리** | 임베딩은 한 번에, ChromaDB 저장은 200개씩 |
| **Rate Limit 회피** | `time.sleep(13)`으로 분당 5회 제한 대응 |
| **동기 스크립트 + 한 번의 비동기** | `run_sync`와 `asyncio.run()` 혼용 |
| **컬렉션 초기화 방식** | `delete` + `create`로 중복 방지 |
| **상대경로 실행 전제** | `Path("docs")`로 프로젝트 루트에서 `-m` 실행 강제 |

---

## 핵심 정리

`scripts/index_docs.py`는 **챗봇이 돌아가기 전에 미리 돌려두는 "데이터 준비" 스크립트**다. 가장 중요한 세 가지:

1. **5단계 파이프라인**: 읽기 → 청킹 → 요약 → 임베딩 → 저장. 각 단계가 순차적이고 다음 단계는 이전 결과에 의존한다.

2. **Summary-based 구조**: 검색용 데이터(요약 벡터)와 답변용 데이터(원본 텍스트)를 `collection.add()`에서 **다른 파라미터에** 저장하는 게 핵심. `embeddings`에는 요약 기반 벡터, `metadatas.raw_text`에는 원본. 이 분리 덕에 `rag.py`가 "요약 벡터로 찾고 원본 텍스트로 답한다"를 구현할 수 있다.

3. **rate limit과 공존**: `time.sleep(13)`이라는 소박한 한 줄이 있어서 전체 스크립트가 무료 Gemini 티어에서도 돌아간다. 느리지만 일회성 작업이라 감내할 만한 비용.

`llm.py`, `rag.py`가 "런타임에 매 요청마다 돌아가는" 코드라면, 이 파일은 "한 번 돌려두면 끝나는" 오프라인 작업. 성격이 완전히 다른 파일이다.
