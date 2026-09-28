// 청크 결과 보기 모달 — JSON을 예쁘게 표시

function ChunkViewer({ chunks, onSave, onEditingChange }) {
  const [expandedId, setExpandedId] = useState(chunks[0]?.chunk_id || null);
  const [query, setQuery] = useState("");
  // 편집은 한 번에 하나만 (expandedId와 동일한 단일 값 방식)
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);

  // 편집 중 여부를 부모에 알림 → 모달 실수 닫힘 방지
  useEffect(() => {
    if (onEditingChange) onEditingChange(editingId !== null);
  }, [editingId, onEditingChange]);

  const startEdit = (c) => {
    setEditingId(c.chunk_id);
    setDraft(c.contextualized_text || "");
    setSaveError(null);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setDraft("");
    setSaveError(null);
  };

  const commitEdit = async (chunkId) => {
    if (!draft.trim()) {
      setSaveError("내용이 비어있습니다. 빈 청크는 임베딩할 수 없어요.");
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await onSave(chunkId, draft);
      setEditingId(null);
      setDraft("");
    } catch (e) {
      setSaveError(e.message || "저장에 실패했어요.");
    } finally {
      setSaving(false);
    }
  };

  const filtered = useMemo(() => {
    if (!query.trim()) return chunks;
    const q = query.toLowerCase();
    return chunks.filter(
      (c) =>
        (c.contextualized_text || "").toLowerCase().includes(q) ||
        (c.headings || []).some((h) => h.toLowerCase().includes(q))
    );
  }, [chunks, query]);

  return (
    <div className="chunk-viewer">
      <div className="chunk-viewer-toolbar">
        <div className="chunk-viewer-search">
          <Icon.Search w={16} h={16} />
          <input
            placeholder="청크 내용·헤딩 검색"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="chunk-viewer-count">
          <Pill tone="muted" icon={<Icon.Hash w={12} h={12} />}>총 {chunks.length}개</Pill>
        </div>
      </div>

      <div className="chunk-list">
        {filtered.map((c, idx) => {
          const expanded = expandedId === c.chunk_id;
          const shortId = c.chunk_id.split("#").pop();
          const heading = (c.headings || [])[0]?.replace(/^\*\s*/, "") || "(제목 없음)";
          return (
            <div key={c.chunk_id} className="chunk-card" data-expanded={expanded}>
              <button
                className="chunk-card-head"
                onClick={() => setExpandedId(expanded ? null : c.chunk_id)}
              >
                <div className="chunk-card-num">#{shortId}</div>
                <div className="chunk-card-title-wrap">
                  <div className="chunk-card-title">{heading}</div>
                  <div className="chunk-card-preview">
                    {(c.contextualized_text || "").slice(0, 110)}…
                  </div>
                </div>
                <div className="chunk-card-meta">
                  <Pill tone="info" icon={<Icon.BookOpen w={11} h={11} />}>
                    p. {c.page_start === c.page_end ? c.page_start : `${c.page_start}–${c.page_end}`}
                  </Pill>
                  <Icon.ChevronDown w={18} h={18} style={{ transition: "transform 0.2s", transform: expanded ? "rotate(180deg)" : "none", color: "var(--text-tertiary)" }} />
                </div>
              </button>

              {expanded && (
                <div className="chunk-card-body anim-in">
                  <div className="chunk-section">
                    <div className="chunk-section-head">
                      <div className="chunk-section-label">컨텍스트화된 텍스트</div>
                      {onSave && editingId !== c.chunk_id && (
                        <button
                          type="button"
                          className="chunk-edit-btn"
                          onClick={() => startEdit(c)}
                        >
                          <Icon.Pencil w={13} h={13} />
                          수정
                        </button>
                      )}
                    </div>

                    {editingId === c.chunk_id ? (
                      <div className="chunk-edit-wrap">
                        <textarea
                          className="chunk-edit-area"
                          value={draft}
                          onChange={(e) => setDraft(e.target.value)}
                          disabled={saving}
                          autoFocus
                          spellCheck={false}
                        />
                        <div className="chunk-edit-hint">
                          이 텍스트가 그대로 임베딩되고 답변 근거로 쓰입니다. 저장하면 chunks.jsonl에 반영돼요.
                        </div>
                        {saveError && (
                          <div className="chunk-edit-error">
                            <Icon.AlertCircle w={14} h={14} />
                            <span>{saveError}</span>
                          </div>
                        )}
                        <div className="chunk-edit-actions">
                          <button
                            type="button"
                            className="chunk-edit-cancel"
                            onClick={cancelEdit}
                            disabled={saving}
                          >
                            취소
                          </button>
                          <button
                            type="button"
                            className="chunk-edit-save"
                            onClick={() => commitEdit(c.chunk_id)}
                            disabled={saving || !draft.trim()}
                          >
                            {saving ? "저장 중…" : "저장"}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="chunk-text">
                        {(c.contextualized_text || "").split("\n").map((line, i) => (
                          <p key={i}>{line}</p>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="chunk-meta-grid">
                    <MetaItem icon={<Icon.BookOpen w={14} h={14} />} label="페이지">
                      <code>{(c.page_nos || []).join(", ")}</code>
                    </MetaItem>
                    <MetaItem icon={<Icon.Hash w={14} h={14} />} label="청크 ID">
                      <code className="mono-id">{c.chunk_id}</code>
                    </MetaItem>
                    {(c.headings || []).length > 0 && (
                      <MetaItem icon={<Icon.Layers w={14} h={14} />} label="헤딩">
                        {c.headings.map((h, i) => (
                          <span key={i} className="chunk-heading-pill">{h.replace(/^\*\s*/, "")}</span>
                        ))}
                      </MetaItem>
                    )}
                    {(c.doc_item_refs || []).length > 0 && (
                      <MetaItem icon={<Icon.FileText w={14} h={14} />} label={`참조 (${c.doc_item_refs.length})`}>
                        <div className="ref-chip-row">
                          {c.doc_item_refs.map((r, i) => (
                            <span key={i} className="ref-chip mono-id">{r}</span>
                          ))}
                        </div>
                      </MetaItem>
                    )}
                    {(c.picture_refs || []).length > 0 && (
                      <MetaItem icon={<Icon.Image w={14} h={14} />} label={`이미지 (${c.picture_refs.length})`}>
                        <div className="ref-chip-row">
                          {c.picture_refs.map((r, i) => (
                            <span key={i} className="ref-chip mono-id">{r}</span>
                          ))}
                        </div>
                      </MetaItem>
                    )}
                    {(c.table_refs || []).length > 0 && (
                      <MetaItem icon={<Icon.Grid w={14} h={14} />} label={`표 (${c.table_refs.length})`}>
                        <div className="ref-chip-row">
                          {c.table_refs.map((r, i) => (
                            <span key={i} className="ref-chip mono-id">{r}</span>
                          ))}
                        </div>
                      </MetaItem>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
        {filtered.length === 0 && (
          <div className="chunk-empty">
            <Icon.Search w={28} h={28} />
            <div>"{query}" 와(과) 일치하는 청크가 없어요</div>
          </div>
        )}
      </div>
    </div>
  );
}

function MetaItem({ icon, label, children }) {
  return (
    <div className="chunk-meta-item">
      <div className="chunk-meta-label">
        {icon}
        <span>{label}</span>
      </div>
      <div className="chunk-meta-value">{children}</div>
    </div>
  );
}

window.ChunkViewer = ChunkViewer;
