// 청킹 페이지 — 업로드 → 청킹 진행 → 완료 → 임베딩 진행 → 완료
// 한 페이지 안에서 phase 상태로 UI를 교체.

function ChunkingPage({ onGoChat }) {
  const [phase, setPhase] = useState("upload");
  // phases: upload | chunking | chunked | embedding | embedded

  const [file, setFile] = useState(null);
  const [doOcr, setDoOcr] = useState(false);
  const [strategy, setStrategy] = useState("docling_hybrid");

  // 청킹 진행
  const [jobId, setJobId] = useState(null);
  const [docName, setDocName] = useState("");
  const [chunkProgress, setChunkProgress] = useState(0);
  const [chunkStep, setChunkStep] = useState("");
  const [chunkMessage, setChunkMessage] = useState("");
  const [chunkResult, setChunkResult] = useState(null);
  const [chunkError, setChunkError] = useState(null);

  // 청크 미리보기 모달
  const [chunkModal, setChunkModal] = useState(false);
  const [chunks, setChunks] = useState(null);
  const [chunksLoading, setChunksLoading] = useState(false);

  // 임베딩
  const [collectionName, setCollectionName] = useState("");
  const [collectionTouched, setCollectionTouched] = useState(false);
  const [embedJobId, setEmbedJobId] = useState(null);
  const [embedProgress, setEmbedProgress] = useState(0);
  const [embedStep, setEmbedStep] = useState("");
  const [embedMessage, setEmbedMessage] = useState("");
  const [embedResult, setEmbedResult] = useState(null);
  const [embedError, setEmbedError] = useState(null);

  // ============== 청킹 시작 ==============
  const startChunking = async () => {
    if (!file) return;
    setChunkError(null);
    setPhase("chunking");
    setChunkProgress(0);
    setChunkMessage("업로드 중…");
    try {
      const up = await window.api.uploadPdf(file, doOcr, strategy);
      setJobId(up.job_id);
      setDocName(up.doc_name);
    } catch (e) {
      setChunkError(e.message || "업로드 실패");
      setPhase("upload");
    }
  };

  // 청킹 폴링
  useEffect(() => {
    if (phase !== "chunking" || !jobId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const s = await window.api.getUploadStatus(jobId);
        if (cancelled) return;
        setChunkProgress(s.progress ?? 0);
        setChunkStep(s.step || "");
        setChunkMessage(s.message || "");
        if (s.status === "completed") {
          setChunkResult(s.result || null);
          setPhase("chunked");
          return;
        }
        if (s.status === "failed") {
          setChunkError(s.error || "청킹 실패");
          return;
        }
        setTimeout(tick, window.APP_CONFIG.POLL_INTERVAL_MS);
      } catch (e) {
        if (!cancelled) {
          setChunkError(e.message || "상태 조회 실패");
        }
      }
    };
    tick();
    return () => { cancelled = true; };
  }, [phase, jobId]);

  // ============== 청크 미리보기 열기 ==============
  const openChunkPreview = async () => {
    setChunkModal(true);
    if (chunks) return;
    if (!docName) {
      setChunks([]);
      return;
    }
    setChunksLoading(true);
    try {
      const data = await window.api.getChunks(docName);
      setChunks(data.chunks || []);
    } catch (e) {
      setChunks([]);
    } finally {
      setChunksLoading(false);
    }
  };

  // ============== 임베딩 시작 ==============
  const startEmbedding = async () => {
    if (!collectionName.trim()) {
      setCollectionTouched(true);
      return;
    }
    setEmbedError(null);
    setPhase("embedding");
    setEmbedProgress(0);
    setEmbedMessage("준비 중…");
    try {
      const res = await window.api.startEmbedding(docName, collectionName.trim());
      setEmbedJobId(res.embed_job_id);
    } catch (e) {
      setEmbedError(e.message || "임베딩 시작 실패");
      setPhase("chunked");
    }
  };

  useEffect(() => {
    if (phase !== "embedding" || !embedJobId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const s = await window.api.getEmbedStatus(embedJobId);
        if (cancelled) return;
        setEmbedProgress(s.progress ?? 0);
        setEmbedStep(s.step || "");
        setEmbedMessage(s.message || "");
        if (s.status === "completed") {
          setEmbedResult(s.result || null);
          setPhase("embedded");
          return;
        }
        if (s.status === "failed") {
          setEmbedError(s.error || "임베딩 실패");
          return;
        }
        setTimeout(tick, window.APP_CONFIG.POLL_INTERVAL_MS);
      } catch (e) {
        if (!cancelled) {
          setEmbedError(e.message || "상태 조회 실패");
        }
      }
    };
    tick();
    return () => { cancelled = true; };
  }, [phase, embedJobId]);

  // 처음부터 다시
  const reset = () => {
    setPhase("upload");
    setFile(null);
    setJobId(null);
    setChunkProgress(0);
    setChunkResult(null);
    setChunkError(null);
    setChunks(null);
    setCollectionName("");
    setCollectionTouched(false);
    setEmbedJobId(null);
    setEmbedProgress(0);
    setEmbedResult(null);
    setEmbedError(null);
  };

  const currentRailStep =
    phase === "upload" ? "upload" :
    phase === "embed_select" ? "embed" :
    phase === "chunking" ? "chunk" :
    phase === "chunked" ? "embed" :
    phase === "embedding" ? "embed" :
    "done";

  // 기존 청킹 결과 선택 시
  const selectExistingChunking = (item) => {
    setDocName(item.doc_name);
    setChunkResult({
      chunk_count: item.chunk_count,
      picture_count: item.picture_count,
      table_count: item.table_count,
    });
    setJobId(null); // 메모리 job 없음
    setChunks(null); // 이전 청크 캐시 비우기 → 미리보기 시 새로 로드
    setCollectionName("");
    setCollectionTouched(false);
    setEmbedError(null);
    setPhase("chunked");
  };

  return (
    <div className="page page-chunking">
      <div className="page-chunking-inner">
        <StepRail current={currentRailStep} />

        <div className="phase-stage">
          {phase === "upload" && (
            <UploadPhase
              file={file}
              setFile={setFile}
              doOcr={doOcr}
              setDoOcr={setDoOcr}
              strategy={strategy}
              setStrategy={setStrategy}
              error={chunkError}
              onStart={startChunking}
              onGoEmbedSelect={() => setPhase("embed_select")}
            />
          )}
          {phase === "embed_select" && (
            <ChunkingSelectPhase
              onSelect={selectExistingChunking}
              onBack={() => setPhase("upload")}
            />
          )}
          {phase === "chunking" && (
            <ProgressPhase
              kind="chunk"
              title="청킹 진행 중"
              docName={docName || file?.name}
              progress={chunkProgress}
              step={chunkStep}
              message={chunkMessage}
              error={chunkError}
            />
          )}
          {phase === "chunked" && (
            <ChunkedPhase
              docName={docName}
              result={chunkResult}
              collectionName={collectionName}
              setCollectionName={setCollectionName}
              touched={collectionTouched}
              setTouched={setCollectionTouched}
              onPreview={openChunkPreview}
              onEmbed={startEmbedding}
              onReset={reset}
              error={embedError}
            />
          )}
          {phase === "embedding" && (
            <ProgressPhase
              kind="embed"
              title="임베딩 진행 중"
              docName={`컬렉션 "${collectionName}" 에 저장`}
              progress={embedProgress}
              step={embedStep}
              message={embedMessage}
              error={embedError}
            />
          )}
          {phase === "embedded" && (
            <EmbeddedPhase
              result={embedResult}
              docName={docName}
              collectionName={collectionName}
              onChat={() => onGoChat(collectionName)}
              onReset={reset}
            />
          )}
        </div>
      </div>

      <Modal
        open={chunkModal}
        onClose={() => setChunkModal(false)}
        title={`청크 결과 미리보기 · ${docName || ""}`}
        width={980}
        footer={
          <Button variant="ghost" onClick={() => setChunkModal(false)}>닫기</Button>
        }
      >
        {chunksLoading ? (
          <div className="chunk-loading">청크 불러오는 중…</div>
        ) : chunks ? (
          <ChunkViewer chunks={chunks} />
        ) : null}
      </Modal>
    </div>
  );
}

