// 채팅 페이지 — 사이드바(세션 목록) + 메인(대화) + 컬렉션 드롭다운

function ChatPage({ initialCollection }) {
  const [collections, setCollections] = useState([]);
  const [collection, setCollection] = useState(initialCollection || null);
  const [collectionMenuOpen, setCollectionMenuOpen] = useState(false);

  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  // 메시지: messages는 활성 세션의 메시지 목록
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef(null);

  // 컬렉션 초기 로드 (세션은 영속화 미구현이라 메모리에서만 누적)
  useEffect(() => {
    (async () => {
      try {
        const c = await window.api.listCollections();
        setCollections(c.collections || []);
        if (!collection && c.collections?.length) {
          setCollection(c.collections[0].name);
        }
      } catch {}
    })();
    // eslint-disable-next-line
  }, []);

  // 사이드바에서 세션 클릭 시 messages 안 덮어씀 (영속화 없음).
  // 사용자가 "새 대화" 클릭하면 newSession() 에서 명시적으로 초기화.

  // 새 세션 시작
  const newSession = () => {
    setActiveSessionId(null);
    setMessages([]);
  };

  // 메시지 전송
  const send = async () => {
    if (!input.trim() || sending || !collection) return;
    const userMsg = {
      id: "m_" + Math.random().toString(36).slice(2, 8),
      role: "user",
      text: input.trim(),
      ts: nowStamp(),
    };
    setMessages((m) => [...m, userMsg]);
    setInput("");
    setSending(true);
    try {
      const res = await window.api.sendChat(collection, userMsg.text, activeSessionId);
      const aiMsg = {
        id: "m_" + Math.random().toString(36).slice(2, 8),
        role: "assistant",
        text: res.answer,
        sources: res.sources || [],
        ts: nowStamp(),
      };
      setMessages((m) => [...m, aiMsg]);

      // 새 세션이면 사이드바에 추가
      if (!activeSessionId && res.session_id) {
        const newSess = {
          id: res.session_id,
          title: userMsg.text.slice(0, 28) + (userMsg.text.length > 28 ? "…" : ""),
          collection,
          updated_at: nowStamp(),
          preview: userMsg.text,
        };
        setSessions((s) => [newSess, ...s]);
        setActiveSessionId(res.session_id);
      } else if (activeSessionId) {
        setSessions((s) =>
          s.map((x) => (x.id === activeSessionId ? { ...x, updated_at: nowStamp(), preview: userMsg.text } : x))
        );
      }
    } catch (e) {
      setMessages((m) => [
        ...m,
        {
          id: "m_err",
          role: "assistant",
          text: "응답을 받지 못했어요. 다시 시도해 주세요.\n" + (e.message || ""),
          isError: true,
          ts: nowStamp(),
        },
      ]);
    } finally {
      setSending(false);
    }
  };

  // 스크롤
  useEffect(() => {
    messagesEndRef.current?.scrollTo({ top: messagesEndRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, sending]);

  const filteredSessions = useMemo(
    () => sessions.filter((s) => !collection || s.collection === collection),
    [sessions, collection]
  );

  return (
    <div className="page page-chat">
      {/* Sidebar */}
      <aside className="chat-sidebar">
        <div className="chat-sidebar-head">
          <Button variant="primary" onClick={newSession} iconLeft={<Icon.Plus w={16} h={16} />} size="md">
            새 대화
          </Button>
        </div>

        <div className="chat-section-label">최근 대화</div>
        <div className="chat-session-list">
          {filteredSessions.length === 0 && (
            <div className="chat-session-empty">
              <Icon.MessageSquare w={20} h={20} />
              <span>아직 대화가 없어요</span>
            </div>
          )}
          {filteredSessions.map((s) => (
            <button
              key={s.id}
              className="chat-session-item"
              data-active={activeSessionId === s.id}
              onClick={() => setActiveSessionId(s.id)}
            >
              <div className="chat-session-title">{s.title}</div>
              <div className="chat-session-preview">{s.preview}</div>
              <div className="chat-session-meta">
                <span className="chat-session-collection mono-id">{s.collection}</span>
                <span className="chat-session-time">{s.updated_at}</span>
              </div>
            </button>
          ))}
        </div>
      </aside>

      {/* Main */}
      <main className="chat-main">
        <header className="chat-header">
          <CollectionDropdown
            value={collection}
            collections={collections}
            open={collectionMenuOpen}
            setOpen={setCollectionMenuOpen}
            onChange={(name) => { setCollection(name); setActiveSessionId(null); setMessages([]); }}
            onDelete={async (c) => {
              const ok = window.confirm(`'${c.name}' 컬렉션을 삭제할까요?\n이 안의 모든 벡터(${c.count}개)가 영구 삭제됩니다.`);
              if (!ok) return;
              try {
                await window.api.deleteCollection(c.name);
                const fresh = await window.api.listCollections();
                const cols = fresh.collections || [];
                setCollections(cols);
                if (collection === c.name) {
                  setCollection(cols.length ? cols[0].name : null);
                  setActiveSessionId(null);
                  setMessages([]);
                }
              } catch (e) {
                alert(`삭제 실패: ${e.message || e}`);
              }
            }}
          />
          <div className="chat-header-meta">
            {collection ? (
              <Pill tone="success" icon={<Icon.CheckCircle w={11} h={11} />}>연결됨</Pill>
            ) : (
              <Pill tone="warning" icon={<Icon.AlertCircle w={11} h={11} />}>컬렉션 선택 필요</Pill>
            )}
          </div>
        </header>

        <div className="chat-body" ref={messagesEndRef}>
          <div className="chat-body-inner">
            {messages.length === 0 ? (
              <ChatEmpty collection={collection} onSuggest={(q) => setInput(q)} />
            ) : (
              messages.map((m) => <ChatMessage key={m.id} message={m} />)
            )}
            {sending && <TypingBubble />}
          </div>
        </div>

        <div className="chat-input-wrap">
          <div className="chat-input-inner">
            <textarea
              className="chat-input"
              placeholder={collection ? "메시지를 입력하고 Enter…" : "먼저 컬렉션을 선택해 주세요"}
              value={input}
              disabled={!collection || sending}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              rows={1}
            />
            <button
              className="chat-send"
              onClick={send}
              disabled={!input.trim() || sending || !collection}
              aria-label="전송"
            >
              <Icon.Send w={18} h={18} />
            </button>
          </div>
          <div className="chat-input-hint">
            Enter로 전송 · Shift+Enter로 줄바꿈 · 답변은 선택한 컬렉션의 청크에서 검색해요
          </div>
        </div>
      </main>
    </div>
  );
}

function nowStamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// ============================================================
// 컬렉션 드롭다운
// ============================================================
function CollectionDropdown({ value, collections, open, setOpen, onChange, onDelete }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open, setOpen]);

  const current = collections.find((c) => c.name === value);

  return (
    <div className="collection-dropdown" ref={ref}>
      <button className="collection-trigger" onClick={() => setOpen(!open)}>
        <div className="collection-trigger-icon">
          <Icon.Database w={16} h={16} />
        </div>
        <div className="collection-trigger-text">
          <div className="collection-trigger-label">현재 컬렉션</div>
          <div className="collection-trigger-name">
            {value || "선택하세요"}
            {current && <span className="collection-trigger-count">{current.count}개 벡터</span>}
          </div>
        </div>
        <Icon.ChevronDown w={16} h={16} style={{ color: "var(--text-tertiary)", transition: "transform 0.2s", transform: open ? "rotate(180deg)" : "none" }} />
      </button>
      {open && (
        <div className="collection-menu anim-in">
          <div className="collection-menu-head">컬렉션 선택</div>
          {collections.length === 0 && (
            <div className="collection-menu-empty">
              아직 임베딩된 컬렉션이 없어요
            </div>
          )}
          {collections.map((c) => (
            <div
              key={c.name}
              className="collection-menu-item"
              data-active={value === c.name}
            >
              <button
                type="button"
                className="collection-menu-item-main"
                onClick={() => { onChange(c.name); setOpen(false); }}
              >
                <Icon.Database w={14} h={14} />
                <div className="collection-menu-item-text">
                  <div className="collection-menu-item-name mono-id">{c.name}</div>
                  <div className="collection-menu-item-meta">{c.count}개 벡터 · {c.created_at}</div>
                </div>
                {value === c.name && <Icon.Check w={14} h={14} />}
              </button>
              {onDelete && (
                <button
                  type="button"
                  className="collection-menu-item-delete"
                  title={`'${c.name}' 컬렉션 삭제`}
                  onClick={(e) => { e.stopPropagation(); onDelete(c); }}
                >
                  <Icon.Trash w={14} h={14} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================
// 메시지 버블
// ============================================================
function ChatMessage({ message }) {
  const isUser = message.role === "user";
  return (
    <div className={"chat-msg " + (isUser ? "chat-msg-user" : "chat-msg-ai")}>
      <div className="chat-msg-avatar">
        {isUser ? <Icon.User w={16} h={16} /> : <Icon.Bot w={16} h={16} />}
      </div>
      <div className="chat-msg-stack">
        <div className={"chat-msg-bubble" + (message.isError ? " chat-msg-bubble-error" : "")}>
          {message.text.split("\n").map((line, i) => (
            <p key={i}>{line}</p>
          ))}
        </div>
        {message.sources && message.sources.length > 0 && (
          <div className="chat-sources">
            <div className="chat-sources-label">
              <Icon.BookOpen w={11} h={11} />
              <span>참고한 청크</span>
            </div>
            <div className="chat-sources-list">
              {message.sources.map((s, i) => (
                <div key={i} className="chat-source-chip">
                  <span className="chat-source-page">p.{s.page_start === s.page_end ? s.page_start : `${s.page_start}–${s.page_end}`}</span>
                  <span className="chat-source-heading">{s.heading}</span>
                  <span className="chat-source-score">{(s.score * 100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          </div>
        )}
        <div className="chat-msg-time">{message.ts}</div>
      </div>
    </div>
  );
}

function TypingBubble() {
  return (
    <div className="chat-msg chat-msg-ai">
      <div className="chat-msg-avatar"><Icon.Bot w={16} h={16} /></div>
      <div className="chat-msg-stack">
        <div className="chat-msg-bubble chat-msg-bubble-typing">
          <span /><span /><span />
        </div>
      </div>
    </div>
  );
}

// ============================================================
// 빈 상태 (대화 시작 전)
// ============================================================
function ChatEmpty({ collection, onSuggest }) {
  const suggestions = [
    "이 문서에서 가장 중요한 개념 3가지를 알려줘",
    "예시 코드가 포함된 부분을 요약해 줘",
    "초보자가 가장 헷갈려 할 만한 부분은?",
  ];
  return (
    <div className="chat-empty">
      <div className="chat-empty-mark">
        <Icon.MessageSquare w={28} h={28} />
      </div>
      <h2 className="chat-empty-title">무엇이든 물어보세요</h2>
      <p className="chat-empty-sub">
        {collection ? (
          <>컬렉션 <span className="mono-id">{collection}</span> 에 저장된 문서에서 답변을 찾아드려요.</>
        ) : (
          <>왼쪽 위에서 ChromaDB 컬렉션을 먼저 선택해 주세요.</>
        )}
      </p>
      {collection && (
        <div className="chat-suggestions">
          {suggestions.map((s, i) => (
            <button key={i} className="chat-suggestion" onClick={() => onSuggest(s)}>
              <Icon.Sparkles w={14} h={14} />
              <span>{s}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

window.ChatPage = ChatPage;
