"""CLI — 한 조합을 채점해 결과를 저장한다.

예)
  .venv/bin/python -m evaluation.run_eval \
      --collection eval_semantic_raw --hybrid --label C_semantic_raw_hybrid \
      --chunking semantic --storage raw --eval-set evaluation/eval_set.json --repeats 3
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

import evaluation  # noqa: F401  (패키지 __init__이 ragas 호환 셰임 적용)
from evaluation.eval_loader import ground_truth_coverage, load_eval_set
from evaluation.pipeline_adapter import MockPipeline, RAGConfig, build_pipeline
from evaluation.runner import collect_samples, run_config

DEFAULT_OUT_DIR = Path(__file__).parent / "results"


def _print_progress(prefix: str):
    def cb(done: int, total: int):
        print(f"\r  {prefix}: {done}/{total}", end="", flush=True)
        if done == total:
            print()
    return cb


def _print_table(bundle) -> None:
    print(f"\n================ {bundle.label} ================")
    print(f"collection={bundle.config['collection_name']} hybrid={bundle.config['hybrid']} "
          f"chunking={bundle.config['chunking']} storage={bundle.config['storage']} "
          f"ground_truth={bundle.has_ground_truth}")
    print(f"{'metric':<42} {'mean':>7} {'±std':>7} {'valid':>8}")
    print("-" * 68)
    for name, m in bundle.metrics.items():
        mean = "  n/a " if m["mean"] is None else f"{m['mean']:.3f}"
        print(f"{name:<42} {mean:>7} {m['std']:>7.3f} {m['n_valid']}/{m['n_total']:>3}")


async def _amain(args) -> int:
    eval_data = load_eval_set(args.eval_set)
    with_gt, total = ground_truth_coverage(eval_data)
    print(f"평가셋: {total}문항, 정답 보유 {with_gt}/{total}"
          f" → {'Recall 포함' if with_gt == total else 'reference-free(정답 일부/없음)'}")

    config = RAGConfig(
        label=args.label,
        collection_name=args.collection,
        hybrid=args.hybrid,
        chunking=args.chunking,
        storage=args.storage,
    )
    pipeline = MockPipeline(config) if args.mock else build_pipeline(config)

    if args.collect_only:
        samples = await collect_samples(pipeline, eval_data, progress_cb=_print_progress("수집"))
        print(f"\n[collect-only] 샘플 {len(samples)}개 수집 완료 — 채점은 건너뜀.")
        print("예시:", {
            "user_input": samples[0].user_input,
            "response": samples[0].response[:60],
            "n_contexts": len(samples[0].retrieved_contexts),
            "reference": (samples[0].reference or "")[:40],
        })
        return 0

    from evaluation.evaluator import build_evaluator
    eval_llm, eval_emb = build_evaluator(args.base_url, args.chat_model, args.embed_model)

    bundle = await run_config(
        config, pipeline, eval_data, eval_llm, eval_emb,
        repeats=args.repeats, max_workers=args.max_workers, timeout=args.timeout,
        answering_cb=_print_progress("answering"),
        scoring_cb=lambda r, n: print(f"  scoring run {r + 1}/{n} …"),
    )

    # provenance 보강
    import ragas
    eval_hash = hashlib.sha256(Path(args.eval_set).read_bytes()).hexdigest()[:12]
    bundle.provenance.update({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ragas_version": ragas.__version__,
        "eval_set": str(args.eval_set),
        "eval_set_sha256_12": eval_hash,
        "judge_chat_model": args.chat_model or "(app.config CHAT_MODEL)",
        "judge_embed_model": args.embed_model or "(app.config EMBEDDING_MODEL)",
        "mock_pipeline": args.mock,
    })

    _print_table(bundle)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_json = args.out_dir / f"{args.label}.json"
    out_json.write_text(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    # CSV(메트릭 평균 한 줄) — 표 비교/엑셀용
    import csv
    out_csv = args.out_dir / f"{args.label}.csv"
    with out_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        names = list(bundle.metrics.keys())
        w.writerow(["label"] + names)
        w.writerow([bundle.label] + [bundle.metrics[n]["mean"] for n in names])
    print(f"\n저장됨: {out_json}  /  {out_csv}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="RAGAS 한 조합 채점")
    p.add_argument("--collection", required=True, help="ChromaDB 컬렉션 이름")
    p.add_argument("--label", required=True, help="결과 라벨(파일명)")
    p.add_argument("--hybrid", action="store_true", help="하이브리드 검색(미지정 시 dense)")
    p.add_argument("--chunking", default="", help="표시용: hybrid|semantic")
    p.add_argument("--storage", default="", help="표시용: raw|summary")
    p.add_argument("--eval-set", required=True, help="평가셋 JSON 경로")
    p.add_argument("--repeats", type=int, default=1, help="채점 반복 횟수(심판 변동성)")
    p.add_argument("--max-workers", type=int, default=2, help="RAGAS 동시성(로컬 모델 보호)")
    p.add_argument("--timeout", type=int, default=180, help="메트릭 호출 타임아웃(초)")
    p.add_argument("--mock", action="store_true", help="MockPipeline 사용(검색·생성 호출 안 함)")
    p.add_argument("--collect-only", action="store_true", help="샘플 수집만, 채점 생략")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--base-url", default=None, help="채점 LLM/임베딩 base_url(미지정 시 app.config)")
    p.add_argument("--chat-model", default=None)
    p.add_argument("--embed-model", default=None)
    args = p.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