// ============================================================
// Phase: 업로드
// ============================================================
function UploadPhase({ file, setFile, doOcr, setDoOcr, strategy, setStrategy, error, onStart, onGoEmbedSelect }) {
  return (
    <div className="phase anim-in">
      <div className="phase-hero">
        <Pill tone="accent" icon={<Icon.Sparkles w={12} h={12} />}>STEP 1 / 3</Pill>
        <h1 className="phase-title">PDF를 청킹할 준비가 되었어요</h1>
        <p className="phase-sub">PDF를 업로드하면 의미 단위로 자르고 메타데이터를 추출해 드릴게요.</p>
      </div>

      <div className="card phase-card">
        <FileDropzone file={file} onFile={setFile} />

        <div className="divider" />

        <div className="strategy-field">
          <div className="strategy-field-label">청킹 전략</div>
          <div className="strategy-field-desc">
            PDF를 어떤 방식으로 청크 단위로 자를지 선택하세요.
          </div>
          <div className="strategy-options">
            <label className={"strategy-option" + (strategy === "docling_hybrid" ? " active" : "")}>
              <input
                type="radio"
                name="strategy"
                value="docling_hybrid"
                checked={strategy === "docling_hybrid"}
                onChange={(e) => setStrategy(e.target.value)}
              />
              <div className="strategy-option-text">
                <div className="strategy-option-name">Docling Hybrid</div>
                <div className="strategy-option-sub">문서 구조 단위 + 토큰 한도. 빠르고 안정적.</div>
              </div>
            </label>
            <label className={"strategy-option" + (strategy === "langchain_semantic" ? " active" : "")}>
              <input
                type="radio"
                name="strategy"
                value="langchain_semantic"
                checked={strategy === "langchain_semantic"}
                onChange={(e) => setStrategy(e.target.value)}
              />
              <div className="strategy-option-text">
                <div className="strategy-option-name">LangChain Semantic</div>
                <div className="strategy-option-sub">임베딩 유사도 기반 의미 단위. 느리지만 의미 흐름 우선.</div>
              </div>
            </label>
          </div>
        </div>

        <div className="divider" />

        <ToggleField
          on={doOcr}
          onChange={setDoOcr}
          title="OCR 사용"
          description="스캔된 이미지·그림 안의 글자도 인식해서 텍스트로 변환합니다. 일반 텍스트 PDF만 있다면 꺼두면 더 빨라요."
        />

        {error && (
          <div className="error-banner">
            <Icon.AlertCircle w={16} h={16} />
            <span>{error}</span>
          </div>
        )}

        <div className="phase-actions">
          <Button
            variant="primary"
            size="lg"
            disabled={!file}
            onClick={onStart}
            iconRight={<Icon.ArrowRight w={18} h={18} />}
          >
            청킹 시작
          </Button>
        </div>
      </div>

      <div className="phase-alt-action">
        <span className="phase-alt-text">이미 청킹된 결과가 있나요?</span>
        <button type="button" className="phase-alt-link" onClick={onGoEmbedSelect}>
          기존 청킹 결과로 임베딩하기
          <Icon.ArrowRight w={14} h={14} />
        </button>
      </div>
    </div>
  );
}

