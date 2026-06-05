// RAGAS 평가 페이지 — 평가셋 생성/검수/저장 + 조합 채점(웹 백그라운드 + 30초 폴링) + 결과 비교
// 기존 디자인 토큰/컴포넌트(card, btn, Progress, Pill, ToggleField, FileDropzone, Icon) 재사용.

const EVAL_POLL_MS = 30000; // 사용자 요청: 30초 간격 폴링

const RAGAS_METRIC_META = {
  faithfulness: { name: "Faithfulness", axis: "생성", desc: "환각 여부", tone: "info" },
  answer_relevancy: { name: "Answer Relevancy", axis: "생성", desc: "질문-답변 적합성", tone: "info" },
  llm_context_precision_without_reference: { name: "Context Precision", axis: "검색", desc: "검색 결과 정밀도", tone: "accent" },
  context_recall: { name: "Context Recall", axis: "검색", desc: "정답 커버리지", tone: "accent" },
};
function _metricMeta(key) {
  return RAGAS_METRIC_META[key] || { name: key, axis: "", desc: "", tone: "muted" };
}

// 폼 칸 아래 작은 설명
function Help({ children }) {
  return <div className="ragas-help">{children}</div>;
}

function RagasPage() {
  const [collections, setCollections] = useState([]);
  const [collection, setCollection] = useState("");
  const [hybrid, setHybrid] = useState(false);
  const [chunking, setChunking] = useState("");
  const [storage, setStorage] = useState("");
  const [label, setLabel] = useState("");
  const [repeats, setRepeats] = useState(1);
  const [selectedSet, setSelectedSet] = useState(""); // 채점에 쓸 저장 평가셋 이름
  const [savedSets, setSavedSets] = useState([]);

  const [phase, setPhase] = useState("setup"); // setup | evaluating | done
  const [jobId, setJobId] = useState(null);
  const [progress, setProgress] = useState(0);
  const [step, setStep] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [savedResults, setSavedResults] = useState([]);

  useEffect(() => {
    window.api.listCollections().then((r) => setCollections(r.collections || [])).catch(() => {});
    refreshSets();
    refreshResults();
  }, []);

  const refreshSets = () => window.api.listEvalSets().then((r) => setSavedSets(r.eval_sets || [])).catch(() => {});
  const refreshResults = () => window.api.listEvaluationResults().then((r) => setSavedResults(r.results || [])).catch(() => {});

  const canStart = collection && label.trim() && selectedSet && phase !== "evaluating";

  const start = async () => {
    setError("");
    try {
      const payload = {
        collection, label: label.trim(), hybrid, chunking, storage,
        eval_set_name: selectedSet, repeats: Number(repeats) || 1,
      };
      const res = await window.api.startEvaluation(payload);
      setJobId(res.eval_job_id);
      setProgress(0); setStep("prepare"); setMessage("준비 중"); setResult(null);
      setPhase("evaluating");
    } catch (e) {
      setError(e.message || "평가 시작 실패");
    }
  };

  useEffect(() => {
    if (phase !== "evaluating" || !jobId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const s = await window.api.getEvaluationStatus(jobId);
        if (cancelled) return;
        setProgress(s.progress ?? 0);
        setStep(s.step || "");
        setMessage(s.message || "");
        if (s.status === "completed") {
          setResult(s.result || null);
          setPhase("done");
          refreshResults();
          return;
        }
        if (s.status === "failed") {
          setError(s.error || "평가 실패");
          setPhase("setup");
          return;
        }
        setTimeout(tick, EVAL_POLL_MS);
      } catch (e) {
        if (!cancelled) { setError(e.message || "상태 조회 실패"); setPhase("setup"); }
      }
    };
    tick();
    return () => { cancelled = true; };
  }, [phase, jobId]);

  const reset = () => { setPhase("setup"); setJobId(null); setResult(null); setProgress(0); };

  return (
    <main className="page page-ragas">
      <div className="ragas-inner">
        <div className="ragas-head">
          <div className="phase-title">RAGAS 평가</div>
          <div className="phase-sub">청킹·저장·검색 전략 조합의 RAG 품질을 채점하고 비교합니다. <span style={{ whiteSpace: "nowrap" }}>(로컬 LM Studio 채점)</span></div>
        </div>

        {phase === "setup" && (
          <>
            <RagasEvalSetManager savedSets={savedSets} onChanged={refreshSets} />
            <RagasSetup
              collections={collections} collection={collection} setCollection={setCollection}
              hybrid={hybrid} setHybrid={setHybrid}
              chunking={chunking} setChunking={setChunking}
              storage={storage} setStorage={setStorage}
              label={label} setLabel={setLabel}
              repeats={repeats} setRepeats={setRepeats}
              savedSets={savedSets} selectedSet={selectedSet} setSelectedSet={setSelectedSet}
              canStart={canStart} onStart={start} error={error}
            />
          </>
        )}

        {phase === "evaluating" && (
          <RagasProgress label={label} progress={progress} step={step} message={message} />
        )}

        {phase === "done" && result && (
          <RagasResult result={result} onReset={reset} />
        )}

        <RagasComparison saved={savedResults} onRefresh={refreshResults} />
      </div>
    </main>
  );
}

