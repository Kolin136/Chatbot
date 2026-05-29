// 청크 결과 보기 모달 — JSON을 예쁘게 표시

function ChunkViewer({ chunks }) {
  const [expandedId, setExpandedId] = useState(chunks[0]?.chunk_id || null);
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    if (!query.trim()) return chunks;
    const q = query.toLowerCase();
    return chunks.filter(
      (c) =>
        c.contextualized_text.toLowerCase().includes(q) ||
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
                    {c.contextualized_text.slice(0, 110)}…
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
                    <div className="chunk-section-label">컨텍스트화된 텍스트</div>
                    <div className="chunk-text">
                      {c.contextualized_text.split("\n").map((line, i) => (
                        <p key={i}>{line}</p>
                      ))}
                    </div>
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
