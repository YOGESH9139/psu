import { useState } from "react";
import { api } from "../api";
import { TEMPLATES, loadLibrary } from "../workspaces";
import { Book, Code, Shield, Table } from "../icons";

const ICON = {
  "plant-maintenance": Table,
  "engineering-code": Code,
  "finance-procurement": Book,
  blank: Shield,
};

const BANNERS = ["INTERNAL", "RESTRICTED", "CONFIDENTIAL"];

/** First-run setup, and "new workspace" afterwards. */
export default function WorkspaceSetup({ first, onCreated, onCancel }) {
  const [templateKey, setTemplateKey] = useState(TEMPLATES[0].key);
  const [name, setName] = useState(TEMPLATES[0].name);
  const [banner, setBanner] = useState(TEMPLATES[0].banner);
  const [withSamples, setWithSamples] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const template = TEMPLATES.find((t) => t.key === templateKey);

  function pick(t) {
    // Keep a name the user typed; only follow the template while it is still the default.
    const wasDefault = TEMPLATES.some((x) => x.name === name);
    setTemplateKey(t.key);
    if (wasDefault) setName(t.name);
    setBanner(t.banner);
  }

  async function create() {
    setError("");
    setBusy("Creating workspace…");
    try {
      const workspace = await api.createWorkspace(name.trim() || template.name, template.key, banner);
      if (withSamples && template.library.length) {
        await loadLibrary(template, workspace.id, setBusy);
      }
      onCreated(workspace);
    } catch (e) {
      setError(e.message);
      setBusy("");
    }
  }

  return (
    <div className={`setup${first ? " is-first" : ""}`}>
      <div className="setup-card">
        <div className="setup-head">
          <div className="hero-mark"><Shield /></div>
          <h1>{first ? "Set up your workspace" : "New workspace"}</h1>
          <p>
            One general assistant, tuned to your team. A workspace keeps its own
            reference library, so answers only ever cite that team's documents.
          </p>
        </div>

        <div className="setup-templates">
          {TEMPLATES.map((t) => {
            const Icon = ICON[t.key] || Shield;
            return (
              <button
                key={t.key}
                type="button"
                className={`setup-template${t.key === templateKey ? " is-picked" : ""}`}
                onClick={() => pick(t)}
                disabled={Boolean(busy)}
              >
                <span className="hc-icon"><Icon /></span>
                <span className="hc-text">
                  <span className="hc-label">{t.name}</span>
                  <span className="hc-hint">{t.blurb}</span>
                </span>
              </button>
            );
          })}
        </div>

        <div className="setup-fields">
          <label htmlFor="ws-name">Workspace name</label>
          <input
            id="ws-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={Boolean(busy)}
          />

          <label htmlFor="ws-banner">Classification marking</label>
          <select id="ws-banner" value={banner} onChange={(e) => setBanner(e.target.value)} disabled={Boolean(busy)}>
            {BANNERS.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>

          {template.library.length > 0 && (
            <label className="setup-check" htmlFor="ws-samples">
              <input
                id="ws-samples"
                type="checkbox"
                checked={withSamples}
                onChange={(e) => setWithSamples(e.target.checked)}
                disabled={Boolean(busy)}
              />
              Load the sample documents ({template.library.join(", ")})
            </label>
          )}
        </div>

        {error && <div className="setup-error">{error}</div>}

        <div className="setup-foot">
          {!first && (
            <button type="button" className="ghost-btn" onClick={onCancel} disabled={Boolean(busy)}>
              Cancel
            </button>
          )}
          <button type="button" className="btn btn-approve setup-go" onClick={create} disabled={Boolean(busy)}>
            {busy || "Create workspace"}
          </button>
        </div>
      </div>
    </div>
  );
}
