// 실제 API 엔드포인트를 여기서 수정하세요.
// 개발 중에는 USE_MOCK=true로 두면 mock 응답으로 동작합니다.

window.APP_CONFIG = {
  // 백엔드 URL (e.g. "http://localhost:8000")
  API_BASE: "",

  // true이면 실제 fetch 대신 mock 응답 사용
  USE_MOCK: false,

  // 폴링 간격 (ms)
  POLL_INTERVAL_MS: 2000,

  // 엔드포인트
  ENDPOINTS: {
    upload: "/api/upload",                          // POST multipart {file, do_ocr}
    uploadStatus: (jobId) => `/api/upload/status/${jobId}`, // GET
    chunks: (docName) => `/api/chunkings/${encodeURIComponent(docName)}/chunks`,  // GET (청크 목록)
    chunkings: "/api/chunkings",                    // GET 청킹 결과 디렉터리 목록
    embed: "/api/embed",                            // POST {doc_name, collection_name}
    embedStatus: (jobId) => `/api/embed/status/${jobId}`,   // GET
    collections: "/api/collections",                // GET 목록
    deleteCollection: (name) => `/api/collections/${encodeURIComponent(name)}`, // DELETE
    chat: "/api/chat",                              // POST {collection, message, session_id?}
  },
};

// ============================================================
// API 헬퍼 — USE_MOCK=true이면 mockApi, false면 realApi 사용
// 함수 시그니처는 동일하게 유지하세요.
// ============================================================

window.api = {
  async uploadPdf(file, doOcr, strategy = "docling_hybrid") {
    if (window.APP_CONFIG.USE_MOCK) return window.mockApi.uploadPdf(file, doOcr, strategy);
    const form = new FormData();
    form.append("file", file);
    form.append("do_ocr", String(doOcr));
    form.append("strategy", strategy);
    const res = await fetch(window.APP_CONFIG.API_BASE + window.APP_CONFIG.ENDPOINTS.upload, {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
    return res.json(); // { job_id, doc_name, saved_path }
  },

  async getUploadStatus(jobId) {
    if (window.APP_CONFIG.USE_MOCK) return window.mockApi.getUploadStatus(jobId);
    const res = await fetch(window.APP_CONFIG.API_BASE + window.APP_CONFIG.ENDPOINTS.uploadStatus(jobId));
    if (!res.ok) throw new Error(`Status failed: ${res.status}`);
    return res.json(); // { status, progress, step, message, result?, error? }
  },

  async getChunks(docName) {
    if (window.APP_CONFIG.USE_MOCK) return window.mockApi.getChunks(docName);
    const res = await fetch(window.APP_CONFIG.API_BASE + window.APP_CONFIG.ENDPOINTS.chunks(docName));
    if (!res.ok) throw new Error(`Chunks failed: ${res.status}`);
    return res.json();
  },

  async listChunkings() {
    if (window.APP_CONFIG.USE_MOCK) return { chunkings: [] };
    const res = await fetch(window.APP_CONFIG.API_BASE + window.APP_CONFIG.ENDPOINTS.chunkings);
    if (!res.ok) throw new Error(`Chunkings failed: ${res.status}`);
    return res.json(); // { chunkings: [{ doc_name, source_pdf, chunk_count, picture_count, table_count, created_at }] }
  },

  async startEmbedding(docName, collectionName) {
    if (window.APP_CONFIG.USE_MOCK) return window.mockApi.startEmbedding(docName, collectionName);
    const res = await fetch(window.APP_CONFIG.API_BASE + window.APP_CONFIG.ENDPOINTS.embed, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_name: docName, collection_name: collectionName }),
    });
    if (!res.ok) throw new Error(`Embed failed: ${res.status}`);
    return res.json(); // { embed_job_id }
  },

  async deleteCollection(name) {
    if (window.APP_CONFIG.USE_MOCK) return true;
    const res = await fetch(window.APP_CONFIG.API_BASE + window.APP_CONFIG.ENDPOINTS.deleteCollection(name), {
      method: "DELETE",
    });
    if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
    return true;
  },

  async getEmbedStatus(embedJobId) {
    if (window.APP_CONFIG.USE_MOCK) return window.mockApi.getEmbedStatus(embedJobId);
    const res = await fetch(window.APP_CONFIG.API_BASE + window.APP_CONFIG.ENDPOINTS.embedStatus(embedJobId));
    if (!res.ok) throw new Error(`Embed status failed: ${res.status}`);
    return res.json();
  },

  async listCollections() {
    if (window.APP_CONFIG.USE_MOCK) return window.mockApi.listCollections();
    const res = await fetch(window.APP_CONFIG.API_BASE + window.APP_CONFIG.ENDPOINTS.collections);
    if (!res.ok) throw new Error(`Collections failed: ${res.status}`);
    return res.json();
  },

  async sendChat(collection, message, sessionId) {
    if (window.APP_CONFIG.USE_MOCK) return window.mockApi.sendChat(collection, message, sessionId);
    const res = await fetch(window.APP_CONFIG.API_BASE + window.APP_CONFIG.ENDPOINTS.chat, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ collection, message, session_id: sessionId }),
    });
    if (!res.ok) throw new Error(`Chat failed: ${res.status}`);
    return res.json();
  },

  async listSessions() {
    if (window.APP_CONFIG.USE_MOCK) return window.mockApi.listSessions();
    const res = await fetch(window.APP_CONFIG.API_BASE + window.APP_CONFIG.ENDPOINTS.sessions);
    if (!res.ok) throw new Error(`Sessions failed: ${res.status}`);
    return res.json();
  },
};

