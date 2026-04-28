# 운영 올리기전 해결항목

> **⚠️ Spring 서버 연동(POST_REPORT 마커, post_reporter.py, SPRING_API_URL, report_submitted)은 이후 제거되었습니다.** 본 문서의 항목 중 12번(httpx 클라이언트), 17번(POST_REPORT silent fail), 그리고 SPRING_API_URL 관련 언급은 더 이상 유효하지 않습니다.

# 결론

**"동작은 한다"와 "운영에 올려도 된다"는 다른 얘기야.** 동시 10명 미만이라는 가정에선 성능/스케일은 문제 없지만(병목은 Gemini API 쪽이지 너 서버가 아냐), **보안·운영 가시성·재현성** 측면에서 그대로 올리면 사고 날 만한 구멍이 여러 개 있어. 아래 🔴 표시 항목은 운영 전에 반드시 막아야 하고, 🟡는 올린 후 바로 보완, 🟢는 여유 있을 때.

---

# 🔴 CRITICAL — 운영 전 반드시 조치

## 1. Google API 키가 평문으로 디스크에 노출됨
- `.env:1` — 실제 키 `AIzaSy...GeMWk` 박혀 있음.
- `.gitignore`에 `.env` 들어있어서 git엔 안 올라가지만, 디스크에 평문으로 떠다니는 거 자체가 문제. 노트북 분실, 백업 유출, 동료 화면공유 한 번이면 끝남. 무엇보다 **이 대화 자체에 키가 노출됐어**. 지금 즉시 폐기하고 새로 발급해.
- 운영에선 시크릿 매니저(GCP Secret Manager / AWS Secrets Manager / Vault / 최소 호스트 환경변수 + chmod 600) 사용. `.env`는 dev에서만.

## 2. CORS 전체 오픈
- `app/main.py:18-23` — `allow_origins=["*"]`, `allow_methods=["*"]`, `allow_headers=["*"]`
- 누구든 자기 사이트에서 너 챗봇 API를 호출할 수 있다는 뜻. 곧 너 API 키로 무료 LLM 호출해주는 봇이 생길 수도 있음.
- `allow_origins=["https://your-frontend.com"]`로 명시. 자격증명 보낼 거 아니면 `allow_credentials`도 명시 안 한 게 맞음.

## 3. 인증/Rate Limit 0%
- `/api/chat`은 누구나 호출 가능 + 호출당 Gemini API 비용이 발생.
- 스크립트 한 번 돌리면 일일 한도 다 태우고 청구서 폭발. 동시 10명이라는 건 "정상 사용자가" 10명일 뿐 어뷰저가 1명만 와도 끝.
- 최소한 다음 중 **두 개**는 필수:
  - 프론트 도메인에서만 받게 하는 토큰/세션 검증 (Spring 쪽 인증 붙이거나 단순 HMAC)
  - per-IP rate limit (`slowapi` 라이브러리 또는 nginx `limit_req`, Cloudflare)
  - Cloudflare Turnstile / reCAPTCHA로 봇 차단

## 4. HTTPS 없음
- Dockerfile/uvicorn이 평문 HTTP 8080으로 그냥 떠 있음.
- 사용자 메시지·세션 ID가 다 평문 노출. 운영망에서 절대 안 됨.
- Nginx/Caddy/Traefik 중 하나로 reverse proxy + Let's Encrypt. Caddy가 가장 간단함(거의 자동).

## 5. 의존성 버전이 전부 floating
- `requirements.txt:1-7` — 전부 버전 핀 0개. `chromadb`만 봐도 마이너 버전마다 API 깨지는 걸로 유명함.
- 오늘 빌드되는 게 내일 빌드 안 될 수 있음. 운영 환경에서 "동일 이미지 재배포"가 보장되지 않음.
- `pip freeze > requirements.lock` 또는 `pip-tools`/`uv`로 lockfile 만들고, Dockerfile에서 lockfile 기준 설치.

## 6. `chromadb/chroma:latest` 태그
- `docker-compose.yml:19` — `latest` 태그는 deploy마다 다른 버전 받음. 어느 날 갑자기 임베딩 컬렉션 호환이 깨질 수 있음.
- 현재 동작 확인된 버전을 핀: 예) `chromadb/chroma:0.5.23` (실제 동작 버전 확인 후 고정).

