import { useEffect, useRef, useState } from "react";
import { formatBytes } from "../api";
import { FileText, Paperclip, Send, X } from "../icons";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.xlsx,.xls,.csv,.py,.txt,.docx";

export default function Composer({ onSubmit, busy, draft, onDraftChange }) {
  const goal = draft;
  const setGoal = onDraftChange;
  const [file, setFile] = useState(null);
  const [dropping, setDropping] = useState(false);
  const textareaRef = useRef(null);
  const fileRef = useRef(null);

  // Grow with the content, up to the CSS max-height.
  //
  // Two things bite here. Measuring at `height: auto` makes a textarea report
  // its container's height rather than its text's, so collapse to 0 first. And
  // on the very first paint the stylesheet may not have applied yet, so the
  // measurement lands before min/max-height exist — deferring one frame lets
  // layout settle. When the box is empty there is nothing to measure at all:
  // drop the inline height and let the CSS min-height define the resting size.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;

    if (!goal) {
      el.style.height = "";
      return;
    }

    const frame = requestAnimationFrame(() => {
      el.style.height = "0px";
      el.style.height = `${el.scrollHeight}px`;
    });
    return () => cancelAnimationFrame(frame);
  }, [goal]);

  function submit() {
    const trimmed = goal.trim();
    if (!trimmed || busy) return;
    onSubmit(trimmed, file);
    setGoal("");
    setFile(null);
  }

  function onKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  function onDrop(event) {
    event.preventDefault();
    setDropping(false);
    const dropped = event.dataTransfer?.files?.[0];
    if (dropped) setFile(dropped);
  }

  return (
    <div className="composer-wrap">
      <div
        className={`composer${dropping ? " is-drop" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDropping(true);
        }}
        onDragLeave={() => setDropping(false)}
        onDrop={onDrop}
      >
        <textarea
          ref={textareaRef}
          rows={1}
          value={goal}
          placeholder="Ask about a report, a spreadsheet, or some code…"
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={busy}
        />

        <div className="composer-foot">
          <button
            type="button"
            className="icon-btn"
            title="Attach a file"
            onClick={() => fileRef.current?.click()}
            disabled={busy}
          >
            <Paperclip />
          </button>
          <input
            ref={fileRef}
            type="file"
            hidden
            accept={ACCEPT}
            onChange={(e) => {
              setFile(e.target.files?.[0] || null);
              e.target.value = "";
            }}
          />

          {file && (
            <span className="file-chip" title={file.name}>
              <FileText style={{ width: 12, height: 12, opacity: 0.6, flex: "none" }} />
              <span className="fname">{file.name}</span>
              <span className="fsize">{formatBytes(file.size)}</span>
              <button type="button" onClick={() => setFile(null)} title="Remove">
                <X />
              </button>
            </span>
          )}

          <button
            type="button"
            className="send-btn"
            onClick={submit}
            disabled={busy || !goal.trim()}
            title="Run analysis"
          >
            <Send />
          </button>
        </div>
      </div>

      <div className="composer-hint">
        Enter to run · Shift + Enter for a new line · every step runs locally
      </div>
    </div>
  );
}
