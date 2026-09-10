import { useRef, useState } from "react";
import { api } from "../api";
import { Book, Cpu, Lock, Plus, Shield } from "../icons";

function StatusRow({ level, label, title }) {
  return (
    <div className="status-row" title={title}>
      <span className={`dot ${level}`} />
      <span className="label">{label}</span>
    </div>
  );
}

function Stat({ value, label }) {
  return (
    <div className="stat">
      <div className="stat-v">{value}</div>
      <div className="stat-k">{label}</div>
    </div>
  );
}

export default function Sidebar({ status, sources, session, onNewRun, onIngested, busy }) {
  const fileRef = useRef(null);
  const [ingesting, setIngesting] = useState(false);
  const [message, setMessage] = useState("");

  async function handleIngest(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    setIngesting(true);
    setMessage(`Indexing ${file.name}…`);
    try {
      const uploaded = await api.uploadFile(file);
      await api.ingest(uploaded.file_id);
      // Ingestion is asynchronous; poll a few times for the chunk count.
      [1500, 4000, 9000, 16000].forEach((delay) => setTimeout(onIngested, delay));
      setMessage("Reading and indexing locally…");
      setTimeout(() => setMessage(""), 14000);
    } catch (error) {
      setMessage(error.message.slice(0, 90));
      setTimeout(() => setMessage(""), 6000);
    } finally {
      setIngesting(false);
    }
  }

  const egress = status?.egress || {};
  const models = status?.model_endpoints || [];
  const healthy = models.filter((m) => m.healthy).length;
  const totalChunks = sources.reduce((sum, s) => sum + (s.chunk_count || 0), 0);

  const level = (probe) => (!probe?.reporting ? "warn" : probe.egress_blocked ? "ok" : "bad");
  const modelLevel = !models.length ? "warn" : healthy === models.length ? "ok" : healthy ? "warn" : "bad";

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark"><Shield /></div>
        <div>
          <div className="brand-name">Sovereign Workbench</div>
          <div className="brand-sub">Runs entirely on this machine</div>
        </div>
      </div>

      <button type="button" className="side-btn is-primary" onClick={onNewRun} disabled={busy}>
        <Plus />
        New analysis
      </button>

      <div className="side-section">
        <div className="side-label">This session</div>
        <div className="stat-grid">
          <Stat value={session.runs} label={session.runs === 1 ? "analysis" : "analyses"} />
          <Stat value={session.approvals} label="approvals" />
          <Stat value={totalChunks} label="passages" />
        </div>
      </div>

      <div className="side-section">
        <div className="side-label">Reference library</div>
        <button
          type="button"
          className="side-btn"
          onClick={() => fileRef.current?.click()}
          disabled={ingesting}
        >
          <Book />
          {ingesting ? "Uploading…" : "Add a policy document"}
        </button>
        <input
          ref={fileRef}
          type="file"
          hidden
          accept=".pdf,.txt,.md,.docx,.png,.jpg,.jpeg"
          onChange={handleIngest}
        />

        <div className="kb-list">
          {sources.length === 0 && !message && (
            <div className="kb-empty">
              Nothing indexed yet. The agent can only cite documents you add here.
            </div>
          )}
          {message && <div className="kb-empty">{message}</div>}
          {sources.map((source) => (
            <div className="kb-item" key={source.source_hash} title={source.source_file}>
              <Book style={{ width: 12, height: 12, opacity: 0.5, flex: "none" }} />
              <span className="name">{source.source_file}</span>
              <span className="count">{source.chunk_count}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="side-section">
        <div className="side-label">System</div>
        <div className="status-rail">
          <StatusRow
            level={level(egress.worker)}
            label={
              level(egress.worker) === "ok" ? "No internet access"
                : level(egress.worker) === "bad" ? "Egress detected"
                : "Checking network…"
            }
            title="Probed from inside the agent container"
          />
          <StatusRow
            level={level(egress.sandbox)}
            label="Sandbox isolated"
            title={`Code execution container network mode: ${status?.sandbox_network_mode ?? "unknown"}`}
          />
          <StatusRow
            level={modelLevel}
            label={models.length ? `${healthy}/${models.length} models ready` : "Models loading…"}
            title={models.map((m) => m.ollama_model).join(", ")}
          />
        </div>
        <div className="model-chips">
          {models.map((model) => (
            <span
              className={`model-chip${model.healthy ? " is-ready" : ""}`}
              key={model.id}
              title={`${model.ollama_model} · ${model.endpoint}`}
            >
              <Cpu style={{ width: 10, height: 10 }} />
              {model.ollama_model}
            </span>
          ))}
        </div>
      </div>

      <div className="side-foot">
        <Lock style={{ width: 11, height: 11, verticalAlign: "-1px", marginRight: 5 }} />
        No data leaves this device
      </div>
    </aside>
  );
}