## 7. Healthcheck 부재
- `docker-compose.yml`의 `chatbot` 서비스에 healthcheck 없음. FastAPI 앱에도 `/health`/`/healthz` 엔드포인트 없음.
- 워커가 데드락에 빠지거나 hung 상태여도 docker는 모른다 → 무한 재시작 안 됨, 사용자만 못 쓰게 됨.
- `app/main.py`에 단순 `@app.get("/healthz")` 추가 + compose에 `curl -f http://localhost:8080/healthz` healthcheck.

---

# 🟡 IMPORTANT — 운영 직후 빠르게 보완

## 8. 컨테이너가 root로 실행됨
- `Dockerfile:1-12` — `USER` 지시자 없음 → root로 동작. 내부 RCE 시 컨테이너 내 권한 무제한.
- `RUN adduser --disabled-password app && USER app` 추가.

## 9. 로깅 설정 없음 + 요청 추적 불가
- `app/routers/chat.py:10`, `app/post_reporter.py:10` — 그냥 `getLogger(__name__)`만 호출. 포맷/레벨/핸들러 설정 0.
- uvicorn 기본 로그가 stdout으로 나오긴 하지만 구조화 안 됐고, 사용자 신고가 들어와도 어떤 요청인지 추적 불가.
- 권장:
  - `main.py`에서 `logging.basicConfig` 또는 dictConfig로 JSON 포맷 + 레벨 ENV로 제어
  - request_id 미들웨어 추가 (X-Request-ID 생성/전파, 로그에 포함)
  - 서버 호스트의 로그 회전 설정 (docker `json-file` 드라이버는 기본 무한 — `max-size`, `max-file` 옵션 필수)

## 10. 에러 모니터링 0
- LLM 호출 실패하면 사용자에겐 한국어 에러 메시지(`chat.py:30`) 보여주고 끝. 너는 모름.
- Sentry(무료 티어로 충분), 또는 최소한 stderr → 파일 → 알림(텔레그램/슬랙 webhook).

## 11. 사용자 메시지 길이 검증 없음
- `app/models.py:4-6` — `message: str`만 있음. 10MB 메시지를 보내도 그대로 임베딩 → Gemini로 전송.
- 비용 폭발 + 응답 시간 증가. `Field(max_length=2000)` 같은 거 필수.

## 12. Spring 호출용 httpx 클라이언트가 매번 새로 만들어짐
- `app/post_reporter.py:39` — 요청마다 `httpx.AsyncClient()` 생성/파괴. TCP 핸드셰이크 + DNS 매번.
- 10명 기준 성능 문제는 아니지만 lifespan 싱글톤으로 하나만 만드는 게 자연스러움. 그리고 연결 끊어졌을 때 재시도 1회 정도는 추가하는 게 좋음 (현재는 실패하면 사용자 신고가 영영 사라짐).

## 13. docker-compose 리소스 제한 없음
- `mem_limit`, `cpus` 미설정 → 챗봇 컨테이너가 메모리 누수 나면 같은 호스트의 chromadb까지 같이 죽음.
- 최소: chatbot 512MB~1GB, chromadb 1~2GB 정도 제한. (실측 후 조정)

## 14. `.env.example` 부재
- 신규 배포자가 어떤 환경변수가 필요한지 모름. 시크릿 없는 템플릿 하나 만들어서 커밋.

## 15. 세션이 in-memory + TTLCache
- `app/llm.py:55` — 컨테이너 재시작/재배포 때 모든 진행중 대화 사라짐.
- 동시 10명 환경에선 가끔 사용자가 "어 갑자기 처음부터 다시 묻네" 정도. 치명적이진 않지만, 배포할 때마다 발생.
- 해결: 세션 스토리지를 Redis로 이전(추가 컨테이너 1개) — 단, 이건 ROI 낮으니 #16과 묶어서 결정.

## 16. uvicorn 워커 1개 + 단일 장애점
- Dockerfile CMD에 `--workers` 없음 → 기본 1개. 워커가 unhandled exception으로 죽으면 컨테이너가 잠시 다운.
- I/O 바운드라 1워커도 10명 처리 충분하지만, 안정성 위해 2개 권장. **단**, 멀티 워커는 in-memory 세션과 충돌(워커마다 캐시 따로) → #15 Redis 이전이 선행돼야 함. 그 전까진 1워커 + 자동 재시작에 의존.