// ============================================================
// Mock API — 백엔드 없이도 동작하도록
// ============================================================
const _mockState = {
  jobs: {},      // jobId -> { startedAt, doOcr, docName, progress, step, status }
  embeds: {},    // embedJobId -> { startedAt, collection, jobId, progress, step, status }
  chunks: null,
  collections: [
    { name: "spring-docs-v1", count: 142, created_at: "2025-05-08" },
    { name: "company-handbook", count: 88, created_at: "2025-05-10" },
  ],
  sessions: [
    { id: "s_001", title: "스프링 인터셉터 흐름", collection: "spring-docs-v1", updated_at: "2025-05-14 14:22", preview: "인터셉터 호출 순서가 어떻게 되나요?" },
    { id: "s_002", title: "DI 컨테이너 동작 원리", collection: "spring-docs-v1", updated_at: "2025-05-13 18:40", preview: "ApplicationContext와 BeanFactory의 차이..." },
    { id: "s_003", title: "휴가 정책 확인", collection: "company-handbook", updated_at: "2025-05-12 09:15", preview: "연차는 며칠인가요?" },
  ],
};

window.mockApi = {
  async uploadPdf(file, doOcr, strategy = "docling_hybrid") {
    await _delay(400);
    const jobId = "job_" + Math.random().toString(36).slice(2, 10);
    _mockState.jobs[jobId] = {
      startedAt: Date.now(),
      doOcr,
      strategy,
      docName: file?.name || "document.pdf",
    };
    return {
      job_id: jobId,
      doc_name: file?.name || "document.pdf",
      saved_path: `/uploads/${jobId}/${file?.name || "document.pdf"}`,
    };
  },

  async getUploadStatus(jobId) {
    await _delay(120);
    const job = _mockState.jobs[jobId];
    if (!job) return { status: "failed", progress: 0, step: "error", message: "Unknown job", error: "Job not found" };
    const elapsed = Date.now() - job.startedAt;
    // 약 12초에 걸쳐 진행
    const total = job.doOcr ? 16000 : 10000;
    const progress = Math.min(100, Math.floor((elapsed / total) * 100));
    let step = "parse";
    let message = "PDF 파싱 중";
    if (progress < 15) { step = "upload"; message = "파일 업로드 완료"; }
    else if (progress < 35) { step = "parse"; message = "PDF 구조 분석 중"; }
    else if (progress < 60) { step = job.doOcr ? "ocr" : "extract"; message = job.doOcr ? "OCR 처리 중 (이미지 텍스트 추출)" : "텍스트 추출 중"; }
    else if (progress < 90) { step = "chunk"; message = "의미 단위로 청킹 중"; }
    else { step = "finalize"; message = "결과 정리 중"; }
    if (progress >= 100) {
      return {
        status: "completed",
        progress: 100,
        step: "done",
        message: "청킹 완료",
        result: { chunk_count: 32, page_count: 48, doc_name: job.docName },
      };
    }
    return { status: "running", progress, step, message };
  },

  async getChunks(jobId) {
    await _delay(300);
    return { chunks: _sampleChunks(jobId) };
  },

  async startEmbedding(jobId, collectionName) {
    await _delay(300);
    const embedJobId = "emb_" + Math.random().toString(36).slice(2, 10);
    _mockState.embeds[embedJobId] = {
      startedAt: Date.now(),
      collection: collectionName,
      jobId,
    };
    return { embed_job_id: embedJobId, collection_name: collectionName };
  },

  async getEmbedStatus(embedJobId) {
    await _delay(120);
    const job = _mockState.embeds[embedJobId];
    if (!job) return { status: "failed", progress: 0, step: "error", message: "Unknown embed job", error: "Job not found" };
    const elapsed = Date.now() - job.startedAt;
    const total = 8000;
    const progress = Math.min(100, Math.floor((elapsed / total) * 100));
    let step = "embed";
    let message = "임베딩 생성 중";
    if (progress < 20) { step = "prepare"; message = "청크 로드 중"; }
    else if (progress < 80) { step = "embed"; message = `임베딩 벡터 생성 중 (${Math.floor(progress * 0.32)}/32 청크)`; }
    else { step = "store"; message = "ChromaDB에 저장 중"; }
    if (progress >= 100) {
      // collection 추가
      if (!_mockState.collections.find((c) => c.name === job.collection)) {
        _mockState.collections.unshift({ name: job.collection, count: 32, created_at: new Date().toISOString().slice(0, 10) });
      }
      return {
        status: "completed",
        progress: 100,
        step: "done",
        message: "임베딩 완료 — ChromaDB에 저장됨",
        result: { collection_name: job.collection, vector_count: 32 },
      };
    }
    return { status: "running", progress, step, message };
  },

  async listCollections() {
    await _delay(120);
    return { collections: _mockState.collections };
  },

  async listSessions() {
    await _delay(120);
    return { sessions: _mockState.sessions };
  },

  async sendChat(collection, message, sessionId) {
    await _delay(700);
    const responses = [
      "스프링 인터셉터는 컨트롤러 호출 전후로 동작하는 컴포넌트입니다. preHandle → handler 실행 → postHandle → afterCompletion 순서로 호출됩니다.",
      "ApplicationContext는 BeanFactory를 확장한 인터페이스로, 메시지 소스, 이벤트 발행, 환경 추상화 등 엔터프라이즈 기능을 추가로 제공합니다.",
      "주어진 문서를 기반으로 정확히 답변드리기 어려운 부분이 있습니다. 좀 더 구체적인 질문을 주시면 관련 청크를 찾아드릴 수 있어요.",
    ];
    return {
      answer: responses[Math.floor(Math.random() * responses.length)],
      sources: [
        { chunk_id: "7. _______ ____2#00032", page_start: 11, page_end: 12, heading: "스프링 인터셉터 호출 흐름", score: 0.92 },
        { chunk_id: "7. _______ ____2#00033", page_start: 12, page_end: 13, heading: "인터셉터 등록 방법", score: 0.81 },
      ],
      session_id: sessionId || "s_" + Math.random().toString(36).slice(2, 8),
    };
  },
};

