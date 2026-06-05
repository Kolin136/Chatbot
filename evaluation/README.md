# RAGAS 오프라인 A/B 평가 하니스

청킹·저장·검색 **전략 조합**의 RAG 품질을 RAGAS로 채점·비교해, 정량 근거(이력서용 수치)를 만든다.
설계 배경/결정은 [`docs/RAGAS_PLAN.md`](../docs/RAGAS_PLAN.md) 참조.

> 프로덕션 모니터링이 아니라 **오프라인 실험**. 채점은 **로컬 LM Studio**(PIPA), 평가셋 생성만 Gemini(1회).

## 핵심 개념

- **청킹·저장은 색인 시점에 굳는다.** 따라서 조합마다 **컬렉션을 미리 만들어 둔다**(챗봇 UI 사용). 채점기는 `컬렉션 + 검색모드(dense/hybrid)`만 받는다.
- **검색만 질의 시점 플래그**(`hybrid`). 같은 컬렉션을 dense/hybrid로 각각 채점하면 검색 효과가 격리된다.
- **한 번에 한 조합만 채점 → 결과 1건 저장.** 비교는 누적된 결과 파일들로.

## 권장 비교 매트릭스

| 라벨 | 컬렉션(청킹+저장) | 검색 | 격리 대상 |
|---|---|---|---|
| baseline | hybrid + raw (`eval_hybrid_raw`) | dense | 기준선 |
| A | semantic + raw (`eval_semantic_raw`) | dense | A − baseline = **청킹 효과** |
| B | semantic + summary (`eval_semantic_summary`) | dense | B − A = **요약저장 효과** |
| C | semantic + raw (A와 동일 컬렉션) | **hybrid** | C − A = **하이브리드검색 효과** |

→ A와 C는 같은 컬렉션, 검색 플래그만 다름. **컬렉션은 최대 3개**만 만들면 된다.
⚠️ summary 컬렉션 임베딩은 청크당 throttle이 걸려 느릴 수 있다.

## 순서

### 1) 컬렉션 준비 (챗봇 UI)
같은 PDF를 업로드해 위 3가지 청킹×저장 조합으로 임베딩 → 컬렉션 3개 생성.

### 2) 평가셋 생성 + 검수 + 저장
**웹(권장):** **RAGAS 평가** 탭 → `1. 평가셋 만들기` → PDF 선택 + 문항 수 → **[Gemini로 생성]**
→ 생성된 질문/정답을 **검수(편집·삭제)** → 이름 붙여 **[저장]**. 서버에 저장되어 모든 조합에서 재사용된다.

**CLI(대안):**
```bash
.venv/bin/python -m evaluation.generate_evalset \
    --pdf chunking-results/<doc>/<원본>.pdf --n 12 --out evaluation/eval_set.json
```
- 둘 다 Gemini에 PDF를 inline 전송해 `[{question, ground_truth}]`를 생성(GOOGLE_API_KEY 필요 — 추천 기능과 동일 키).
- **⚠️ 한국어 합성은 불안정**할 수 있다. 생성 후 **반드시 사람이 훑어** 깨지거나 근거 약한 항목을 제거/수정한다(웹은 검수 리스트에서 바로).
- 정답(ground_truth)이 모두 채워져 있으면 **Context Recall**까지 측정된다(일부만 있으면 reference-free).
- ⚠️ 생성은 비결정적 → **모든 조합에 같은(저장된) 평가셋**을 써야 비교가 공정.

### 3a) 채점 — 웹 (권장)
**RAGAS 평가** 탭 → `2. 채점 실행` → 컬렉션·검색모드·라벨 선택 + **저장된 평가셋 드롭다운에서 선택** → **평가 시작**.
백그라운드로 채점하며 **30초마다 진행률**을 갱신, 완료 시 점수표·막대그래프 + 저장된 결과 비교표를 보여준다.
조합을 바꿔 다시 돌릴 때 **같은 평가셋을 그대로 선택**하면 공정 비교가 보장된다(서버 저장이라 PDF 재업로드 불필요).