// ── 평가셋 만들기/검수/저장 ─────────────────────────────────
function RagasEvalSetManager({ savedSets, onChanged }) {
  const [file, setFile] = useState(null);
  const [n, setN] = useState(12);
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState(null); // 검수 중 평가셋
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [savedOk, setSavedOk] = useState(false);

  const generate = async () => {
    if (!file) return;
    setErr(""); setLoading(true); setSavedOk(false);
    try {
      const res = await window.api.generateEvalset(file, Number(n) || 12);
      setItems(res.items || []);
      if (!name) {
        // macOS는 한글 파일명을 자모 분해(NFD)로 줌 → NFC로 합쳐야 완성형 한글이 보존됨
        const base = (file.name || "evalset")
          .normalize("NFC")
          .replace(/\.pdf$/i, "")
          .replace(/[^A-Za-z0-9_\-가-힣]+/g, "_")
          .replace(/^_+|_+$/g, "");
        setName(base || "evalset");
      }
    } catch (e) {
      setErr(e.message || "평가셋 생성 실패");
    }
    setLoading(false);
  };

  const editItem = (i, key, val) => setItems(items.map((it, idx) => (idx === i ? { ...it, [key]: val } : it)));
  const delItem = (i) => setItems(items.filter((_, idx) => idx !== i));

  const save = async () => {
    setErr("");
    try {
      await window.api.saveEvalSet(name.trim(), items);
      setSavedOk(true);
      onChanged && onChanged();
    } catch (e) {
      setErr(e.message || "저장 실패");
    }
  };

  const gtCount = items ? items.filter((it) => (it.ground_truth || "").trim()).length : 0;

  return (
    <div className="card ragas-card">
      <div className="ragas-section-title">1. 평가셋 만들기</div>
      <Help>
        PDF를 올리면 <b>Gemini가 질문+모범답안을 자동 생성</b>해요. 검수(편집·삭제) 후 이름을 붙여 저장하면,
        아래 '채점 실행'에서 골라 재사용합니다. ⚠️ <b>모든 조합에 같은 평가셋</b>을 써야 비교가 공정해요(한 번 만들고 계속 재사용).
      </Help>

      <div className="ragas-gen-row">
        <div className="ragas-gen-drop">
          <FileDropzone file={file} onFile={setFile} accept=".pdf" />
        </div>
        <div className="ragas-gen-controls">
          <label className="ragas-field">
            <span className="ragas-label">문항 수</span>
            <input className="input" type="number" min="3" max="50" value={n}
              onChange={(e) => setN(e.target.value)} />
          </label>
          <Button variant="primary" disabled={!file || loading} onClick={generate}
            iconLeft={<Icon.Sparkles w={16} h={16} />}>
            {loading ? "생성 중…" : "Gemini로 생성"}
          </Button>
        </div>
      </div>
      <Help>※ 한국어 PDF는 일부 항목이 어색할 수 있어요. 생성 후 꼭 훑어보고 이상한 건 지우세요. (생성엔 GOOGLE_API_KEY 필요)</Help>

      {err && <div className="ragas-error"><Icon.AlertCircle w={16} h={16} /> {err}</div>}

      {items && (
        <div className="ragas-review">
          <div className="ragas-section-subtitle">검수 — {items.length}문항 · 정답 {gtCount}/{items.length} (편집·삭제 후 저장)</div>
          <div className="ragas-review-list">
            {items.map((it, i) => (
              <div key={i} className="ragas-review-item">
                <div className="ragas-review-num">{i + 1}</div>
                <div className="ragas-review-fields">
                  <textarea className="input ragas-textarea" value={it.question} placeholder="질문"
                    onChange={(e) => editItem(i, "question", e.target.value)} />
                  <textarea className="input ragas-textarea" value={it.ground_truth || ""}
                    placeholder="모범답안(정답) — 비우면 이 항목은 Recall 측정에서 제외"
                    onChange={(e) => editItem(i, "ground_truth", e.target.value)} />
                </div>
                <button className="btn btn-ghost btn-sm" onClick={() => delItem(i)} title="삭제">
                  <Icon.Trash w={15} h={15} />
                </button>
              </div>
            ))}
          </div>
          <div className="ragas-save-row">
            <label className="ragas-field ragas-save-name">
              <span className="ragas-label">평가셋 이름</span>
              <input className="input" value={name} placeholder="예: seok_doc"
                onChange={(e) => { setName(e.target.value); setSavedOk(false); }} />
              <Help>영문/숫자/한글/_/- 만. 이 이름으로 아래 채점에서 골라 써요.</Help>
            </label>
            <Button variant="primary" disabled={!name.trim() || !items.length} onClick={save}
              iconLeft={<Icon.Check w={16} h={16} />}>저장</Button>
            {savedOk && <Pill tone="success">저장됨</Pill>}
          </div>
        </div>
      )}

      {savedSets && savedSets.length > 0 && (
        <div className="ragas-saved-list">
          <span className="ragas-muted">저장된 평가셋:</span>
          {savedSets.map((s) => (
            <Pill key={s.name} tone="info">{s.name} · {s.count}문항 · 정답 {s.with_gt}</Pill>
          ))}
        </div>
      )}
    </div>
  );
}

