import { useEffect, useState } from "react";
import { api, formatBytes } from "../api";
import { ChevronRight, Eye, FileText, Sparkle, Table } from "../icons";

function Findings({ findings }) {
  if (!findings?.length) return null;
  return (
    <section className="card">
      <div className="card-head">
        <h4>What the agent found</h4>
        <span className="spacer" />
        <span className="pill">{findings.length}</span>
      </div>
      <div className="card-body">
        {findings.map((finding, index) => {
          const severity = String(finding.severity || "info").toLowerCase();
          return (
            <div className="finding" key={index}>
              <span className={`finding-bar ${severity}`} />
              <div className="finding-main">
                <div className="finding-title">
                  {finding.item}
                  <span className={`pill ${severity === "high" ? "bad" : severity === "medium" ? "warn" : ""}`}>
                    {finding.severity || "Info"}
                  </span>
                </div>
                <div className="finding-detail">{finding.detail}</div>
                {finding.evidence && <div className="finding-evidence">{finding.evidence}</div>}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/** The rows that actually matched. This is the answer, not a paraphrase of it. */
function MatchedRows({ table, dataset }) {
  const [open, setOpen] = useState(true);
  if (!table?.rows?.length) return null;

  const columns = Object.keys(table.rows[0]);
  const filter = table.filter;

  return (
    <section className="card">
      <div className="card-head">
        <Table style={{ width: 14, height: 14, opacity: 0.6 }} />
        <h4>Matching rows</h4>
        <span className="spacer" />
        <span className="pill accent">
          {table.matchCount} of {dataset?.rowCount ?? "?"}
        </span>
        <button type="button" className="mini-btn" onClick={() => setOpen((v) => !v)}>
          {open ? "hide" : "show"}
        </button>
      </div>
      {open && (
        <>
          {filter && (
            <div className="filter-strip">
              <span className="filter-label">filter applied</span>
              <code>{filter.column} {filter.operator} {filter.value}</code>
              <span className="filter-note">computed directly over the file, not by the model</span>
            </div>
          )}
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  {columns.map((column) => (
                    <th key={column} className={filter?.column === column ? "is-filtered" : undefined}>
                      {column.replace(/_/g, " ")}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row, index) => (
                  <tr key={index}>
                    {columns.map((column) => (
                      <td
                        key={column}
                        className={
                          filter?.column === column
                            ? "is-filtered"
                            : typeof row[column] === "number"
                            ? "is-num"
                            : undefined
                        }
                      >
                        {row[column] ?? "—"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function Citations({ citations }) {
  const [expanded, setExpanded] = useState({});
  if (!citations?.length) return null;

  return (
    <section className="card">
      <div className="card-head">
        <h4>Sources it relied on</h4>
        <span className="spacer" />
        <span className="pill ok">{citations.length} cited</span>
      </div>
      <div className="card-body">
        {citations.map((citation, index) => {
          const key = citation.chunk_id || index;
          const full = citation.text || citation.content || citation.excerpt || "";
          const short = citation.excerpt || full;
          const isLong = full.length > short.length + 8;
          const open = expanded[key];
          return (
            <div className="citation" key={key}>
              <div className="citation-src">
                <FileText style={{ width: 11, height: 11 }} />
                {citation.source_file} · page {citation.page_number ?? "?"}
                {citation.score != null && (
                  <span className="score">{Number(citation.score).toFixed(3)}</span>
                )}
              </div>
              <div className="citation-text">{open ? full : short}</div>
              {isLong && (
                <button
                  type="button"
                  className="mini-btn"
                  onClick={() => setExpanded((prev) => ({ ...prev, [key]: !prev[key] }))}
                >
                  {open ? "show less" : "read the full passage"}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Artifacts({ runId, artifacts, onPreview }) {
  const [rows, setRows] = useState([]);

  useEffect(() => {
    if (!runId || !artifacts?.length) return;
    let cancelled = false;
    api.artifacts(runId)
      .then((data) => !cancelled && setRows(data))
      .catch(() => {});
    return () => { cancelled = true; };
  }, [runId, artifacts]);

  if (!artifacts?.length) return null;
  const known = new Map(rows.map((r) => [r.filename, r]));

  return (
    <section className="card">
      <div className="card-head">
        <h4>Deliverable</h4>
        <span className="spacer" />
        <span className="pill">{artifacts.length}</span>
      </div>
      <div className="card-body">
        {artifacts.map((artifact) => {
          const row = known.get(artifact.filename);
          return (
            <div className="artifact" key={artifact.filename}>
              <div className="artifact-icon"><FileText /></div>
              <div className="artifact-meta">
                <div className="artifact-name">{artifact.filename}</div>
                <div className="artifact-sub">
                  {formatBytes(artifact.size_bytes)} · {String(artifact.sha256).slice(0, 18)}…
                </div>
              </div>
              {row && (
                <button type="button" className="ghost-btn" onClick={() => onPreview(row)}>
                  <Eye />
                  Open
                </button>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default function AgentTurn({ run, onPreview, onShowWork }) {
  const working = run.status === "running" || run.status === "awaiting";
  const nothingYet =
    working && !run.findings.length && !run.table && !run.answer && !run.artifacts.length;

  const headline =
    run.status === "running" ? "Working on it"
      : run.status === "awaiting" ? "Waiting for your decision"
      : run.status === "failed" ? "Could not finish"
      : run.finalStatus === "rejected_final" ? "Sent back — not finalised"
      : "Done";

  return (
    <div className="turn turn-agent">
      <div className="agent-head">
        <span className="agent-avatar"><Sparkle /></span>
        <span>{headline}</span>
        {onShowWork && (
          <button type="button" className="mini-btn" onClick={onShowWork}>
            show the work
            <ChevronRight style={{ width: 11, height: 11, verticalAlign: "-1px" }} />
          </button>
        )}
      </div>

      <div className="turn-body">
        {nothingYet && (
          <div className="thinking">
            <span className="spinner" />
            <span>
              {run.steps[run.steps.length - 1]?.label || "Getting started"}
              <span className="dots" />
            </span>
          </div>
        )}

        {run.answer && (
          <section className="card">
            <div className="card-body"><div className="answer">{run.answer}</div></div>
          </section>
        )}

        <Findings findings={run.findings} />
        <MatchedRows table={run.table} dataset={run.dataset} />
        <Citations citations={run.citations} />
        <Artifacts runId={run.runId} artifacts={run.artifacts} onPreview={onPreview} />

        {run.error && (
          <div className="error-card">
            <div className="title">Something went wrong</div>
            {run.error}
          </div>
        )}
      </div>
    </div>
  );
}
