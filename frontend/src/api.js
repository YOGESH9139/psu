// All requests go to the local API — same origin behind nginx.
const BASE = "";

async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, options);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      /* no JSON body */
    }
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

const json = (payload) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});

export const api = {
  uploadFile(file) {
    const form = new FormData();
    form.append("file", file);
    return request("/api/files", { method: "POST", body: form });
  },

  createRun(goal, fileIds, { workspace, parentRunId, model } = {}) {
    return request("/api/runs", json({
      goal,
      file_ids: fileIds,
      workspace: workspace || null,
      parent_run_id: parentRunId || null,
      model: model && model !== "auto" ? model : null,
    }));
  },

  ingest(fileId, workspace) {
    return request("/api/knowledge/ingest", json({ file_id: fileId, workspace: workspace || null }));
  },

  knowledgeSources(workspace) {
    const q = workspace ? `?workspace=${encodeURIComponent(workspace)}` : "";
    return request(`/api/knowledge/sources${q}`);
  },

  workspaces() {
    return request("/api/workspaces");
  },

  createWorkspace(name, template, banner) {
    return request("/api/workspaces", json({ name, template, banner }));
  },

  artifacts(runId) {
    return request(`/api/runs/${runId}/artifacts`);
  },

  decide(runId, decision, note) {
    return request(`/api/runs/${runId}/approval`, json({ decision, note }));
  },

  sovereignty() {
    return request("/api/sovereignty/status");
  },

  eventStreamUrl(runId) {
    return `${BASE}/api/runs/${runId}/events`;
  },

  downloadUrl(path) {
    return `${BASE}${path}`;
  },
};

/** Fetch a bundled sample file (served by nginx from /samples) as a File. */
export async function fetchSample(filename) {
  const response = await fetch(`/samples/${filename}`);
  if (!response.ok) throw new Error(`Sample ${filename} is not available`);
  const blob = await response.blob();
  return new File([blob], filename, { type: blob.type || "application/octet-stream" });
}

export function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDuration(ms) {
  if (!Number.isFinite(ms)) return "";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}
