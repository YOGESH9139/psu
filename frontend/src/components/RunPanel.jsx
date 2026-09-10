import { useEffect, useRef, useState } from "react";
import { formatDuration } from "../api";
import { Check, ChevronRight, Sparkle, X, toolIcon } from "../icons";

const TASK_LABEL = {
  "multimodal-document": "Scanned document",
  "spreadsheet-analysis": "Spreadsheet analysis",
  coding: "Code task",
  "general-reasoning": "General question",
};

/** Compact, readable view of what a tool actually returned. */
function StepResult({ step }) {
  const result = step.result || {};
  const rows = Object.entries(result).filter(
    ([key, value]) =>
      !["status", "matched_rows", "citations", "results", "sample_rows",
        "column_statistics", "isolation", "stdout", "stderr"].includes(key) &&
      value !== null && value !== "" &&
      (typeof value !== "object" || Array.isArray(value))
  );

  return (
    <div className="step-expand">
      {rows.length > 0 && (
        <dl className="step-kv">
          {rows.slice(0, 8).map(([key, value]) => (
            <div key={key}>
              <dt>{key.replace(/_/g, " ")}</dt>
              <dd>{Array.isArray(value) ? value.join(", ").slice(0, 120) : String(value).slice(0, 160)}</dd>
            </div>
          ))}
        </dl>
      )}
      {(result.stdout || result.stderr) && (
        <pre className="step-console">{(result.stdout || "") + (result.stderr || "")}</pre>
      )}
      {result.isolation && (
        <div className="step-isolation">
          ran in the sandbox · network {result.isolation.network_mode} ·
          {" "}{result.isolation.mem_limit} · {result.isolation.timeout_seconds}s limit
        </div>
      )}
      {step.hash && <div className="step-hash">result hash {step.hash}</div>}
    </div>
  );
}

function Step({ step }) {
  const [open, setOpen] = useState(false);
  const Icon = step.kind === "tool" ? toolIcon(step.tool) : Sparkle;
  const expandable = step.kind === "tool" && step.result;

  return (
    <div className={`step${open ? " is-open" : ""}`}>
      <div className={`step-icon ${step.state}`}>
        {step.state === "active" ? (
          <span className="spinner" />
        ) : step.state === "fail" ? (
          <X />
        ) : step.kind === "tool" ? (
          <Icon />
        ) : (
          <Check />
        )}
      </div>
      <div className="step-body">
        <button
          type="button"
          className={`step-title${expandable ? " is-clickable" : ""}`}
          onClick={() => expandable && setOpen((v) => !v)}
          disabled={!expandable}
        >
          <span className="name">{step.label}</span>
          {step.durationMs != null && (
            <span className="time">{formatDuration(step.durationMs)}</span>
          )}
          {expandable && <ChevronRight className={`chev${open ? " open" : ""}`} />}
        </button>
        {step.detail && <div className="step-detail">{step.detail}</div>}
        {open && <StepResult step={step} />}
      </div>
    </div>
  );
}

function Elapsed({ run }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (run.status !== "running" && run.status !== "awaiting") return;
    const timer = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(timer);
  }, [run.status]);

  if (!run.startedAt) return null;
  const end = run.finishedAt ?? now;
  return <span className="run-elapsed">{((end - run.startedAt) / 1000).toFixed(1)}s</span>;
}

export default function RunPanel({ run, onClose }) {
  const stepsRef = useRef(null);

  useEffect(() => {
    const el = stepsRef.current;
    if (el && (run.status === "running" || run.status === "awaiting")) {
      el.scrollTop = el.scrollHeight;
    }
  }, [run.steps.length, run.status]);

  const router = run.router;
  const percent = Math.round((router?.confidence ?? 0) * 100);
  const done = run.steps.filter((s) => s.state === "done").length;
  const running = run.status === "running" || run.status === "awaiting";

  return (
    <aside className="run-panel">
      <header className="run-panel-head">
        <div className="run-panel-title">
          <span className={`run-beacon${running ? " is-live" : ""}`} />
          <div>
            <div className="rp-h">
              {running ? "Working" : run.status === "failed" ? "Stopped" : "Finished"}
            </div>
            <div className="rp-sub">
              {done} of {run.steps.length} steps
              {" · "}
              <Elapsed run={run} />
            </div>
          </div>
        </div>
        <button type="button" className="icon-btn" onClick={onClose} title="Hide panel">
          <X />
        </button>
      </header>

      {router && (
        <section className="rp-route">
          <div className="rp-label">Routed automatically</div>
          <div className="rp-route-main">
            <span className="rp-task">{TASK_LABEL[router.task_class] || router.task_class}</span>
            <span className={`pill ${router.fallback ? "warn" : "accent"}`}>{percent}%</span>
          </div>
          <div className="rp-model">{router.model_id}</div>
          <div className="confidence-bar">
            <span className="confidence-fill" style={{ width: `${percent}%` }} />
          </div>
          <div className="signals">
            {(router.matched_signals || []).slice(0, 4).map((signal) => (
              <span className="signal" key={signal}>{signal}</span>
            ))}
          </div>
        </section>
      )}

      <div className="rp-steps" ref={stepsRef}>
        <div className="rp-label rp-steps-label">Activity</div>
        {run.steps.map((step) => <Step key={step.key} step={step} />)}
        {run.notices.map((notice, index) => (
          <div className="rp-notice" key={index}>
            <strong>Retrying once.</strong> {notice.text}
          </div>
        ))}
        {run.error && <div className="rp-error">{run.error}</div>}
      </div>
    </aside>
  );
}