## 17. POST_REPORT 실패 시 silent fail
- `app/post_reporter.py:46-48` — Spring 호출 실패해도 cleaned 텍스트 + `False` 리턴. 사용자에겐 LLM이 이미 "접수했습니다"라고 말한 상태인데 실제로 접수 안 됨.
- 현재 응답에 `report_submitted=False`가 들어가긴 함 → 프론트는 ✓ 배지 안 띄움. 그래도 LLM 본문 텍스트와 모순. 알림(Sentry/슬랙)으로 운영자에게 즉시 통보 필요.

---

# 🟢 RECOMMENDED — 여유 있을 때

## 18. 멀티스테이지 Dockerfile + 이미지 슬림화
- 현재 `COPY . .`으로 `project-docs/`, `.git/`(있다면) 등도 다 포함. `.dockerignore`에 `project-docs/`, `*.md` 추가.
- 빌더 스테이지에서 wheel 만들고, 런타임 스테이지엔 wheel만 복사하면 이미지 100MB대로 줄일 수 있음.

## 19. CI/CD 파이프라인
- 지금은 `docker compose up --build` 수동 실행 가정. 운영에선 GitHub Actions 등으로 빌드 → 이미지 레지스트리 푸시 → 호스트에서 pull/restart.
- 적어도 lint/import-check 정도라도 PR 단위로 돌려줄 것.

## 20. 로컬 ChromaDB 백업 전략
- chroma 데이터는 `chroma_data` 볼륨에만 있음. 호스트 디스크 죽으면 인덱스 날아감.
- 다행히 `docs/` + `scripts/index_docs.py`로 재생성 가능 → 사실상 백업 = `docs/` 폴더 백업. 단, `index_docs.py`가 청크당 13초씩 sleep(`scripts/index_docs.py:111`)이라 큰 문서 인덱싱하면 시간 폭발. 유료 티어로 옮기면 sleep 제거.

## 21. 응답 스트리밍 미적용
- LLM 응답이 5~15초 걸리는데 사용자는 그 동안 typing dot만 봄. 운영 UX엔 마이너스.
- FastAPI `StreamingResponse` + Gemini stream 모드로 바꾸면 체감 속도 확 올라감. 챗봇 자체 기능이라기보단 인프라/UX 영역.

## 22. 컨테이너 타임존
- `python:3.12-slim` 기본 UTC. 로그 타임스탬프가 KST 아니어도 운영엔 문제 없지만, 보고 싶으면 `ENV TZ=Asia/Seoul` + `tzdata` 설치.

## 23. 알려진 코드 이슈
- `project-docs/issues/code-review-findings.md`에 있는 항목 중 아직 안 고친 것:
  - `keep_recent`의 `messages[0]` 의도와 다를 가능성 (`app/llm.py:42-46`)
  - 모델명 코드/문서 불일치 (`app/config.py:19-20` vs `ARCHITECTURE.md:222-223`)
  - Docker compose에서 Spring 네트워크 미연결 (`SPRING_API_URL=http://localhost:8000`은 컨테이너 안에선 자기 자신을 가리킴 — 운영에서 Spring이 다른 호스트면 반드시 수정)
- 이 중 Spring 네트워크 문제는 사실상 🔴급. 운영 호스트에서 Spring이 어디 떠있느냐에 따라 챗봇 → Spring 호출이 아예 안 될 수 있음. 배포 전 `SPRING_API_URL` 점검 필수.

---

# TL;DR — 운영 올리기 전 최소 체크리스트

```
[ ] 1. Google API 키 즉시 폐기 후 재발급, 시크릿 매니저 사용
[ ] 2. CORS allow_origins 실제 프론트 도메인으로 제한
[ ] 3. /api/chat에 rate limit (slowapi 또는 nginx) + 봇 차단(Turnstile 등)
[ ] 4. Caddy/Nginx로 HTTPS 종단
[ ] 5. requirements.txt 버전 핀 (lockfile)
[ ] 6. chromadb/chroma:latest → 특정 버전 핀
[ ] 7. /healthz 엔드포인트 + compose healthcheck
[ ] 8. SPRING_API_URL 운영값 확인 (Docker 네트워크/호스트)
[ ] 9. 사용자 메시지 max_length 제한
[ ] 10. 로그 회전 설정 (docker json-file max-size/max-file)
[ ] 11. 컨테이너 non-root 사용자
[ ] 12. Sentry 또는 최소한의 에러 알림 채널
```

이 12개만 막아도 동시 10명 운영은 충분히 안정적이야. 나머지(🟡 후반~🟢)는 운영하면서 점진적으로.
