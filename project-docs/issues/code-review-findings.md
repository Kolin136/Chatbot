# 코드 리뷰 발견사항 (2026-04-06)

> **⚠️ 이 문서는 2026-04-06 시점 리뷰 기록입니다.** Spring 서버 연동은 이후 제거되어, 본 문서의 `post_reporter.py`, `SpringPostPayload`, "Docker 환경에서 Spring API 연결 미설정" 같은 항목은 더 이상 유효하지 않습니다.

## 1. .env에 실제 API 키 노출 위험

**위치**: `.env`
**상태**: git 미초기화 상태라 현재는 안전

git init 시 `.gitignore`가 `.env`를 제대로 무시하는지 반드시 확인할 것. 만약 git init 전에 이미 `.env`가 staging 되면 `.gitignore`가 무시됨.

```bash
# git init 직후 확인 절차
git init
git status  # .env가 untracked로 안 뜨는지 확인
```

---

## 2. 모델명 불일치 (코드 vs 문서)

**코드** (`app/config.py`):
```python
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "google-gla:gemini-3.1-flash-lite-preview")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "google-gla:gemini-embedding-2-preview")
```

**문서** (`project-docs/architecture/ARCHITECTURE.md`):
```
GEMINI_MODEL: google-gla:gemini-2.5-flash
EMBEDDING_MODEL: google-gla:gemini-embedding-001
```

코드가 실제 동작 기준이므로, 문서를 코드에 맞춰 업데이트 필요.

---

## 3. CORS 전체 오픈

**위치**: `app/main.py`
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

개발 단계에서는 문제 없음. 배포 시 실제 프론트엔드 도메인으로 제한 필요.

---

## 4. 테스트 코드 없음

pytest 파일이 하나도 없는 상태. 최소한 아래 항목은 테스트 필요:

- `post_reporter.py`: 마커 파싱 정규식 (정상/비정상/다중 마커/빈 응답)
- `rag.py`: 검색 결과가 비었을 때 빈 리스트 반환
- `routers/chat.py`: RAG 실패 시 빈 컨텍스트로 진행되는지
- `models.py`: `SpringPostPayload.from_report()` 팩토리 메서드

---

## 5. keep_recent 히스토리 트리밍 로직 검토 필요

**위치**: `app/llm.py`
```python
async def keep_recent(messages: list[ModelMessage]) -> list[ModelMessage]:
    if len(messages) <= 10:
        return messages
    return [messages[0]] + messages[-9:]
```

주석에는 "첫 메시지(시스템 instruction 포함)는 항상 유지"라고 되어있지만, PydanticAI는 `instructions` 파라미터로 시스템 프롬프트를 별도 관리함. `all_messages()`에 시스템 프롬프트가 포함되는지, `messages[0]`이 실제로 무엇인지 확인 필요.

잘못되면 첫 번째 사용자 턴을 의미 없이 유지하고 있는 셈.

---

## 6. Docker 환경에서 Spring API 연결 미설정

**위치**: `docker-compose.yml`

`SPRING_API_URL`이 `localhost:8000`인데, Docker 컨테이너 내부에서 localhost는 컨테이너 자신을 가리킴. Spring이 별도 Docker Compose로 운영 중이라면:

- 외부 네트워크 설정이 docker-compose.yml에 없음
- `host.docker.internal` 사용하거나, 공유 Docker 네트워크 구성 필요

```yaml
# 필요한 설정 예시
networks:
  spring-network:
    external: true

services:
  chatbot:
    networks:
      - default
      - spring-network
```

---

## 7. 인덱싱 스크립트 sleep 13초

**위치**: `scripts/index_docs.py`
```python
time.sleep(13)
```

Gemini 무료 티어 rate limit 대응. 현재 문서(1개, 40줄)에서는 문제 없지만, 문서가 늘어나면 인덱싱 시간이 `청크 수 x 13초`로 급증.

개선 방안: 유료 티어 전환 시 sleep 제거 또는 배치 요약 처리.

---

## 8. 프론트엔드 에러 시 원본 입력 복원 (긍정적)

**위치**: `front/app.js`
```javascript
} catch (err) {
    inputEl.value = originalInput;
}
```

전송 실패 시 사용자가 입력한 텍스트를 다시 채워주는 처리. 사용자가 긴 문의를 작성했는데 네트워크 오류로 날아가는 상황 방지. 유지할 것.
