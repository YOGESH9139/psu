import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

// Human-readable labels for the tools the agent may call.
const TOOL_LABEL = {
  extract_pdf_pages: "Reading the document pages",
  run_ocr: "Extracting text from the scan",
  inspect_image: "Looking at the image",
  search_knowledge: "Searching the policy library",
  read_source_excerpt: "Reading the source passage",
  read_spreadsheet: "Opening the spreadsheet",
  analyze_spreadsheet: "Analysing the readings",
  create_approval_docx: "Writing the approval note",
  verify_docx: "Checking the document",
  write_code_file: "Writing the code",
  run_code_tests: "Running tests in the sandbox",
  list_run_artifacts: "Collecting the output",
  request_human_approval: "Requesting human sign-off",
};

const STAGE_LABEL = {
  INTAKE: "Taking in the request",
  PREFLIGHT: "Checking local services",
  ROUTE: "Choosing a model",
  PLAN: "Planning the steps",
  VERIFY: "Verifying the result",
  AWAIT_APPROVAL: "Waiting for your decision",
  DELIVER: "Finishing up",
};

const FAILED = new Set(["error", "rejected", "blocked", "timeout"]);

const emptyRun = () => ({
  runId: null,
  status: "idle", // idle | running | awaiting | done | failed
  router: null,
  steps: [],
  stage: null,
  findings: [],
  citations: [],
  artifacts: [],
  table: null,
  dataset: null,
  answer: null,
  verification: null,
  approval: null,
  error: null,
  notices: [],
  startedAt: null,
  finishedAt: null,
});

/** Detail line shown under a completed step. */
function describe(tool, result = {}) {
  switch (tool) {
    case "extract_pdf_pages":
      return result.page_count ? `${result.page_count} pages` : "";
    case "run_ocr":
      return result.word_count
        ? `${result.word_count} words · ${Math.round(result.confidence)}% confidence`
        : "";
    case "inspect_image":
      return result.anomalies_found ? "Possible issue spotted" : "No visible issue";
    case "search_knowledge":
      return `${result.result_count ?? 0} matching passages`;
    case "read_spreadsheet":
      return result.row_count ? `${result.row_count} rows · ${result.sheet_names?.length ?? 1} sheets` : "";
    case "analyze_spreadsheet":
      return result.match_count != null ? `${result.match_count} rows matched` : result.interpretation || "";
    case "create_approval_docx":
      return `${result.findings_count ?? 0} findings · ${result.citation_count ?? 0} citations`;
    case "verify_docx":
      return result.valid ? "Document is valid" : result.reason || "Document failed checks";
    case "run_code_tests":
      return result.passed ? "All tests passed" : `Tests failed (exit ${result.exit_code})`;
    case "write_code_file":
      return result.line_count ? `${result.line_count} lines` : "";
    default:
      return result.error ? String(result.error).slice(0, 120) : "";
  }
}