// ============================================================
// Phase: 기존 청킹 결과 선택 (임베딩 재진입)
// ============================================================
function ChunkingSelectPhase({ onSelect, onBack }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await window.api.listChunkings();
        setItems(data.chunkings || []);
      } catch (e) {
        setError(e.message || "목록을 불러오지 못했습니다.");
      }
    })();
  }, []);

  return (
    <div className="phase anim-in">
      <div className="phase-hero">
        <Pill tone="accent" icon={<Icon.Database w={12} h={12} />}>임베딩 재진입</Pill>
        <h1 className="phase-title">청킹 결과를 선택해 주세요</h1>
        <p className="phase-sub">이미 청킹된 문서를 골라 바로 임베딩 단계로 넘어갈 수 있어요.</p>
      </div>

      <div className="card phase-card">
        {error && (
          <div className="error-banner">
            <Icon.AlertCircle w={16} h={16} />
            <span>{error}</span>
          </div>
        )}

        {items === null && !error && (
          <div className="chunk-loading">목록 불러오는 중…</div>
        )}

        {items && items.length === 0 && (
          <div className="empty-state">
            <Icon.Database w={26} h={26} />
            <div className="empty-title">아직 청킹된 결과가 없어요</div>
            <div className="empty-sub">PDF를 먼저 업로드해 주세요.</div>
          </div>
        )}

        {items && items.length > 0 && (
          <div className="chunking-list">
            {items.map((it) => (
              <button
                key={it.doc_name}
                type="button"
                className="chunking-item"
                onClick={() => onSelect(it)}
              >
                <div className="chunking-item-main">
                  <div className="chunking-item-name mono-id">{it.doc_name}</div>
                  <div className="chunking-item-meta">
                    <span>청크 {it.chunk_count}</span>
                    <span>·</span>
                    <span>이미지 {it.picture_count}</span>
                    <span>·</span>
                    <span>표 {it.table_count}</span>
                    {it.created_at && (
                      <>
                        <span>·</span>
                        <span>{formatCreatedAt(it.created_at)}</span>
                      </>
                    )}
                  </div>
                </div>
                <Icon.ArrowRight w={18} h={18} />
              </button>
            ))}
          </div>
        )}

        <div className="phase-actions phase-actions-spread">
          <Button variant="ghost" onClick={onBack} iconLeft={<Icon.ArrowLeft w={16} h={16} />}>
            PDF 업로드로 돌아가기
          </Button>
        </div>
      </div>
    </div>
  );
}