// ── 채점 실행 폼 ─────────────────────────────────────────────
function RagasSetup(props) {
  const {
    collections, collection, setCollection, hybrid, setHybrid,
    chunking, setChunking, storage, setStorage, label, setLabel,
    repeats, setRepeats, savedSets, selectedSet, setSelectedSet, canStart, onStart, error,
  } = props;

  return (
    <div className="card ragas-card">
      <div className="ragas-section-title">2. 채점 실행</div>
      <div className="ragas-grid">
        <label className="ragas-field">
          <span className="ragas-label">컬렉션</span>
          <select className="input" value={collection} onChange={(e) => setCollection(e.target.value)}>
            <option value="">컬렉션 선택…</option>
            {collections.map((c) => (
              <option key={c.name} value={c.name}>{c.name} ({c.count})</option>
            ))}
          </select>
          <Help>채점할 대상 데이터. 이 컬렉션이 어떤 청킹·저장으로 만들어졌는지는 색인할 때 이미 정해졌어요.</Help>
        </label>

        <label className="ragas-field">
          <span className="ragas-label">결과 라벨</span>
          <input className="input" value={label} placeholder="예: A_요약저장"
            onChange={(e) => setLabel(e.target.value)} />
          <Help>이 채점 결과의 이름표. 아래 비교표에서 이 이름으로 구분돼요.</Help>
        </label>

        <label className="ragas-field">
          <span className="ragas-label">평가셋</span>
          <select className="input" value={selectedSet} onChange={(e) => setSelectedSet(e.target.value)}>
            <option value="">평가셋 선택…</option>
            {savedSets.map((s) => (
              <option key={s.name} value={s.name}>{s.name} ({s.count}문항, 정답 {s.with_gt})</option>
            ))}
          </select>
          <Help>위 1번에서 만들어 저장한 평가셋을 고르세요. 모든 조합에 같은 걸 써야 공정해요.</Help>
        </label>

        <label className="ragas-field">
          <span className="ragas-label">청킹 (표시용)</span>
          <select className="input" value={chunking} onChange={(e) => setChunking(e.target.value)}>
            <option value="">—</option>
            <option value="hybrid">hybrid (Docling)</option>
            <option value="semantic">semantic (LangChain)</option>
          </select>
          <Help>동작에 영향 없음. 결과에 '무슨 청킹이었는지' 메모만 남겨요. 비워도 됩니다.</Help>
        </label>

        <label className="ragas-field">
          <span className="ragas-label">저장 (표시용)</span>
          <select className="input" value={storage} onChange={(e) => setStorage(e.target.value)}>
            <option value="">—</option>
            <option value="raw">raw (원본)</option>
            <option value="summary">summary (요약)</option>
          </select>
          <Help>동작에 영향 없음. '원본/요약 저장' 메모용. 비워도 됩니다.</Help>
        </label>

        <label className="ragas-field">
          <span className="ragas-label">채점 반복</span>
          <input className="input" type="number" min="1" max="10" value={repeats}
            onChange={(e) => setRepeats(e.target.value)} />
          <Help>보통 1. 심판(LLM) 점수가 흔들릴까 봐 여러 번 평균내고 싶을 때만 늘리세요.</Help>
        </label>
      </div>

      <div className="ragas-toggle-row">
        <ToggleField
          on={hybrid} onChange={setHybrid}
          title="하이브리드 검색 (BM25 + RRF)"
          description="켜면 BM25+RRF, 끄면 dense. 같은 컬렉션을 켜고/끄고 두 번 돌리면 검색 방식의 효과를 비교할 수 있어요."
        />
      </div>

      {error && <div className="ragas-error"><Icon.AlertCircle w={16} h={16} /> {error}</div>}

      <div className="ragas-actions">
        <Button variant="primary" disabled={!canStart} onClick={onStart}
          iconLeft={<Icon.Sparkles w={16} h={16} />}>
          평가 시작
        </Button>
        <span className="ragas-muted">채점은 로컬 LM Studio로 수 분~수십 분 걸릴 수 있어요(30초마다 진행률 갱신).</span>
      </div>
    </div>
  );
}

