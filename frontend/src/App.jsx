import { useCallback, useEffect, useRef, useState } from "react";
import { api, fetchSample, formatBytes } from "./api";
import { Eye, FileText, Lock, Search, Shield, Sparkle, Table, Terminal } from "./icons";
import { useRunStream } from "./useRunStream";
import { templateOf } from "./workspaces";
import AgentTurn from "./components/AgentTurn";
import ApprovalDialog from "./components/ApprovalDialog";
import Composer from "./components/Composer";
import DocumentPreview from "./components/DocumentPreview";
import Guide from "./components/Guide";
import RunPanel from "./components/RunPanel";
import Sidebar from "./components/Sidebar";
import SovereigntyDrawer from "./components/SovereigntyDrawer";
import WorkspaceSetup from "./components/WorkspaceSetup";

const STATUS_POLL_MS = 6000;
const TASK_ICON = { table: Table, code: Terminal, ask: Search };

const remember = (key, value) => {
  try {
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* private mode */
  }
};
const recall = (key) => {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
};

function UserBubble({ prompt }) {
  return (
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
  );
}

export default function App() {
  const { run, start, reset, fail } = useRunStream();
  const [workspaces, setWorkspaces] = useState(null); // null = still loading
  const [currentId, setCurrentId] = useState(recall("workspace"));
  const [creating, setCreating] = useState(false);
  const [view, setView] = useState("workbench"); // workbench | guide
  const [prompt, setPrompt] = useState(null);
  const [thread, setThread] = useState([]); // earlier turns of this conversation
  const [status, setStatus] = useState(null);
  const [sources, setSources] = useState([]);
  const [session, setSession] = useState({ runs: 0, approvals: 0 });
  const [drawer, setDrawer] = useState(false);
  const [panel, setPanel] = useState(true);
  const [previewing, setPreviewing] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [draft, setDraft] = useState("");
  const [model, setModel] = useState("auto"); // "auto" = the router decides
  const [preset, setPreset] = useState({ file: null, key: 0 });
  const streamRef = useRef(null);

  const current = workspaces?.find((w) => w.id === currentId) || workspaces?.[0] || null;
  const template = current ? templateOf(current.template) : null;
  const currentWorkspaceId = current?.id;

  const refreshWorkspaces = useCallback(async () => {
    try {
      const list = await api.workspaces();
      setWorkspaces(list);
      return list;
    } catch {
      setWorkspaces((prev) => prev ?? []);
      return [];
    }
  }, []);

  const refreshSources = useCallback(() => {
    if (!currentWorkspaceId) return;
    api.knowledgeSources(currentWorkspaceId).then(setSources).catch(() => {});
  }, [currentWorkspaceId]);

  useEffect(() => {
    refreshWorkspaces();
  }, [refreshWorkspaces]);

  useEffect(() => {
    setSources([]);
    refreshSources();
  }, [refreshSources]);

  useEffect(() => {
    const tick = () => api.sovereignty().then(setStatus).catch(() => setStatus(null));
    tick();
    const timer = setInterval(tick, STATUS_POLL_MS);
    return () => clearInterval(timer);
  }, []);

  // Keep the newest result in view while the agent is working.
  useEffect(() => {
    const el = streamRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [run.findings.length, run.artifacts.length, run.status, run.table, thread.length]);

  const busy = submitting || run.status === "running" || run.status === "awaiting";
  const active = run.status !== "idle" || thread.length > 0;

  function clearConversation() {
    reset();
    setPrompt(null);
    setThread([]);
    setPreviewing(null);
  }

  function switchWorkspace(id) {
    if (id === current?.id) return;
    setCurrentId(id);
    remember("workspace", id);
    clearConversation();
    setDraft("");
    setPreset((p) => ({ file: null, key: p.key + 1 }));
    setView("workbench");
  }

  async function handleCreated(workspace) {
    await refreshWorkspaces();
    setCurrentId(workspace.id);
    remember("workspace", workspace.id);
    setCreating(false);
    clearConversation();
    // Indexing runs in the worker; poll until the passages appear.
    [2500, 6000, 12000, 20000].forEach((delay) =>
      setTimeout(() => api.knowledgeSources(workspace.id).then(setSources).catch(() => {}), delay)
    );
  }

  async function usePrompt(goal, sample) {
    setView("workbench");
    setDraft(goal);
    try {
      const file = sample ? await fetchSample(sample) : null;
      setPreset((p) => ({ file, key: p.key + 1 }));
    } catch {
      setPreset((p) => ({ file: null, key: p.key + 1 }));
    }
  }

  async function handleSubmit(goal, file) {
    // A finished run means this message continues the conversation.
    const parentRunId = run.status === "done" ? run.runId : null;

    setSubmitting(true);
    if (prompt && run.status !== "idle") {
      setThread((t) => [...t, { prompt, run }]);
    }
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
      const created = await api.createRun(goal, fileIds, {
        workspace: currentWorkspaceId,
        parentRunId,
        model,
      });
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

  if (workspaces === null) {
    return <div className="boot">Starting the workbench…</div>;
  }

  if (workspaces.length === 0 || creating) {
    return (
      <WorkspaceSetup
        first={workspaces.length === 0}
        onCreated={handleCreated}
        onCancel={() => setCreating(false)}
      />
    );
  }

  const showPanel = view === "workbench" && active && panel && run.status !== "idle";
  const tasks = template?.tasks || [];

  return (
    <div className={`shell${showPanel ? " with-panel" : ""}${drawer ? " with-drawer" : ""}`}>
      <Sidebar
        status={status}
        sources={sources}
        session={session}
        workspaces={workspaces}
        current={current}
        onSwitch={switchWorkspace}
        onNewWorkspace={() => setCreating(true)}
        onNewRun={() => {
          clearConversation();
          setView("workbench");
        }}
        onIngested={refreshSources}
        busy={busy}
      />

      <main className="main">
        <header className="topbar">
          <div className="topbar-left">
            <div className="viewtabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={view === "workbench"}
                className={view === "workbench" ? "is-on" : ""}
                onClick={() => setView("workbench")}
              >
                Workbench
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={view === "guide"}
                className={view === "guide" ? "is-on" : ""}
                onClick={() => setView("guide")}
              >
                Guide
              </button>
            </div>
            {view === "workbench" && run.runId && <span className="run-id">{run.runId.slice(0, 8)}</span>}
          </div>
          <div className="topbar-right">
            {current && <span className="banner-chip">{current.banner}</span>}
            {view === "workbench" && run.status !== "idle" && !panel && (
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

        {view === "guide" ? (
          <Guide onTry={(f) => usePrompt(f.tryGoal, f.sample)} />
        ) : !active ? (
          <div className="hero">
            <div className="hero-mark">
              <Sparkle />
            </div>
            <h1>{current.name}</h1>
            <p>
              Attach a file, or ask a question. The agent reads it, checks it against this
              workspace's library, and drafts a note for you to approve, all on this machine.
            </p>

            {tasks.length > 0 && (
              <div className="hero-cards">
                {tasks.map((task) => {
                  const Icon = TASK_ICON[task.icon] || Sparkle;
                  return (
                    <button
                      type="button"
                      className="hero-card"
                      key={task.label}
                      onClick={() => usePrompt(task.goal, task.sample)}
                    >
                      <span className="hc-icon">
                        <Icon />
                      </span>
                      <span className="hc-text">
                        <span className="hc-label">{task.label}</span>
                        <span className="hc-hint">{task.hint}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            )}

            <div className="hero-badges">
              <span className="hero-badge">
                <Lock style={{ width: 12, height: 12 }} /> No internet access
              </span>
              <span className="hero-badge">
                <Eye style={{ width: 12, height: 12 }} /> Every step visible
              </span>
              <span className="hero-badge">
                <FileText style={{ width: 12, height: 12 }} /> You approve the output
              </span>
            </div>
          </div>
        ) : (
          <div className="stream" ref={streamRef}>
            <div className="stream-inner">
              {thread.map((turn, index) => (
                <div className="thread-turn" key={index}>
                  <UserBubble prompt={turn.prompt} />
                  <AgentTurn run={turn.run} onPreview={setPreviewing} onShowWork={null} />
                </div>
              ))}
              {prompt && <UserBubble prompt={prompt} />}
              {run.status !== "idle" && (
                <AgentTurn run={run} onPreview={setPreviewing} onShowWork={() => setPanel(true)} />
              )}
            </div>
          </div>
        )}

        {view === "workbench" && (
          <Composer
            onSubmit={handleSubmit}
            busy={busy}
            draft={draft}
            onDraftChange={setDraft}
            preset={preset}
            models={status?.model_endpoints || []}
            model={model}
            onModelChange={setModel}
            placeholder={
              run.status === "done"
                ? "Ask a follow-up about this result…"
                : "Ask about a report, a spreadsheet, or some code…"
            }
          />
        )}
      </main>

      {showPanel && <RunPanel run={run} onClose={() => setPanel(false)} />}
      {drawer && <SovereigntyDrawer status={status} />}

      {previewing && <DocumentPreview artifact={previewing} onClose={() => setPreviewing(null)} />}

      {run.status === "awaiting" && run.approval && (
        <ApprovalDialog
          approval={run.approval}
          onDecide={handleDecision}
          onReadDraft={() =>
            api
              .artifacts(run.runId)
              .then((rows) => rows[0] && setPreviewing(rows[0]))
              .catch(() => {})
          }
        />
      )}
    </div>
  );
}