function formatCreatedAt(iso) {
  if (!iso) return "";
  // "2026-05-11T19:47:52" → "2026-05-11 19:47"
  return iso.replace("T", " ").slice(0, 16);
}

// ============================================================
// Phase: 진행 (청킹 / 임베딩 공통)
// ============================================================
function ProgressPhase({ kind, title, docName, progress, step, message, error }) {
  const Icn = kind === "chunk" ? Icon.Layers : Icon.Database;
  return (
    <div className="phase anim-in">
      <div className="phase-hero">
        <Pill tone="accent" icon={<Icon.Sparkles w={12} h={12} />}>
          {kind === "chunk" ? "STEP 2 / 3" : "STEP 3 / 3"}
        </Pill>
        <h1 className="phase-title">{title}</h1>
        <p className="phase-sub">{docName}</p>
      </div>

      <div className="card phase-card progress-card">
        <div className="progress-headline">
          <div className="progress-icon">
            <Icn w={26} h={26} />
          </div>
          <div className="progress-percent">
            <div className="progress-percent-num">{progress}%</div>
            <div className="progress-step-label">{step ? labelForStep(kind, step) : "준비 중"}</div>
          </div>
        </div>

        <Progress value={progress} />

        <div className="progress-message">
          {error ? (
            <span className="progress-message-error">
              <Icon.AlertCircle w={14} h={14} />
              {error}
            </span>
          ) : (
            <span>{message}</span>
          )}
        </div>

        <div className="progress-meta">
          <Pill tone="muted" icon={<Icon.Clock w={11} h={11} />}>2초마다 상태 확인</Pill>
          <Pill tone="info">{kind === "chunk" ? "청킹" : "임베딩"} 작업</Pill>
        </div>
      </div>
    </div>
  );
}

function labelForStep(kind, step) {
  const map = kind === "chunk"
    ? { upload: "업로드", parse: "구조 분석", extract: "텍스트 추출", ocr: "OCR", chunk: "청킹", finalize: "마무리", done: "완료" }
    : { prepare: "준비", embed: "벡터 생성", store: "DB 저장", done: "완료" };
  return map[step] || step;
}

