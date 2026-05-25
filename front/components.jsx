// 공통 UI 컴포넌트

const { useState, useEffect, useRef, useCallback, useMemo } = React;

// ============================================================
// Button
// ============================================================
function Button({ variant = "primary", size = "md", iconLeft, iconRight, children, ...rest }) {
  const cls = ["btn", `btn-${variant}`, size !== "md" ? `btn-${size}` : ""].filter(Boolean).join(" ");
  return (
    <button className={cls} {...rest}>
      {iconLeft}
      {children}
      {iconRight}
    </button>
  );
}

// ============================================================
// Pill
// ============================================================
function Pill({ tone = "muted", children, icon }) {
  return (
    <span className={`pill pill-${tone}`}>
      {icon}
      {children}
    </span>
  );
}

// ============================================================
// Progress bar
// ============================================================
function Progress({ value = 0, label }) {
  return (
    <div className="progress-wrap">
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      </div>
      {label && <div className="progress-label">{label}</div>}
    </div>
  );
}

// ============================================================
// Toggle switch with label/description
// ============================================================
function ToggleField({ on, onChange, title, description }) {
  return (
    <div className="toggle-field">
      <div className="toggle-field-text">
        <div className="toggle-field-title">{title}</div>
        {description && <div className="toggle-field-desc">{description}</div>}
      </div>
      <button
        type="button"
        className="toggle"
        data-on={on ? "true" : "false"}
        onClick={() => onChange(!on)}
        aria-pressed={on}
      />
    </div>
  );
}

// ============================================================
// File dropzone
// ============================================================
function FileDropzone({ file, onFile, accept = ".pdf" }) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef(null);

  const handleFiles = (files) => {
    if (!files || !files.length) return;
    const f = files[0];
    if (f && (!accept || f.name.toLowerCase().endsWith(accept.replace(".", "")))) {
      onFile(f);
    } else if (f) {
      onFile(f);
    }
  };

  return (
    <div
      className="dropzone"
      data-drag={dragOver ? "true" : "false"}
      data-has-file={file ? "true" : "false"}
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files); }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        style={{ display: "none" }}
        onChange={(e) => handleFiles(e.target.files)}
      />
      {file ? (
        <div className="dropzone-file">
          <div className="dropzone-file-icon">
            <Icon.FileText w={28} h={28} />
          </div>
          <div className="dropzone-file-info">
            <div className="dropzone-file-name">{file.name}</div>
            <div className="dropzone-file-meta">
              {formatBytes(file.size)} · PDF
            </div>
          </div>
          <button
            className="btn btn-ghost btn-sm"
            onClick={(e) => { e.stopPropagation(); onFile(null); }}
          >
            <Icon.X w={16} h={16} />
            변경
          </button>
        </div>
      ) : (
        <div className="dropzone-empty">
          <div className="dropzone-icon">
            <Icon.Upload w={26} h={26} />
          </div>
          <div className="dropzone-title">PDF 파일을 끌어다 놓거나 클릭해서 선택</div>
          <div className="dropzone-sub">한 번에 한 개의 PDF만 업로드할 수 있어요</div>
        </div>
      )}
    </div>
  );
}

function formatBytes(b) {
  if (!b) return "—";
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
}

window.formatBytes = formatBytes;

// ============================================================
// Modal
// ============================================================
function Modal({ open, onClose, title, children, width = 920, footer }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") onClose?.(); };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{ maxWidth: width }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">{title}</div>
          <button className="modal-close" onClick={onClose}><Icon.X w={18} h={18} /></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

// ============================================================
// Step indicator for the upload→embed flow
// ============================================================
function StepRail({ current }) {
  const steps = [
    { id: "upload", label: "PDF 업로드" },
    { id: "chunk", label: "청킹" },
    { id: "embed", label: "임베딩" },
    { id: "done", label: "완료" },
  ];
  return (
    <div className="step-rail">
      {steps.map((s, i) => {
        const order = steps.findIndex((x) => x.id === current);
        const state = i < order ? "done" : i === order ? "active" : "future";
        return (
          <React.Fragment key={s.id}>
            <div className="step-rail-item" data-state={state}>
              <div className="step-rail-dot">
                {state === "done" ? <Icon.Check w={14} h={14} /> : <span>{i + 1}</span>}
              </div>
              <div className="step-rail-label">{s.label}</div>
            </div>
            {i < steps.length - 1 && <div className="step-rail-line" data-state={i < order ? "done" : "future"} />}
          </React.Fragment>
        );
      })}
    </div>
  );
}

Object.assign(window, { Button, Pill, Progress, ToggleField, FileDropzone, Modal, StepRail });