### 3b) 채점 — CLI (대안)
```bash
.venv/bin/python -m evaluation.run_eval \
    --collection eval_semantic_raw --hybrid --label C_semantic_raw_hybrid \
    --chunking semantic --storage raw --eval-set evaluation/eval_set.json --repeats 3
```
결과는 `evaluation/results/<label>.json|csv`에 저장된다.

## 메트릭 (진단 축)

| 메트릭 | 축 | 의미 | 정답 필요 |
|---|---|---|---|
| Faithfulness | 생성 | 환각 여부 | X |
| ResponseRelevancy | 생성 | 질문-답변 적합성 | X |
| LLMContextPrecisionWithoutReference | 검색 | 검색 결과 정밀도 | X |
| LLMContextRecall | 검색 | 정답 커버리지 | **O** |

청킹/검색 전략 효과는 **Precision·Recall**, 생성 품질은 **Faithfulness·ResponseRelevancy**로 본다.

## 공정성·재현성

- **top-k 고정:** 검색 개수는 코드의 `FINAL_TOP_N`(dense·hybrid 공통)을 그대로 사용.
- **같은 평가셋:** 한 비교군은 동일 `eval_set.json`으로만 채점(결과 provenance에 해시 기록).
- **노이즈:** 심판 `temperature=0`, `--repeats`로 반복 → 평균±표준편차. 단일 숫자보다 **상대 델타** 위주로 해석.
- **NaN:** 채점 실패 샘플은 제외 평균 + 유효 개수 표기.
- **요약저장 미묘점:** 채점에 들어가는 컨텍스트는 항상 **원본 텍스트**(`raw_text`)다. 요약은 "검색 매칭"에만 영향 → "요약 기반 검색이 정답 청크를 잘 끌어오나"를 공정하게 측정한다.

## 정직한 한계

- 로컬 심판(`gemma-4-e4b`)은 작은 모델 → 점수 변동·한국어 NaN 가능. 절대점수보다 상대 비교로.
- 질문 10~20개는 통계적 유의성이 약함 → **방향성** 수치로 제시.
- 단일 PDF 결과가 모든 문서에 일반화되진 않음.

## 운영 주의 (실측에서 확인됨)

- **컬렉션 임베딩 차원 일치:** 평가 대상 컬렉션은 **현재 `EMBEDDING_MODEL`(e5-large = 1024차원)로 색인**돼 있어야 한다. 다른 모델(예: 3072차원)로 만든 옛 컬렉션은 검색이 막혀(`dimension mismatch`) 빈 컨텍스트로 처리된다. → 비교 매트릭스 컬렉션 3개는 **지금 모델로 새로 색인**할 것.
- **로컬 심판 컨텍스트 한도:** `Faithfulness`/`ContextPrecision`은 검색된 컨텍스트 전체를 심판에 넣는다. 컨텍스트가 길면 작은 모델이 `Context size exceeded`로 해당 샘플을 NaN 처리한다(하니스는 NaN 제외 평균 + valid 개수로 graceful 처리). 더 깨끗한 수치가 필요하면 LM Studio에서 **컨텍스트 윈도우가 큰 심판 모델**을 쓰거나 top-k를 줄인다. `ResponseRelevancy`(답변만 사용)는 영향이 적다.

## 의존성 메모 (왜 이렇게 깔렸나)

- 본 프로젝트는 **langchain 1.x**. `ragas==0.4.3`에 핀 고정(0.2.x는 구 langchain 전제라 충돌).
- ragas 0.4.3는 (1) `instructor`가 `mistralai` 1.x API를 기대 → `mistralai<2`, (2) sunset된
  `langchain_community.chat_models.vertexai`를 top-level import → `_ragas_compat.py` 셰임을
  ragas import 전에 적용(미사용 Vertex 클래스만 stub). `import evaluation` 시 자동 적용된다.
- metrics는 classic 경로(`ragas.metrics.*`) 사용. 0.4.3에서 deprecation 경고가 뜨지만 classic
  `evaluate()`와 함께 동작하는 건 이쪽. ragas 1.0 이전 환경 한정(향후 `ragas.metrics.collections`로 이전).