function _delay(ms) { return new Promise((r) => setTimeout(r, ms)); }

function _sampleChunks(jobId) {
  return [
    {
      chunk_id: "7. _______ ____2 - ______ __________#00032",
      contextualized_text: "* 스프링 인터셉터 호출 흐름\nFlow chart 이 다이어그램은 Spring MVC 프레임워크에서 클라이언트의 요청이 처리되는 전체 흐름을 보여줍니다. DispatcherServlet이 요청을 받으면 HandlerMapping을 통해 적절한 핸들러를 찾고, 등록된 인터셉터들의 preHandle 메서드가 차례로 호출됩니다. 모든 preHandle이 true를 반환하면 실제 핸들러(컨트롤러)가 실행되고, 이후 postHandle, afterCompletion 순서로 후처리가 진행됩니다.",
      headings: ["* 스프링 인터셉터 호출 흐름"],
      page_nos: [11, 12],
      page_start: 11,
      page_end: 12,
      doc_item_refs: ["#/texts/160", "#/pictures/0"],
      picture_refs: ["#/pictures/0"],
      table_refs: [],
    },
    {
      chunk_id: "7. _______ ____2 - ______ __________#00033",
      contextualized_text: "* 인터셉터 등록 방법\n@Configuration 클래스에서 WebMvcConfigurer를 구현하고 addInterceptors 메서드를 오버라이드합니다. registry.addInterceptor(new MyInterceptor()).addPathPatterns(\"/api/**\").excludePathPatterns(\"/api/public/**\") 형태로 경로별 적용 범위를 지정할 수 있습니다.",
      headings: ["* 인터셉터 등록 방법"],
      page_nos: [12, 13],
      page_start: 12,
      page_end: 13,
      doc_item_refs: ["#/texts/172"],
      picture_refs: [],
      table_refs: [],
    },
    {
      chunk_id: "7. _______ ____2 - ______ __________#00034",
      contextualized_text: "* DI 컨테이너의 동작 원리\nApplicationContext는 빈 정의를 읽어들이고, 의존성 그래프를 구성한 뒤 적절한 순서로 빈을 생성합니다. 생성된 빈은 싱글톤 스코프인 경우 컨테이너 내부에 캐싱되어 재사용됩니다. @Autowired 어노테이션이 붙은 필드/생성자는 타입 매칭을 통해 자동으로 의존성이 주입됩니다.",
      headings: ["* DI 컨테이너의 동작 원리"],
      page_nos: [14],
      page_start: 14,
      page_end: 14,
      doc_item_refs: ["#/texts/180", "#/tables/3"],
      picture_refs: [],
      table_refs: ["#/tables/3"],
    },
    {
      chunk_id: "7. _______ ____2 - ______ __________#00035",
      contextualized_text: "* AOP의 핵심 개념\nAspect-Oriented Programming은 횡단 관심사(cross-cutting concerns)를 모듈화하기 위한 패러다임입니다. 로깅, 트랜잭션, 보안 같은 공통 기능을 비즈니스 로직과 분리하여 관리할 수 있게 해줍니다. Spring AOP는 프록시 기반으로 동작하며, JDK 다이나믹 프록시 또는 CGLIB을 사용합니다.",
      headings: ["* AOP의 핵심 개념"],
      page_nos: [16, 17, 18],
      page_start: 16,
      page_end: 18,
      doc_item_refs: ["#/texts/195"],
      picture_refs: ["#/pictures/2"],
      table_refs: [],
    },
    {
      chunk_id: "7. _______ ____2 - ______ __________#00036",
      contextualized_text: "* 트랜잭션 전파 옵션\n@Transactional의 propagation 속성은 트랜잭션 경계를 어떻게 처리할지 결정합니다. REQUIRED는 기본값으로 기존 트랜잭션에 참여하거나 새로 시작하고, REQUIRES_NEW는 항상 새로운 트랜잭션을 시작합니다. NESTED는 중첩 트랜잭션을, SUPPORTS는 트랜잭션이 있으면 참여하고 없으면 그대로 진행합니다.",
      headings: ["* 트랜잭션 전파 옵션"],
      page_nos: [22, 23],
      page_start: 22,
      page_end: 23,
      doc_item_refs: ["#/texts/210", "#/tables/5"],
      picture_refs: [],
      table_refs: ["#/tables/5"],
    },
  ];
}
