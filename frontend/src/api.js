// All requests go to the local API — same origin behind nginx in the container,
// or 127.0.0.1:8000 when running `npm run dev` against a running stack.
const BASE = import.meta.env.DEV ? "" : "";

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

  createRun(goal, fileIds) {
    return request("/api/runs", json({ goal, file_ids: fileIds }));
  },

  ingest(fileId) {
    return request("/api/knowledge/ingest", json({ file_id: fileId }));
  },

  knowledgeSources() {
    return request("/api/knowledge/sources");
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