export function useRunStream() {
  const [run, setRun] = useState(emptyRun);
  const sourceRef = useRef(null);

  const close = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
  }, []);

  useEffect(() => close, [close]);

  const reset = useCallback(() => {
    close();
    setRun(emptyRun());
  }, [close]);

  const handle = useCallback((message) => {
    const data = message.data || {};

    setRun((prev) => {
      const next = { ...prev };

      switch (message.type) {
        case "router_decision":
          next.router = data;
          break;

        case "state_change": {
          next.stage = data.state;
          const label = STAGE_LABEL[data.state];
          // ACT and OBSERVE are represented by their tool row, not a stage row.
          if (label) {
            const steps = next.steps.map((s) =>
              s.state === "active" ? { ...s, state: "done" } : s
            );
            const last = next.steps[next.steps.length - 1];
            // A stage can legitimately recur (PLAN after a re-plan), so the key
            // carries a sequence number — reusing the bare stage name collides
            // in React and strands the earlier row's spinner.
            if (!(last?.kind === "stage" && last.stage === data.state)) {
              steps.push({
                kind: "stage",
                key: `stage-${data.state}-${steps.length}`,
                stage: data.state,
                label,
                state: "active",
              });
            }
            next.steps = steps;
          }
          break;
        }

        case "tool_call": {
          const steps = next.steps.map((s) =>
            s.state === "active" ? { ...s, state: "done" } : s
          );
          steps.push({
            kind: "tool",
            key: `tool-${data.tool}-${steps.length}`,
            tool: data.tool,
            label: TOOL_LABEL[data.tool] || data.tool,
            state: "active",
          });
          next.steps = steps;
          break;
        }

        case "tool_result": {
          const result = data.result || {};
          const failed = FAILED.has(result.status) || result.valid === false || result.passed === false;
          let patched = false;
          next.steps = next.steps.map((s) => {
            if (!patched && s.kind === "tool" && s.tool === data.tool && s.state === "active") {
              patched = true;
              return {
                ...s,
                state: failed ? "fail" : "done",
                detail: describe(data.tool, result),
                durationMs: data.duration_ms,
                hash: data.hash,
                result,
              };
            }
            return s;
          });
          if (data.tool === "search_knowledge" && result.citations?.length) {
            next.citations = result.citations;
          }
          // The matched rows ARE the answer for a spreadsheet question. Showing
          // them as data is what separates this from a chatbot's paragraph.
          if (data.tool === "analyze_spreadsheet" && result.matched_rows?.length) {
            next.table = {
              rows: result.matched_rows,
              interpretation: result.interpretation,
              filter: result.filter,
              matchCount: result.match_count,
            };
          }
          if (data.tool === "read_spreadsheet") {
            next.dataset = {
              rowCount: result.row_count,
              sheets: result.sheet_names,
              columns: result.columns,
            };
          }
          break;
        }

        case "tool_blocked":
          next.steps = [
            ...next.steps,
            { kind: "tool", key: `blocked-${data.tool}-${next.steps.length}`, tool: data.tool,
              label: `Blocked: ${data.tool}`, state: "fail", detail: data.error },
          ];
          break;

        case "verification":
          next.verification = data;
          break;

        case "repair":
        case "replan":
          next.notices = [...next.notices, { kind: message.type, text: data.reason }];
          break;

        case "agent_answer":
          next.answer = data.answer;
          if (data.citations?.length) next.citations = data.citations;
          break;

        case "awaiting_approval":
          next.status = "awaiting";
          next.approval = data;
          if (data.findings?.length) next.findings = data.findings;
          if (data.citations?.length) next.citations = data.citations;
          // The draft is registered before the run blocks, so it can be read
          // while the decision is still open.
          if (data.artifacts?.length) next.artifacts = data.artifacts;
          break;

        case "approval_recorded":
          next.approval = null;
          next.status = "running";
          next.decision = data.decision;
          break;

        case "artifacts":
          if (data.artifacts?.length) next.artifacts = data.artifacts;
          break;

        case "run_complete":
          next.status = "done";
          next.finishedAt = Date.now();
          next.stage = "DELIVER";
          next.steps = next.steps.map((s) => (s.state === "active" ? { ...s, state: "done" } : s));
          if (data.artifacts?.length) next.artifacts = data.artifacts;
          next.finalStatus = data.status;
          break;

        case "run_error":
          next.status = "failed";
          next.finishedAt = Date.now();
          next.error = data.error;
          next.steps = next.steps.map((s) => (s.state === "active" ? { ...s, state: "fail" } : s));
          break;

        default:
          break;
      }
      return next;
    });

    if (message.type === "run_complete" || message.type === "run_error") close();
  }, [close]);

  const start = useCallback((runId, router) => {
    close();
    setRun({
      ...emptyRun(),
      runId,
      router: router ?? null,
      status: "running",
      startedAt: Date.now(),
    });

    const source = new EventSource(api.eventStreamUrl(runId));
    sourceRef.current = source;
    source.onmessage = (event) => {
      try {
        handle(JSON.parse(event.data));
      } catch {
        /* ignore malformed frame */
      }
    };
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) close();
    };
  }, [close, handle]);

  const fail = useCallback((error) => {
    setRun((prev) => ({ ...prev, status: "failed", error }));
  }, []);

  return { run, start, reset, fail, setRun };
}
