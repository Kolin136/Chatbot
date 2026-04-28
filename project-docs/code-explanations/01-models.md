# `app/models.py` 코드 해석

## 파일 역할

챗봇이 다루는 **모든 데이터의 형태(스키마)** 를 정의하는 파일. 로직은 거의 없고 데이터 구조만 들어있음. Pydantic의 `BaseModel`을 상속해서 만든 2개의 클래스로 구성.

총 2개 모델:
1. `ChatRequest` — 사용자 → 챗봇 요청
2. `ChatResponse` — 챗봇 → 사용자 응답

---

## Line 1: 임포트

```python
from pydantic import BaseModel
```

`pydantic` 라이브러리에서 `BaseModel`을 가져온다. **Pydantic**은 Python에서 데이터 검증과 직렬화를 자동으로 해주는 라이브러리.

`BaseModel`을 상속하면 자동으로 얻는 기능:
- 필드 타입 검증 (잘못된 타입 들어오면 자동으로 에러 발생)
- JSON ↔ Python 객체 변환
- FastAPI가 이 모델을 보고 자동으로 OpenAPI 문서 생성

---

## ChatRequest (Line 4-6) — 사용자 요청

```python
class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
```

### 용도

`/api/chat` POST 엔드포인트가 받는 **요청 본문(JSON)** 의 형태.

### 필드별 설명

#### `session_id: str | None = None`
- **타입**: 문자열 또는 `None`
- **기본값**: `None` (요청에서 생략 가능)
- **의미**:
  - 첫 요청에는 세션 ID가 없으므로 `None`을 보냄
  - 서버가 새 UUID를 만들어서 응답에 포함시켜 반환
  - 프론트는 받은 ID를 저장해두고 이후 요청부터 같이 보냄
  - → 서버가 같은 ID로 들어온 요청은 이전 대화 맥락과 이어줌

#### `message: str`
- **타입**: 문자열
- **기본값 없음** → **필수 필드**
- **의미**: 사용자가 입력한 메시지 텍스트
- 누락하면 FastAPI가 자동으로 422 Unprocessable Entity 에러 반환

### 실제 들어오는 JSON 예시

```json
// 첫 요청
{ "message": "발음 점수는 어떻게 매겨지나요?" }

// 두 번째 요청 이후
{ "session_id": "abc-123-def", "message": "더 자세히 알려줘" }
```

---

## ChatResponse (Line 9-11) — 챗봇 응답

```python
class ChatResponse(BaseModel):
    session_id: str
    message: str
```

### 용도

`/api/chat` 엔드포인트가 반환하는 **응답 본문(JSON)** 의 형태.

### 필드별 설명

#### `session_id: str`
- **필수**, 항상 문자열
- **의미**:
  - 첫 요청이면 새로 만든 UUID
  - 이후 요청이면 받은 ID를 그대로 다시 돌려줌
  - 프론트는 이걸 `sessionStorage`에 저장해두고 다음 요청에 포함시킴

#### `message: str`
- **필수**
- **의미**: LLM(Gemini)이 생성한 답변 텍스트

### 실제 응답 JSON 예시

```json
{
  "session_id": "abc-123-def",
  "message": "발음 점수는 정확도, 유창성, 억양 세 항목으로..."
}
```

---

## 전체 데이터 흐름 요약

```
사용자 → ChatRequest (요청)
   ↓
챗봇 처리 (RAG → LLM)
   ↓
사용자 ← ChatResponse (응답)
```

---

## 핵심 정리

`models.py`는 **데이터 형태만 정의하는 파일**이다. 로직은 없다.

이 2개 모델은 챗봇의 입출력 형태를 보여주는 **지도**다. 이 파일을 이해하면 `/api/chat`이 무엇을 받고 무엇을 돌려주는지 그대로 머릿속에 그려진다.
