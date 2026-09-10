import { useCallback, useEffect, useRef, useState } from "react";
import { api, formatBytes } from "./api";
import { Eye, FileText, Lock, Shield, Sparkle, Table, Terminal } from "./icons";
import { useRunStream } from "./useRunStream";
import AgentTurn from "./components/AgentTurn";
import ApprovalDialog from "./components/ApprovalDialog";
import Composer from "./components/Composer";
import DocumentPreview from "./components/DocumentPreview";
import RunPanel from "./components/RunPanel";
import Sidebar from "./components/Sidebar";
import SovereigntyDrawer from "./components/SovereigntyDrawer";

const STATUS_POLL_MS = 6000;

const SUGGESTIONS = [
  {
    icon: Table,
    label: "Machines running too hot",
    hint: "shift log + maintenance policy",
    goal:
      "Which machines are running above 85 degrees C? Check them against our " +
      "maintenance policy and draft a maintenance approval note.",
  },
  {
    icon: Table,
    label: "Where the shift lost time",
    hint: "downtime breakdown",
    goal: "Which machines had downtime over 60 minutes? Summarise the impact on output.",
  },
  {
    icon: Terminal,
    label: "Fix a bug and test it",
    hint: "runs in the sandbox",
    goal:
      "Fix the off-by-one bug in this code so a reading exactly at the limit is " +
      "not reported as a breach, and make the pytest tests pass.",
  },
];

export default function App() {
  const { run, start, reset, fail } = useRunStream();
  const [prompt, setPrompt] = useState(null);
  const [status, setStatus] = useState(null);
  const [sources, setSources] = useState([]);
  const [session, setSession] = useState({ runs: 0, approvals: 0 });
  const [drawer, setDrawer] = useState(false);
  const [panel, setPanel] = useState(true);
  const [previewing, setPreviewing] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [draft, setDraft] = useState("");
  const streamRef = useRef(null);

  const refreshSources = useCallback(() => {
    api.knowledgeSources().then(setSources).catch(() => {});
  }, []);

  useEffect(() => {
    const tick = () => api.sovereignty().then(setStatus).catch(() => setStatus(null));
    tick();
    refreshSources();
    const timer = setInterval(tick, STATUS_POLL_MS);
    return () => clearInterval(timer);
  }, [refreshSources]);

  // Keep the newest result in view while the agent is working.
  useEffect(() => {
    const el = streamRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [run.findings.length, run.artifacts.length, run.status, run.table]);

  const busy = submitting || run.status === "running" || run.status === "awaiting";
  const active = run.status !== "idle";

  async function handleSubmit(goal, file) {
    setSubmitting(true);
    reset();
    setPanel(true);
    setDrawer(false);
    setPrompt({ goal, fileName: file?.name, fileSize: file?.size });
    setSession((s) => ({ ...s, runs: s.runs + 1 }));

    try {
      const fileIds = [];
      if (file) {
        const uploaded = await api.uploadFile(file);
        fileIds.push(uploaded.file_id);
      }
      const created = await api.createRun(goal, fileIds);
      start(created.run_id, created.router_decision);
    } catch (error) {
      start(null, null);
      fail(error.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDecision(decision, note) {
    await api.decide(run.runId, decision, note);
    setSession((s) => ({ ...s, approvals: s.approvals + 1 }));
  }

  function handleNewRun() {
    reset();
    setPrompt(null);
    setPreviewing(null);
  }

  const showPanel = active && panel;

  return (
    <div
      className={`shell${showPanel ? " with-panel" : ""}${drawer ? " with-drawer" : ""}`}
    >
      <Sidebar
        status={status}
        sources={sources}
        session={session}
        onNewRun={handleNewRun}
        onIngested={refreshSources}
        busy={busy}
      />

      <main className="main">
        <header className="topbar">
          <div className="topbar-left">
            <h2>{active ? "Analysis" : "Workbench"}</h2>
            {run.runId && <span className="run-id">{run.runId.slice(0, 8)}</span>}
          </div>
          <div className="topbar-right">
            {active && !panel && (
              <button type="button" className="ghost-btn" onClick={() => setPanel(true)}>
                <Sparkle />
                Show the work
              </button>
            )}
            <button
              type="button"
              className={`ghost-btn${drawer ? " is-on" : ""}`}
              onClick={() => setDrawer((v) => !v)}
            >
              <Shield />
              Proof of isolation
            </button>
          </div>
        </header>

        {!active ? (
          <div className="hero">
            <div className="hero-mark"><Sparkle /></div>
            <h1>What should the agent look at?</h1>
            <p>
              Attach a shift log, a policy document or a script. The agent reads it,
              checks it against your own reference library, and drafts a note for
              you to approve — all on this machine.
            </p>

            <div className="hero-cards">
              {SUGGESTIONS.map((suggestion) => {
                const Icon = suggestion.icon;
                return (
                  <button
                    type="button"
                    className="hero-card"
                    key={suggestion.label}
                    onClick={() => setDraft(suggestion.goal)}
                  >
                    <span className="hc-icon"><Icon /></span>
                    <span className="hc-text">
                      <span className="hc-label">{suggestion.label}</span>
                      <span className="hc-hint">{suggestion.hint}</span>
                    </span>
                  </button>
                );
              })}
            </div>

            <div className="hero-badges">
              <span className="hero-badge"><Lock style={{ width: 12, height: 12 }} /> No internet access</span>
              <span className="hero-badge"><Eye style={{ width: 12, height: 12 }} /> Every step visible</span>
              <span className="hero-badge"><FileText style={{ width: 12, height: 12 }} /> You approve the output</span>
            </div>
          </div>
        ) : (
          <div className="stream" ref={streamRef}>
            <div className="stream-inner">
              {prompt && (
                <div className="turn turn-user">
                  <div className="bubble">
                    {prompt.goal}
                    {prompt.fileName && (
                      <div className="attachment">
                        <FileText />
                        {prompt.fileName}
                        <span style={{ opacity: 0.6 }}>{formatBytes(prompt.fileSize)}</span>
                      </div>
                    )}
                  </div>
                </div>
              )}
              <AgentTurn
                run={run}
                onPreview={setPreviewing}
                onShowWork={() => setPanel(true)}
              />
            </div>
          </div>
        )}

        <Composer
          onSubmit={handleSubmit}
          busy={busy}
          draft={draft}
          onDraftChange={setDraft}
        />
      </main>

      {showPanel && <RunPanel run={run} onClose={() => setPanel(false)} />}
      {drawer && <SovereigntyDrawer status={status} />}

      {previewing && (
        <DocumentPreview artifact={previewing} onClose={() => setPreviewing(null)} />
      )}

      {run.status === "awaiting" && run.approval && (
        <ApprovalDialog
          approval={run.approval}
          onDecide={handleDecision}
          onReadDraft={() =>
            api.artifacts(run.runId)
              .then((rows) => rows[0] && setPreviewing(rows[0]))
              .catch(() => {})
          }
        />
      )}
    </div>
  );
}