// ── 진행 상태 ─────────────────────────────────────────────
function RagasProgress({ label, progress, step, message }) {
  const stepLabel = { prepare: "준비", answering: "질문 처리", scoring: "RAGAS 채점", done: "완료" }[step] || step;
  return (
    <div className="card ragas-card ragas-progress-card">
      <div className="ragas-progress-head">
        <div className="ragas-progress-icon"><Icon.Sparkles w={26} h={26} /></div>
        <div>
          <div className="ragas-progress-title">{label} 평가 중</div>
          <div className="ragas-progress-step">{stepLabel}</div>
        </div>
        <div className="ragas-progress-pct">{progress}%</div>
      </div>
      <Progress value={progress} />
      <div className="ragas-progress-msg">{message}</div>
      <div className="ragas-progress-meta">
        <Pill tone="muted" icon={<Icon.Clock w={13} h={13} />}>30초마다 상태 확인</Pill>
        <Pill tone="info">백그라운드 채점</Pill>
      </div>
    </div>
  );
}

// ── 결과 ─────────────────────────────────────────────
function RagasResult({ result, onReset }) {
  const metrics = result.metrics || {};
  const keys = Object.keys(metrics);
  const prov = result.provenance || {};
  return (
    <div className="card ragas-card">
      <div className="ragas-result-head">
        <div>
          <div className="ragas-progress-title">{result.label} · 결과</div>
          <div className="ragas-muted">
            컬렉션 {result.config?.collection_name} · 검색 {result.config?.hybrid ? "hybrid" : "dense"}
            {result.config?.chunking ? ` · 청킹 ${result.config.chunking}` : ""}
            {result.config?.storage ? ` · 저장 ${result.config.storage}` : ""}
            {" · "}{result.has_ground_truth ? "정답 포함" : "reference-free"}
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={onReset} iconLeft={<Icon.ArrowLeft w={15} h={15} />}>새 평가</Button>
      </div>

      <div className="ragas-metrics">
        {keys.map((k) => {
          const m = metrics[k];
          const meta = _metricMeta(k);
          const pct = m.mean == null ? 0 : m.mean * 100;
          return (
            <div key={k} className="ragas-metric">
              <div className="ragas-metric-top">
                <span className="ragas-metric-name">{meta.name}</span>
                <Pill tone={meta.tone}>{meta.axis}</Pill>
              </div>
              <div className="ragas-metric-desc">{meta.desc}</div>
              <Progress value={pct} />
              <div className="ragas-metric-val">
                {m.mean == null ? "n/a" : m.mean.toFixed(3)}
                {m.std ? <span className="ragas-muted"> ±{m.std.toFixed(3)}</span> : null}
                <span className="ragas-muted"> · valid {m.n_valid}/{m.n_total}</span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="ragas-prov">
        <Pill tone="muted">문항 {prov.n_questions ?? "—"}</Pill>
        <Pill tone="muted">반복 {prov.repeats ?? 1}</Pill>
        {prov.eval_set_name && <Pill tone="muted">평가셋 {prov.eval_set_name}</Pill>}
        {prov.ragas_version && <Pill tone="muted">ragas {prov.ragas_version}</Pill>}
        {prov.timestamp && <Pill tone="muted">{prov.timestamp}</Pill>}
      </div>
    </div>
  );
}

// ── 결과 비교 (저장된 결과들) ─────────────────────────────
function RagasComparison({ saved, onRefresh }) {
  if (!saved || !saved.length) return null;
  const metricKeys = [];
  saved.forEach((r) => Object.keys(r.metrics || {}).forEach((k) => { if (!metricKeys.includes(k)) metricKeys.push(k); }));

  return (
    <div className="card ragas-card">
      <div className="ragas-result-head">
        <div className="ragas-progress-title">결과 비교 ({saved.length})</div>
        <Button variant="ghost" size="sm" onClick={onRefresh} iconLeft={<Icon.RefreshCw w={15} h={15} />}>새로고침</Button>
      </div>
      <div className="ragas-table-scroll">
        <table className="ragas-table">
          <thead>
            <tr>
              <th>메트릭</th>
              {saved.map((r) => <th key={r.label}>{r.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {metricKeys.map((k) => (
              <tr key={k}>
                <td className="ragas-table-metric">{_metricMeta(k).name}</td>
                {saved.map((r) => {
                  const m = (r.metrics || {})[k];
                  return <td key={r.label} className="ragas-table-num">{m && m.mean != null ? m.mean.toFixed(3) : "—"}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="ragas-muted ragas-compare-note">
        한 축만 바꾼 두 결과의 차이가 그 축의 효과입니다 (예: 같은 컬렉션의 dense vs hybrid → 검색 효과).
      </div>
    </div>
  );
}
