// 메인 앱 — 라우팅 + Tweaks 패널

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "mint"
}/*EDITMODE-END*/;

function App() {
  const [page, setPage] = useState("chunking");
  const [collectionForChat, setCollectionForChat] = useState(null);
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);

  // 테마를 body의 data-theme 속성으로 반영
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", t.theme || "coral");
  }, [t.theme]);

  const goChat = (collection) => {
    setCollectionForChat(collection);
    setPage("chat");
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">
            <Icon.Layers w={20} h={20} />
          </div>
          <div>
            <div>청킹페이지</div>
            <div className="brand-sub">PDF → Chunk → Chroma → Chat</div>
          </div>
        </div>

        <nav className="nav-tabs">
          <button
            className="nav-tab"
            data-active={page === "chunking"}
            onClick={() => setPage("chunking")}
          >
            <Icon.Layers w={16} h={16} />
            청킹 & 임베딩
          </button>
          <button
            className="nav-tab"
            data-active={page === "chat"}
            onClick={() => setPage("chat")}
          >
            <Icon.MessageSquare w={16} h={16} />
            챗봇 대화
          </button>
        </nav>

        <div className="topbar-right" />
      </header>

      {page === "chunking" && <ChunkingPage onGoChat={goChat} />}
      {page === "chat" && <ChatPage initialCollection={collectionForChat} />}

      <TweaksPanel title="Tweaks">
        <TweakSection title="비주얼 테마">
          <TweakRadio
            value={t.theme}
            onChange={(v) => setTweak("theme", v)}
            options={[
              { value: "coral", label: "코랄" },
              { value: "mint", label: "민트" },
              { value: "sunset", label: "선셋" },
            ]}
          />
          <ThemePreview value={t.theme} />
        </TweakSection>
        <TweakSection title="개발 메모">
          <div style={{ fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.6 }}>
            현재 <strong style={{ color: "var(--text-primary)" }}>USE_MOCK=true</strong> 로 동작 중이에요.
            실제 백엔드를 연결하려면 <code>config.jsx</code> 에서
            <br /><code>API_BASE</code> 와 <code>USE_MOCK=false</code> 를 설정하세요.
          </div>
        </TweakSection>
      </TweaksPanel>
    </div>
  );
}

function ThemePreview({ value }) {
  const palettes = {
    coral: ["#f06a3b", "#fff7f1", "#2b1d14"],
    mint: ["#14916a", "#f1faf7", "#0f2a23"],
    sunset: ["#e85a7a", "#fff5f3", "#2c1820"],
  };
  const labels = { coral: "따뜻한 산호 + 머스타드", mint: "신선한 틸 + 크림", sunset: "부드러운 핑크 + 피치" };
  const colors = palettes[value] || palettes.coral;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8 }}>
      <div style={{ display: "flex", gap: 4 }}>
        {colors.map((c, i) => (
          <div key={i} style={{ width: 22, height: 22, borderRadius: 7, background: c, border: "1px solid rgba(0,0,0,0.08)" }} />
        ))}
      </div>
      <div style={{ fontSize: 12, color: "var(--text-tertiary)" }}>{labels[value]}</div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