// ============================================================
// Phase: 청킹 완료 → 컬렉션 입력 + 임베딩
// ============================================================
function ChunkedPhase({ docName, result, collectionName, setCollectionName, touched, setTouched, onPreview, onEmbed, onReset, error }) {
  const valid = isValidCollection(collectionName);
  const showErr = touched && !valid && collectionName.length > 0;

  return (
    <div className="phase anim-in">
      <div className="phase-hero">
        <div className="success-mark">
          <Icon.Check w={18} h={18} />
          <span>청킹 완료</span>
        </div>
        <h1 className="phase-title">{docName} 이(가) {result?.chunk_count ?? "—"}개 청크로 정리됐어요</h1>
        <p className="phase-sub">이제 ChromaDB에 저장할 컬렉션 이름을 정해주세요.</p>
      </div>

      <div className="result-stats">
        <Stat label="청크 수" value={result?.chunk_count ?? "—"} icon={<Icon.Hash w={16} h={16} />} />
        <Stat label="페이지" value={result?.page_count ?? "—"} icon={<Icon.BookOpen w={16} h={16} />} />
        <Stat label="문서" value={result?.doc_name || docName} icon={<Icon.FileText w={16} h={16} />} mono />
      </div>

      <div className="phase-actions phase-actions-center">
        <Button variant="secondary" onClick={onPreview} iconLeft={<Icon.Eye w={16} h={16} />}>
          청킹 결과 보기
        </Button>
      </div>

      <div className="card phase-card">
        <div className="field-label">
          <Icon.Database w={14} h={14} />
          <span>ChromaDB 컬렉션 이름</span>
        </div>
        <input
          className="input"
          placeholder="예: spring-docs-v1"
          value={collectionName}
          onChange={(e) => setCollectionName(e.target.value)}
          onBlur={() => setTouched(true)}
        />
        <div className="field-hint">
          {showErr ? (
            <span className="hint-error">
              <Icon.AlertCircle w={12} h={12} />
              영문 소문자·숫자·하이픈·언더스코어, 3~63자
            </span>
          ) : (
            <span className="hint-ok">
              <Icon.Info w={12} h={12} />
              영문 소문자·숫자·하이픈·언더스코어를 사용하세요 (3~63자)
            </span>
          )}
        </div>

        {error && (
          <div className="error-banner">
            <Icon.AlertCircle w={16} h={16} />
            <span>{error}</span>
          </div>
        )}

        <div className="phase-actions">
          <Button variant="ghost" onClick={onReset} iconLeft={<Icon.RefreshCw w={16} h={16} />}>
            처음부터
          </Button>
          <Button
            variant="primary"
            size="lg"
            disabled={!valid}
            onClick={onEmbed}
            iconRight={<Icon.ArrowRight w={18} h={18} />}
          >
            임베딩하기
          </Button>
        </div>
      </div>
    </div>
  );
}

function isValidCollection(s) {
  if (!s) return false;
  return /^[a-z0-9][a-z0-9_-]{1,61}[a-z0-9]$/.test(s);
}

function Stat({ label, value, icon, mono }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{icon}<span>{label}</span></div>
      <div className={"stat-value" + (mono ? " mono-id" : "")}>{value}</div>
    </div>
  );
}

// ============================================================
// Phase: 임베딩 완료 → 채팅으로
// ============================================================
function EmbeddedPhase({ result, docName, collectionName, onChat, onReset }) {
  return (
    <div className="phase anim-in">
      <div className="phase-hero">
        <div className="success-mark success-mark-lg">
          <Icon.CheckCircle w={22} h={22} />
          <span>모든 작업 완료</span>
        </div>
        <h1 className="phase-title">"{result?.collection_name || collectionName}" 컬렉션이 준비됐어요</h1>
        <p className="phase-sub">이제 챗봇에게 이 문서에 대해 물어볼 수 있어요.</p>
      </div>

      <div className="result-stats">
        <Stat label="저장된 벡터" value={result?.vector_count ?? "—"} icon={<Icon.Sparkles w={16} h={16} />} />
        <Stat label="컬렉션" value={result?.collection_name || collectionName} icon={<Icon.Database w={16} h={16} />} mono />
        <Stat label="원본 문서" value={docName || "—"} icon={<Icon.FileText w={16} h={16} />} mono />
      </div>

      <div className="phase-actions phase-actions-center">
        <Button variant="ghost" onClick={onReset} iconLeft={<Icon.Plus w={16} h={16} />}>
          새 문서 청킹
        </Button>
        <Button variant="primary" size="lg" onClick={onChat} iconRight={<Icon.ArrowRight w={18} h={18} />}>
          채팅으로 가서 물어보기
        </Button>
      </div>
    </div>
  );
}

window.ChunkingPage = ChunkingPage;
